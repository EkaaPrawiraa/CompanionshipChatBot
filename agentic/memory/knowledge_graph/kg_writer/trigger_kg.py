"""
agentic/memory/kg_writer/trigger_kg.py

Writer for the :Trigger node and the (:User)-[:HAS_TRIGGER]->(:Trigger)
edge.

Dedup strategy for triggers is keyword-based on the fast path (LLM
rarely invents new categories and the description space is narrow),
falling back to pgvector cosine for cross-phrasing entity dedup
(DevNotes v1.3 Section 1.3 marks Trigger as embeddable for cases like
"exam stress" / "academic anxiety" / "test fear"). On a hit we
increment frequency, bump last_seen, and fold any new phrasing into
the canonical node's ``aliases`` array (per KG_Schema_Design.md
section 2.5).

Embedding flow (DevNotes v1.3, Section 1.4)
-------------------------------------------
The dense vector is NEVER stored on the Neo4j node. CREATE sets
``embedding_synced = false`` and the cross-store helper writes the
matching pgvector row.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import (
    MERGE_THRESHOLD,
    _new_id,
    _require,
)
from agentic.memory.knowledge_graph.kg_retriever.schemas import TriggerInput
from agentic.memory.neo4j_client     import get_client
from agentic.memory.cross_store_sync import (
    find_similar_node,
    sync_embedding_to_pgvector,
)

logger = logging.getLogger(__name__)


async def write_trigger(inp: TriggerInput) -> str:
    """
    MERGE :Trigger by (user_id, category, description prefix) on the
    fast path; fall back to pgvector cosine for cross-phrasing dedup.

    On match:
      * frequency += 1
      * last_seen refreshed to now
      * aliases gains the incoming description (and any caller-supplied
        aliases) when they differ from the canonical description and
        are not already present
    On create:
      * aliases is initialized from ``inp.aliases`` (defaults to empty)
      * embedding_synced is initialized to false; the cross-store helper
        flips it to true once the pgvector row is written

    Returns the node id.
    """
    _require(inp.category,    "category")
    _require(inp.description, "description")
    _require(inp.user_id,     "user_id")
    _require(inp.session_id,  "session_id")

    client = get_client()

    # ── 1. Fast-path keyword match ─────────────────────────────────────────
    existing = await client.execute_read_single(
        """
        MATCH (u:User {id: $user_id})-[:HAS_TRIGGER]->(t:Trigger)
        WHERE t.category = $category
          AND t.active   = true
          AND toLower(t.description) CONTAINS toLower($keyword)
        RETURN t.id AS id, t.frequency AS frequency, t.description AS canonical
        ORDER BY t.frequency DESC
        LIMIT 1
        """,
        {
            "user_id":  inp.user_id,
            "category": inp.category,
            "keyword":  inp.description[:30],
        },
    )

    # ── 1b. Slow-path cosine match (cross-phrasing entity dedup) ───────────
    # Only consulted if the keyword fast path missed AND the caller
    # supplied an embedding. The threshold logic mirrors Experience /
    # Thought: at or above MERGE_THRESHOLD we treat the existing node
    # as canonical and just absorb the new phrasing into its aliases.
    if existing is None and inp.embedding is not None:
        similar = await find_similar_node(
            label="Trigger",
            embedding=inp.embedding,
            user_id=inp.user_id,
        )
        if similar and similar["similarity"] >= MERGE_THRESHOLD:
            existing = {
                "id":        similar["id"],
                "frequency": None,                 # not needed for the merge
                "canonical": similar["description"],
            }
            logger.debug(
                "Trigger cosine-merged: %.2f similarity to %s",
                similar["similarity"], similar["id"],
            )

    if existing:
        # Build the candidate aliases list: the new phrasing plus any
        # aliases the caller supplied. We drop the canonical description
        # itself; the Cypher side will dedup against existing aliases.
        canonical = existing["canonical"]
        candidate_aliases: list[str] = []
        if inp.description and inp.description != canonical:
            candidate_aliases.append(inp.description)
        for alias in (inp.aliases or []):
            if alias and alias != canonical and alias not in candidate_aliases:
                candidate_aliases.append(alias)

        await client.execute_write(
            """
            MATCH (t:Trigger {id: $id})
            SET t.frequency = t.frequency + 1,
                t.last_seen = datetime(),
                t.aliases   = [
                    alias IN coalesce(t.aliases, []) + $candidate_aliases
                    WHERE alias IS NOT NULL
                      AND alias <> t.description
                    | alias
                ]
            WITH t
            // Collapse aliases to unique values while preserving first-seen order.
            UNWIND t.aliases AS a
            WITH t, collect(DISTINCT a) AS deduped
            SET t.aliases = deduped
            WITH t
            MATCH (u:User {id: $user_id})-[r:HAS_TRIGGER]->(t)
            WHERE r.t_invalid IS NULL
              AND $message_id IS NOT NULL
              AND NOT $message_id IN coalesce(r.source_messages, [])
            SET r.source_messages = coalesce(r.source_messages, []) + $message_id
            """,
            {
                "id":                 existing["id"],
                "candidate_aliases":  candidate_aliases,
                "user_id":            inp.user_id,
                "message_id":         inp.source_message_id,
            },
        )
        logger.debug(
            "Trigger frequency incremented: %s (added %d alias(es))",
            existing["id"], len(candidate_aliases),
        )
        return existing["id"]

    # ── 2. CREATE path ─────────────────────────────────────────────────────
    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (t:Trigger {
            id:                $id,
            category:          $category,
            description:       $description,
            frequency:         1,
            first_seen:        datetime(),
            last_seen:         datetime(),
            active:            true,
            aliases:           $aliases,
            embedding_synced:  false,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:HAS_TRIGGER {
            t_valid:         datetime(),
            t_invalid:       null,
            confidence:      $confidence,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(t)
        RETURN t.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "category":          inp.category,
            "description":       inp.description,
            "aliases":           list(inp.aliases or []),
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
            "message_id":        inp.source_message_id,
        },
    )

    # Mirror vector into pgvector and flip embedding_synced on success.
    await sync_embedding_to_pgvector(
        label="Trigger",
        node_id=node_id,
        user_id=inp.user_id,
        content=inp.description,
        embedding=inp.embedding,
        importance=0.5,
    )

    logger.debug("Trigger written: %s", node_id)
    return node_id
