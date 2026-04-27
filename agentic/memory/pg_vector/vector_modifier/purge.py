"""
agentic/memory/pg_vector/vector_modifier/purge.py

Hard delete helpers. Use only when the caller already holds a Neo4j
delete confirmation: this is the GDPR / UU PDP right-to-erasure path
and is irreversible.

Two operations
--------------
* ``purge_node(label, neo4j_node_id)``
    Remove a single mirror row. Used by ``cross_store_sync`` after
    ``kg_deleter.purge_message`` removes the matching Neo4j node.

* ``purge_user(user_id)``
    Drop every row tied to ``user_id`` across all four mirror tables
    in a single transaction. Mirrors ``kg_deleter.purge_user``.

Graceful degradation: if the pool is unavailable both calls return
``0`` (or zeroed dict) so the caller can continue and rely on a later
reconciliation pass.
"""

from __future__ import annotations

import logging

from agentic.memory.pg_vector._common import (
    EMBEDDABLE_LABELS,
    require_str,
    table_for,
)
from agentic.memory.pg_vector.client import get_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard delete (single node)
# ---------------------------------------------------------------------------

async def purge_node(label: str, neo4j_node_id: str) -> int:
    """
    Remove the row matching ``neo4j_node_id`` from the mirror table.
    Returns the number of rows deleted.
    """
    require_str(neo4j_node_id, "neo4j_node_id")

    pool = await get_pool()
    if pool is None:
        return 0

    table = table_for(label)
    sql   = f"DELETE FROM {table} WHERE neo4j_node_id = $1"
    try:
        async with pool.acquire() as conn:
            tag = await conn.execute(sql, neo4j_node_id)
            return int(tag.rsplit(" ", 1)[-1]) if tag else 0
    except Exception as exc:
        logger.warning(
            "pgvector purge_node failed for %s/%s: %s",
            label, neo4j_node_id, exc,
        )
        return 0


# ---------------------------------------------------------------------------
# Hard delete (full user, every table)
# ---------------------------------------------------------------------------

async def purge_user(user_id: str) -> dict[str, int]:
    """
    Drop every embedding row tied to ``user_id`` across all four
    tables. Mirrors ``kg_deleter.purge_user``.

    Returns a dict mapping label -> rows deleted, even when the pool
    is unavailable (every value is 0 in that case).
    """
    require_str(user_id, "user_id")

    deleted: dict[str, int] = {label: 0 for label in EMBEDDABLE_LABELS}
    pool = await get_pool()
    if pool is None:
        return deleted

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for label in EMBEDDABLE_LABELS:
                    table = table_for(label)
                    tag   = await conn.execute(
                        f"DELETE FROM {table} WHERE user_id = $1::uuid",
                        user_id,
                    )
                    deleted[label] = (
                        int(tag.rsplit(" ", 1)[-1]) if tag else 0
                    )
    except Exception as exc:
        logger.warning("pgvector purge_user failed for %s: %s", user_id, exc)

    return deleted
