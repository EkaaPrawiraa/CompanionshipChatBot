"""
agentic/memory/vector_search.py

Back-compat shim. Vector search now lives in the modular
``agentic.memory.pg_vector`` package (DevNotes v1.3, Section 1.4;
hexagonal split formalized in v1.3 Section 1.5). This module simply
re-exports the most commonly used names so older import sites can
continue to work without churn.

For new code, import directly from ``agentic.memory.pg_vector``.
"""

from __future__ import annotations

from agentic.memory.pg_vector import (  # noqa: F401  (re-export)
    EMBED_DIM,
    SearchHit,
    archive_node,
    embed_text,
    purge_node,
    purge_user,
    search_experience,
    search_memory,
    search_thought,
    search_trigger,
    upsert_experience,
    upsert_memory,
    upsert_thought,
    upsert_trigger,
)

__all__ = [
    "EMBED_DIM",
    "SearchHit",
    "embed_text",
    "search_memory",
    "search_experience",
    "search_thought",
    "search_trigger",
    "upsert_memory",
    "upsert_experience",
    "upsert_thought",
    "upsert_trigger",
    "archive_node",
    "purge_node",
    "purge_user",
]
