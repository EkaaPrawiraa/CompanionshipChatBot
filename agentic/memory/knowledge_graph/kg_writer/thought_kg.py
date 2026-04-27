"""
agentic/memory/kg_writer/thought_kg.py

Writer for the :Thought node and the (:User)-[:HAS_THOUGHT]->(:Thought)
edge, with cosine-similarity deduplication.

Dedup rules (DevNotes v1.1, Section 2; backed by pgvector per v1.3
Section 1.4):
    similarity >= 0.85  -> merge: average believability, reset challenged flag
    0.65 <= sim < 0.85  -> log for LLM merge review; still CREATE a new node
    similarity  < 0.65  -> CREATE a new node

The supersession path (CBT reframe) is handled by supersede_thought in
supersession.py; this writer never flips active to false.

Embedding flow (DevNotes v1.3, Section 1.4)
-------------------------------------------
The dense vector is NEVER stored on the Neo4j node. The CREATE clause
sets ``embedding_synced = false`` and the cross-store helper
``sync_embedding_to_pgvector`` writes to pgvector then flips the flag.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import (
    MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    _new_id,
    _now_iso,
    _require,
)
from agentic.memory.knowledge_graph.kg_retriever.schemas import ThoughtInput
from agentic.memory.neo4j_client     import get_client
from agentic.memory.cross_store_sync import (
    find_similar_node,
    sync_embedding_to_pgvector,
)

logger = logging.getLogger(__name__)


async def write_thought(inp: ThoughtInput) -> str:
    """
    Write a :Thought node with cosine deduplication (pgvector backed).
    Returns the node id of the merged or newly-created node.
    """
    _require(inp.content,    "content")
    _require(inp.user_id,    "user_id")
    _require(inp.session_id, "session_id")

    client = get_client()

    # ── 1. Deduplication lookup (pgvector) ─────────────────────────────────
    existing = await find_similar_node(
        label="Thought",
        embedding=inp.embedding,
        user_id=inp.user_id,
    )

    # ── 2a. MERGE path ─────────────────────────────────────────────────────
    if existing and existing["similarity"] >= MERGE_THRESHOLD:
        # Average believability, reset challenged, and append the new
        # message id to the user-anchor edge's source_messages so the
        # lifecycle module can trace this thought back to every message
        # that contributed to it.
        await client.execute_write(
            """
            MATCH (th:Thought {id: $id})
            SET th.believability = (th.believability + $believability) / 2.0,
                th.challenged    = false
            WITH th
            MATCH (u:User {id: $user_id})-[r:HAS_THOUGHT]->(th)
            WHERE r.t_invalid IS NULL
              AND $message_id IS NOT NULL
              AND NOT $message_id IN coalesce(r.source_messages, [])
            SET r.source_messages = coalesce(r.source_messages, []) + $message_id
            """,
            {
                "id":            existing["id"],
                "believability": inp.believability,
                "user_id":       inp.user_id,
                "message_id":    inp.source_message_id,
            },
        )
        logger.debug("Thought merged into existing: %s", existing["id"])
        return existing["id"]

    # ── 2b. LLM-review zone: still CREATE a new node but flag the overlap ──
    if existing and existing["similarity"] >= REVIEW_THRESHOLD:
        logger.info(
            "Thought similarity %.2f in review zone -- writing new node "
            "(LLM merge review flagged): '%s' vs '%s'",
            existing["similarity"],
            inp.content[:60],
            existing["description"][:60],
        )

    # ── 3. CREATE path ─────────────────────────────────────────────────────
    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (th:Thought {
            id:                $id,
            content:           $content,
            thought_type:      $thought_type,
            distortion:        $distortion,
            believability:     $believability,
            challenged:        false,
            active:            true,
            timestamp:         datetime($timestamp),
            embedding_synced:  false,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:HAS_THOUGHT {
            t_valid:         datetime($timestamp),
            t_invalid:       null,
            confidence:      $confidence,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(th)
        RETURN th.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "content":           inp.content,
            "thought_type":      inp.thought_type,
            "distortion":        inp.distortion,
            "believability":     inp.believability,
            "timestamp":         _now_iso(),
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
            "message_id":        inp.source_message_id,
        },
    )

    # Mirror vector into pgvector and flip embedding_synced on success.
    await sync_embedding_to_pgvector(
        label="Thought",
        node_id=node_id,
        user_id=inp.user_id,
        content=inp.content,
        embedding=inp.embedding,
        importance=inp.believability,
    )

    logger.debug("Thought written: %s", node_id)
    return node_id
