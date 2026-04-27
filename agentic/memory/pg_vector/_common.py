"""
agentic/memory/pg_vector/_common.py

Shared validation and label-to-table mapping for the pgvector adapter.
Internal module: callers go through the public entry points in
``vector_writer``, ``vector_retriever``, and ``vector_modifier``.

The four embedding tables defined in DevNotes v1.3 (Section 1.4) and
mirrored in ``infra/postgres/pgvector_init.sql`` share an identical
shape::

    id              UUID PRIMARY KEY
    user_id         UUID NOT NULL
    neo4j_node_id   VARCHAR(64) NOT NULL UNIQUE
    content         TEXT NOT NULL
    embedding       vector(1536) NOT NULL
    importance      FLOAT NOT NULL DEFAULT 0.5
    active          BOOLEAN NOT NULL DEFAULT TRUE
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    last_accessed   TIMESTAMPTZ

Each label gets its own table so HNSW indexes stay tight and ANN
recall does not have to compete across heterogeneous payloads.

Hexagonal note
--------------
This package never imports from ``knowledge_graph``. The label string
is the only Neo4j-flavored thing it knows about, and even that is
just a key in a dict. Cross-store orchestration lives in
``agentic.memory.cross_store_sync``.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Label -> table mapping. Single source of truth.
# ---------------------------------------------------------------------------

LABEL_TO_TABLE: dict[str, str] = {
    "Memory":     "memory_embeddings",
    "Experience": "experience_embeddings",
    "Thought":    "thought_embeddings",
    "Trigger":    "trigger_embeddings",
}

EMBEDDABLE_LABELS: frozenset[str] = frozenset(LABEL_TO_TABLE.keys())


def table_for(label: str) -> str:
    """Resolve a node label to its pgvector mirror table name."""
    if label not in LABEL_TO_TABLE:
        raise ValueError(
            f"label {label!r} is not embeddable. "
            f"Allowed: {sorted(EMBEDDABLE_LABELS)}"
        )
    return LABEL_TO_TABLE[label]


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def require_str(value: str | None, field_name: str) -> str:
    """Application-layer null check."""
    if value is None or not str(value).strip():
        raise ValueError(f"Required field '{field_name}' is None or empty")
    return value


def require_vector(vec: list[float] | None, expected_dim: int) -> list[float]:
    """
    Reject embeddings that do not match the configured dimensionality.
    The HNSW index is dimension-locked, so a wrong-length vector would
    fail the INSERT with a confusing pgvector error message.
    """
    if vec is None:
        raise ValueError("embedding vector is required (got None)")
    if not isinstance(vec, list):
        raise ValueError(
            f"embedding must be list[float], got {type(vec).__name__}"
        )
    if len(vec) != expected_dim:
        raise ValueError(
            f"embedding has length {len(vec)}, expected {expected_dim}"
        )
    return vec


def vector_literal(vec: list[float]) -> str:
    """
    Serialize a Python ``list[float]`` to the textual form pgvector
    expects (``[v1,v2,...]``). asyncpg has no native pgvector codec,
    so we cast on the SQL side via ``$1::vector``.
    """
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
