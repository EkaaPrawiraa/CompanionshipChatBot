"""
agentic/memory/pg_vector/vector_retriever

Read side of the pgvector adapter. Cosine top-k search per embeddable
label, plus the ``SearchHit`` dataclass that callers receive.
"""

from __future__ import annotations

from agentic.memory.pg_vector.vector_retriever.search import (
    SearchHit,
    search_memory,
    search_experience,
    search_thought,
    search_trigger,
)

__all__ = [
    "SearchHit",
    "search_memory",
    "search_experience",
    "search_thought",
    "search_trigger",
]
