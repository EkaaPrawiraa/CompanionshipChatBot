"""
agentic/memory/kg_writer/memory_kg.py

Writer for the :Memory node (compressed post-session summary).

Per the canonical KG schema (KG_Schema_Design.md, section 3) a Memory
node hangs off two anchors:

    (:User)   -[:HAS_MEMORY]      -> (:Memory)   -- root user-level link
    (:Session)-[:CONTAINS_MEMORY] -> (:Memory)   -- provenance chain

One Memory is created per Session in session_end.py. It is the primary
semantic retrieval target (hybrid retrieval signal 2) and the source of
importance for the salience retrieval signal.

Embedding flow (DevNotes v1.3, Section 1.4)
-------------------------------------------
The dense vector is NEVER stored on the Neo4j node. Instead:

  1. CREATE the Neo4j node with ``embedding_synced = false``.
  2. Hand the vector to ``pg_vector.upsert_memory`` (via the
     ``cross_store_sync.sync_embedding_to_pgvector`` seam) which
     writes the pgvector row and returns ok / not-ok.
  3. On success the cross-store helper flips ``embedding_synced`` to
     ``true`` via the modifier. On failure (or when the embedding is
     None) the flag stays false and the retry job picks the node up
     next sweep.

The ``sync_embedding_to_pgvector`` helper hides all of this so the
writer only deals with the Cypher CREATE.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import (
    _new_id,
    _require,
)
from agentic.memory.knowledge_graph.kg_retriever.schemas import MemoryInput
from agentic.memory.neo4j_client     import get_client
from agentic.memory.cross_store_sync import sync_embedding_to_pgvector

logger = logging.getLogger(__name__)


async def write_memory(inp: MemoryInput) -> str:
    """
    Write a compressed :Memory node for this user, link it from the
    User via HAS_MEMORY, and link it from the Session via
    CONTAINS_MEMORY for provenance. Mirror the embedding into pgvector.
    Returns the new node id.
    """
    _require(inp.summary,    "summary")
    _require(inp.user_id,    "user_id")
    _require(inp.session_id, "session_id")

    client  = get_client()
    node_id = _new_id()

    await client.execute_write(
        """
        MATCH (u:User    {id: $user_id})
        MATCH (s:Session {id: $session_id})

        CREATE (m:Memory {
            id:                $id,
            summary:           $summary,
            importance:        $importance,
            created_at:        datetime(),
            last_accessed:     datetime(),
            access_count:      0,
            embedding_synced:  false,
            active:            true,
            sensitivity_level: $sensitivity_level
        })

        CREATE (u)-[:HAS_MEMORY {
            t_valid:         datetime(),
            t_invalid:       null,
            confidence:      1.0,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(m)

        CREATE (s)-[:CONTAINS_MEMORY {
            t_valid:         datetime(),
            t_invalid:       null,
            confidence:      1.0,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(m)

        RETURN m.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "summary":           inp.summary,
            "importance":        inp.importance,
            "sensitivity_level": inp.sensitivity_level,
            "message_id":        inp.source_message_id,
        },
    )

    # Mirror the embedding into pgvector and flip embedding_synced on
    # success. Failures are logged but never raised: the retry job
    # reconciles stuck nodes via the embedding_synced=false predicate.
    await sync_embedding_to_pgvector(
        label="Memory",
        node_id=node_id,
        user_id=inp.user_id,
        content=inp.summary,
        embedding=inp.embedding,
        importance=inp.importance,
    )

    logger.info("Memory written: %s (importance=%.2f)", node_id, inp.importance)
    return node_id
