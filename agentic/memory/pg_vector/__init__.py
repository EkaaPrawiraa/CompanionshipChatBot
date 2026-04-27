"""
agentic/memory/pg_vector

PostgreSQL ``pgvector`` adapter for the hybrid retrieval pipeline
(DevNotes v1.3, Section 1.4).

Why this package exists
-----------------------
Neo4j Community Edition does not serve native ANN vector search,
so an in-graph ``embedding`` property cannot back semantic retrieval.
DevNotes v1.3 moves all dense vectors out of Neo4j and into
PostgreSQL ``pgvector`` tables, with an HNSW index per table. The
Neo4j node remains the structural identity; the pgvector row holds
the vector and the content snippet that was embedded. The two halves
are linked by a single key: ``neo4j_node_id``.

Hexagonal split
---------------
This package is the PostgreSQL adapter half of the memory layer. It
exposes only what an ANN-and-relational store can do:

  * upserts keyed on ``neo4j_node_id``
  * cosine top-k search per embeddable label
  * lifecycle: soft archive, hard purge

It does NOT import from ``agentic.memory.knowledge_graph``. The label
string is the only Neo4j-flavored thing it touches, and even that is
just a key in a dict. Cross-store orchestration (write-time mirror,
delete-time archive cascade, retry sweep) lives one layer up in
``agentic.memory.cross_store_sync``.

Subpackages
-----------
* ``client``            asyncpg pool + config
* ``embeddings``        OpenAI / offline-stub embedder
* ``vector_writer``     idempotent upsert per label
* ``vector_retriever``  cosine top-k search + ``SearchHit`` dataclass
* ``vector_modifier``   archive_node, purge_node, purge_user
"""

from __future__ import annotations

from agentic.memory.pg_vector.client     import (
    PgvectorConfig,
    get_pool,
    close_pool,
    is_available,
)
from agentic.memory.pg_vector.embeddings import (
    EMBED_DIM,
    embed_text,
    embed_many,
)
from agentic.memory.pg_vector.vector_writer    import (
    upsert_memory,
    upsert_experience,
    upsert_thought,
    upsert_trigger,
)
from agentic.memory.pg_vector.vector_retriever import (
    SearchHit,
    search_memory,
    search_experience,
    search_thought,
    search_trigger,
)
from agentic.memory.pg_vector.vector_modifier  import (
    archive_node,
    purge_node,
    purge_user,
)

__all__ = [
    # config / lifecycle
    "PgvectorConfig",
    "get_pool",
    "close_pool",
    "is_available",
    # embeddings
    "EMBED_DIM",
    "embed_text",
    "embed_many",
    # writes
    "upsert_memory",
    "upsert_experience",
    "upsert_thought",
    "upsert_trigger",
    # reads
    "SearchHit",
    "search_memory",
    "search_experience",
    "search_thought",
    "search_trigger",
    # lifecycle / archival
    "archive_node",
    "purge_node",
    "purge_user",
]
