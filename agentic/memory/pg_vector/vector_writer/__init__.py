"""
agentic/memory/pg_vector/vector_writer

Write side of the pgvector adapter. Idempotent upserts keyed on
``neo4j_node_id`` so the cross-store sync helper can call the same
function from both the writer happy path and the retry sweep.
"""

from __future__ import annotations

from agentic.memory.pg_vector.vector_writer.upsert import (
    upsert_memory,
    upsert_experience,
    upsert_thought,
    upsert_trigger,
)

__all__ = [
    "upsert_memory",
    "upsert_experience",
    "upsert_thought",
    "upsert_trigger",
]
