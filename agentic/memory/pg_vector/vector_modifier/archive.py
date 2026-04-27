"""
agentic/memory/pg_vector/vector_modifier/archive.py

Soft-archive a single mirror row. Flips ``active = FALSE`` on the
matching ``neo4j_node_id``. Called by ``cross_store_sync`` whenever
Neo4j flips a derived node's ``active`` flag (decay job, manual
archive, soft-delete cascade).

Graceful degradation: if the pool is unavailable the call is a no-op
and returns 0. The next sweep of the retry job will re-attempt the
archival as part of its normal ``embedding_synced = false`` flow once
PostgreSQL is back.
"""

from __future__ import annotations

import logging

from agentic.memory.pg_vector._common import require_str, table_for
from agentic.memory.pg_vector.client  import get_pool

logger = logging.getLogger(__name__)


async def archive_node(label: str, neo4j_node_id: str) -> int:
    """
    Set ``active = FALSE`` on the row matching ``neo4j_node_id``.
    Returns the number of rows updated (0 if not present, 1 on hit).
    """
    require_str(neo4j_node_id, "neo4j_node_id")

    pool = await get_pool()
    if pool is None:
        return 0

    table = table_for(label)
    sql = f"""
        UPDATE {table}
           SET active = FALSE
         WHERE neo4j_node_id = $1
           AND active        = TRUE
    """

    try:
        async with pool.acquire() as conn:
            tag = await conn.execute(sql, neo4j_node_id)
            return int(tag.rsplit(" ", 1)[-1]) if tag else 0
    except Exception as exc:
        logger.warning(
            "pgvector archive_node failed for %s/%s: %s",
            label, neo4j_node_id, exc,
        )
        return 0
