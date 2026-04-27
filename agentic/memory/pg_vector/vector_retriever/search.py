"""
agentic/memory/pg_vector/vector_retriever/search.py

Cosine top-k search against the four pgvector mirror tables.

Two consumers
-------------
1. ``context_builder._fetch_semantic`` calls ``search_memory`` to
   build hybrid retrieval signal 2 (DevNotes v1.3, Section 2.2).
2. ``cross_store_sync`` exposes ``search_experience``, ``search_thought``,
   and ``search_trigger`` to the writers for write-time deduplication.
   The 0.85 / 0.65 thresholds in DevNotes v1.3, Section 2.4 are applied
   by the caller; this module just returns the closest active row.

Result shape
------------
Each hit is a ``SearchHit`` dataclass carrying the cross-store key
(``neo4j_node_id``), the content snippet, the importance mirror, and
the cosine similarity in [0.0, 1.0]. ``similarity = 1 - distance``
where ``distance`` is the pgvector cosine distance (``<=>`` operator).

Graceful degradation
--------------------
If the pgvector pool is unavailable every search returns ``[]``.
Callers treat the empty result as "nothing to merge / no near
duplicate" and let recency + salience carry the retrieval pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SearchHit:
    neo4j_node_id: str
    content:       str
    importance:    float
    similarity:    float    # cosine similarity in [0, 1]


# ---------------------------------------------------------------------------
# Generic search
# ---------------------------------------------------------------------------

async def _search(
    label: str,
    *,
    user_id: str,
    embedding: list[float],
    top_k: int,
    min_similarity: float | None = None,
    touch_last_accessed: bool = False,
) -> list[SearchHit]:
    """
    Return the top-k active rows of ``label`` for ``user_id`` ordered
    by cosine similarity descending. Optionally filter on a minimum
    similarity floor.

    When ``touch_last_accessed`` is True, the matched rows have their
    ``last_accessed`` updated. Used by the Memory retrieval path so
    decay calculations reflect actual usage.
    """
    require_str(user_id,  "user_id")
    require_vector(embedding, EMBED_DIM)
    if top_k <= 0:
        raise ValueError(f"top_k must be > 0, got {top_k}")

    pool = await get_pool()
    if pool is None:
        return []

    table = table_for(label)
    vec   = vector_literal(embedding)

    base_sql = f"""
        SELECT neo4j_node_id, content, importance,
               1 - (embedding <=> $1::vector) AS similarity
        FROM   {table}
        WHERE  user_id = $2::uuid
          AND  active  = TRUE
        ORDER  BY embedding <=> $1::vector
        LIMIT  $3
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(base_sql, vec, user_id, top_k)
            hits = [
                SearchHit(
                    neo4j_node_id=r["neo4j_node_id"],
                    content=r["content"],
                    importance=float(r["importance"]),
                    similarity=float(r["similarity"]),
                )
                for r in rows
            ]
            if min_similarity is not None:
                hits = [h for h in hits if h.similarity >= min_similarity]

            if touch_last_accessed and hits:
                ids = [h.neo4j_node_id for h in hits]
                await conn.execute(
                    f"""
                    UPDATE {table}
                       SET last_accessed = NOW()
                     WHERE neo4j_node_id = ANY($1::varchar[])
                    """,
                    ids,
                )
            return hits
    except Exception as exc:
        logger.warning("pgvector search failed for %s: %s", label, exc)
        return []


# ---------------------------------------------------------------------------
# Per-label thin wrappers
# ---------------------------------------------------------------------------

async def search_memory(
    user_id: str,
    embedding: list[float],
    *,
    top_k: int = 5,
    min_similarity: float | None = 0.5,
) -> list[SearchHit]:
    """
    Hybrid retrieval signal 2: top-k Memory rows by cosine similarity.
    Defaults match DevNotes v1.3 Section 2.2 (top-5, threshold 0.5).
    """
    return await _search(
        "Memory",
        user_id=user_id,
        embedding=embedding,
        top_k=top_k,
        min_similarity=min_similarity,
        touch_last_accessed=True,
    )


async def search_experience(
    user_id: str,
    embedding: list[float],
    *,
    top_k: int = 1,
    min_similarity: float | None = None,
) -> list[SearchHit]:
    """Write-time dedup probe for Experience."""
    return await _search(
        "Experience",
        user_id=user_id,
        embedding=embedding,
        top_k=top_k,
        min_similarity=min_similarity,
    )


async def search_thought(
    user_id: str,
    embedding: list[float],
    *,
    top_k: int = 1,
    min_similarity: float | None = None,
) -> list[SearchHit]:
    """Write-time dedup probe for Thought."""
    return await _search(
        "Thought",
        user_id=user_id,
        embedding=embedding,
        top_k=top_k,
        min_similarity=min_similarity,
    )


async def search_trigger(
    user_id: str,
    embedding: list[float],
    *,
    top_k: int = 1,
    min_similarity: float | None = None,
) -> list[SearchHit]:
    """Write-time dedup probe for Trigger (slow path after keyword miss)."""
    return await _search(
        "Trigger",
        user_id=user_id,
        embedding=embedding,
        top_k=top_k,
        min_similarity=min_similarity,
    )
