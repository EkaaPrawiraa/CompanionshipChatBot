"""
agentic/memory/pg_vector/vector_modifier

Lifecycle helpers that mutate existing rows: soft archive, hard purge.
The cross-store reconciliation sweep is NOT in this package because it
must read Neo4j to find unsynced rows; that orchestration lives in
``agentic.memory.cross_store_sync``.
"""

from __future__ import annotations

from agentic.memory.pg_vector.vector_modifier.archive import archive_node
from agentic.memory.pg_vector.vector_modifier.purge   import (
    purge_node,
    purge_user,
)

__all__ = [
    "archive_node",
    "purge_node",
    "purge_user",
]
