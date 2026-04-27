"""
agentic/memory/kg_writer/experience_kg.py

Writer for the :Experience node (CBT Situation) and its two anchor edges:
    (:User)-[:EXPERIENCED]->(:Experience)
    (:Session)-[:HAD_EXPERIENCE]->(:Experience)

Deduplicated via cosine similarity (now backed by pgvector, see DevNotes
v1.3 Section 1.4). On merge we reinforce significance by +0.05 (capped
at 1.0) so repeated mentions of the same situation bubble up the
salience retrieval signal over time.

Embedding flow (DevNotes v1.3, Section 1.4)
-------------------------------------------
The dense vector is NEVER stored on the Neo4j node. Instead:

  1. Dedup lookup runs against pgvector via ``_find_similar_node``.
  2. CREATE the Neo4j node with ``embedding_synced = false``.
  3. ``sync_embedding_to_pgvector`` mirrors the vector into pgvector
     and flips the flag to ``true`` on success.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import (
    MERGE_THRESHOLD,
    _new_id,
    _require,
)
from agentic.memory.knowledge_graph.kg_retriever.schemas import ExperienceInput
from agentic.memory.neo4j_client     import get_client
from agentic.memory.cross_store_sync import (
    find_similar_node,
    sync_embedding_to_pgvector,
)

logger = logging.getLogger(__name__)


async def write_experience(inp: ExperienceInput) -> str:
    """
    Write an :Experience node (CBT Situation) with cosine dedup.
    Returns the node id of the merged or newly-created node.
    """
    _require(inp.description,  "description")
    _require(inp.occurred_at,  "occurred_at")
    _require(inp.extracted_at, "extracted_at")
    _require(inp.user_id,      "user_id")
    _require(inp.session_id,   "session_id")

    client = get_client()

    # ── 1. Dedup lookup (pgvector cosine, not in-graph) ────────────────────
    existing = await find_similar_node(
        label="Experience",
        embedding=inp.embedding,
        user_id=inp.user_id,
    )

    if existing and existing["similarity"] >= MERGE_THRESHOLD:
        # Reinforce significance; cap at 1.0. Also append the new
        # message id to the user-anchor edge's provenance list so a
        # later edit/delete on this message can find every fact it
        # contributed to.
        await client.execute_write(
            """
            MATCH (e:Experience {id: $id})
            SET e.significance = CASE
                WHEN e.significance < 0.95 THEN e.significance + 0.05
                ELSE 1.0
            END
            WITH e
            MATCH (u:User {id: $user_id})-[r:EXPERIENCED]->(e)
            WHERE r.t_invalid IS NULL
              AND $message_id IS NOT NULL
              AND NOT $message_id IN coalesce(r.source_messages, [])
            SET r.source_messages = coalesce(r.source_messages, []) + $message_id
            """,
            {
                "id":         existing["id"],
                "user_id":    inp.user_id,
                "message_id": inp.source_message_id,
            },
        )
        logger.debug("Experience merged: %s", existing["id"])
        return existing["id"]

    # ── 2. CREATE path ─────────────────────────────────────────────────────
    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User    {id: $user_id})
        MATCH (s:Session {id: $session_id})
        CREATE (e:Experience {
            id:                $id,
            description:       $description,
            occurred_at:       datetime($occurred_at),
            extracted_at:      datetime($extracted_at),
            valence:           $valence,
            significance:      $significance,
            source_session_id: $session_id,
            embedding_synced:  false,
            active:            true,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:EXPERIENCED {
            t_valid:         datetime($occurred_at),
            t_invalid:       null,
            confidence:      $confidence,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(e)
        CREATE (s)-[:HAD_EXPERIENCE {
            t_valid:         datetime(),
            t_invalid:       null,
            confidence:      $confidence,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(e)
        RETURN e.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "description":       inp.description,
            "occurred_at":       inp.occurred_at,
            "extracted_at":      inp.extracted_at,
            "valence":           inp.valence,
            "significance":      inp.significance,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
            "message_id":        inp.source_message_id,
        },
    )

    # Mirror vector into pgvector and flip embedding_synced on success.
    await sync_embedding_to_pgvector(
        label="Experience",
        node_id=node_id,
        user_id=inp.user_id,
        content=inp.description,
        embedding=inp.embedding,
        importance=inp.significance,
    )

    logger.debug("Experience written: %s", node_id)
    return node_id
