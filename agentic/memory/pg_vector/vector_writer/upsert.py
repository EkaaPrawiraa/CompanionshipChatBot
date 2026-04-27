"""
agentic/memory/pg_vector/vector_writer/upsert.py

Idempotent UPSERTs into the four pgvector mirror tables. Called by
``agentic.memory.cross_store_sync`` immediately after the Neo4j
CREATE succeeds. The Neo4j ``id`` becomes ``neo4j_node_id`` in
pgvector; that column carries the UNIQUE constraint that powers
``ON CONFLICT (neo4j_node_id) DO UPDATE``.

DevNotes v1.3 cross-store flow (see kg_schema.md, Section 9):

    1. Writer CREATEs Neo4j node with embedding_synced = false.
    2. Orchestrator calls upsert_<label> here.
    3. Orchestrator flips embedding_synced = true via kg_modifier.

Failures here are non-fatal. The Neo4j node still exists with
embedding_synced = false; the retry job will pick it up on the next
sweep. We log a warning and return False so the orchestrator knows
not to flip the flag.
"""

from __future__ import annotations

import logging
import uuid

from agentic.memory.pg_vector._common    import (
    require_str,
    require_vector,
    table_for,
    vector_literal,
)
from agentic.memory.pg_vector.client     import get_pool
from agentic.memory.pg_vector.embeddings import EMBED_DIM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic upsert
# ---------------------------------------------------------------------------

async def _upsert(
    label: str,
    *,
    user_id: str,
    neo4j_node_id: str,
    content: str,
    embedding: list[float],
    importance: float,
) -> bool:
    """
    Insert or update a single row in the mirror table for ``label``.
    Returns True on success, False if the database is unavailable.
    """
    require_str(user_id,       "user_id")
    require_str(neo4j_node_id, "neo4j_node_id")
    require_str(content,       "content")
    require_vector(embedding,  EMBED_DIM)

    pool = await get_pool()
    if pool is None:
        logger.debug(
            "pgvector unavailable; skipping upsert for %s/%s",
            label, neo4j_node_id,
        )
        return False

    table = table_for(label)
    sql = f"""
        INSERT INTO {table}
            (id, user_id, neo4j_node_id, content, embedding,
             importance, active, created_at, last_accessed)
        VALUES
            ($1::uuid, $2::uuid, $3, $4, $5::vector,
             $6, TRUE, NOW(), NOW())
        ON CONFLICT (neo4j_node_id) DO UPDATE SET
            content       = EXCLUDED.content,
            embedding     = EXCLUDED.embedding,
            importance    = EXCLUDED.importance,
            active        = TRUE,
            last_accessed = NOW()
    """

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                str(uuid.uuid4()),
                user_id,
                neo4j_node_id,
                content,
                vector_literal(embedding),
                float(importance),
            )
        logger.debug("pgvector upsert ok: %s/%s", label, neo4j_node_id)
        return True
    except Exception as exc:
        logger.warning(
            "pgvector upsert failed for %s/%s: %s. "
            "Node will retry via embedding_synced=false sweep.",
            label, neo4j_node_id, exc,
        )
        return False


# ---------------------------------------------------------------------------
# Per-label thin wrappers
# ---------------------------------------------------------------------------

async def upsert_memory(
    *,
    user_id: str,
    neo4j_node_id: str,
    content: str,
    embedding: list[float],
    importance: float = 0.5,
) -> bool:
    return await _upsert(
        "Memory",
        user_id=user_id, neo4j_node_id=neo4j_node_id,
        content=content, embedding=embedding, importance=importance,
    )


async def upsert_experience(
    *,
    user_id: str,
    neo4j_node_id: str,
    content: str,
    embedding: list[float],
    importance: float = 0.5,
) -> bool:
    return await _upsert(
        "Experience",
        user_id=user_id, neo4j_node_id=neo4j_node_id,
        content=content, embedding=embedding, importance=importance,
    )


async def upsert_thought(
    *,
    user_id: str,
    neo4j_node_id: str,
    content: str,
    embedding: list[float],
    importance: float = 0.5,
) -> bool:
    return await _upsert(
        "Thought",
        user_id=user_id, neo4j_node_id=neo4j_node_id,
        content=content, embedding=embedding, importance=importance,
    )


async def upsert_trigger(
    *,
    user_id: str,
    neo4j_node_id: str,
    content: str,
    embedding: list[float],
    importance: float = 0.5,
) -> bool:
    return await _upsert(
        "Trigger",
        user_id=user_id, neo4j_node_id=neo4j_node_id,
        content=content, embedding=embedding, importance=importance,
    )
