"""
agentic/memory/kg_writer/_common.py

Shared helpers for the kg_writer package. Internal module (leading
underscore): importers outside this package should go through the writer
functions in the per-node modules, which call into these helpers.

Contents:
  * Deduplication thresholds (DevNotes v1.1, Section 2).
  * Timestamp and id generators.
  * Application-layer null check (replaces Enterprise-only IS NOT NULL
    property existence constraints).
  * Cosine-similarity dedup lookup used by Thought and Experience writers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Deduplication thresholds
# ---------------------------------------------------------------------------

MERGE_THRESHOLD:  float = 0.85   # >= this: merge + update payload
REVIEW_THRESHOLD: float = 0.65   # >= this: flag for LLM merge review
# < REVIEW_THRESHOLD: write a fresh node.


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Fresh UUID4 as a string. Used as the ``id`` property on every node."""
    return str(uuid.uuid4())


def _require(value: Any, field_name: str) -> Any:
    """
    Application-layer null check. Raises before any DB call is issued.

    Replaces the Enterprise-only property-existence (IS NOT NULL) constraint
    (see infra/neo4j/schema/constraints.cypher header note).
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Required field '{field_name}' is None or empty")
    return value


# ---------------------------------------------------------------------------
# Cosine-similarity dedup lookup
# ---------------------------------------------------------------------------

async def _find_similar_node(
    label: str,
    description_field: str,
    embedding: list[float] | None,
    user_id: str,
    client: Any,
) -> dict[str, Any] | None:
    """
    Return the single closest active node of ``label`` for this user whose
    cosine similarity is >= REVIEW_THRESHOLD, or None.

    When ``embedding`` is None (the first-run case before the embedding
    model is wired up) we bail out early so the caller falls through to a
    fresh CREATE instead of a fulltext fallback. A fulltext fallback can be
    added later without changing the call sites.

    The ``label`` and ``description_field`` arguments are interpolated
    directly into the Cypher string. They must be hard-coded constants
    from the caller -- never pass user input here.
    """
    if embedding is None:
        return None

    records = await client.execute_read(
        f"""
        MATCH (u:User {{id: $user_id}})-[*1..2]-(n:{label})
        WHERE n.active = true AND n.embedding IS NOT NULL
        WITH n,
             vector.similarity.cosine(n.embedding, $embedding) AS similarity
        WHERE similarity >= $threshold
        RETURN n.id        AS id,
               n.{description_field} AS description,
               similarity
        ORDER BY similarity DESC
        LIMIT 1
        """,
        {
            "user_id":   user_id,
            "embedding": embedding,
            "threshold": REVIEW_THRESHOLD,
        },
    )
    return records[0] if records else None
