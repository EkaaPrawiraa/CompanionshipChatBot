"""
agentic/memory/knowledge_graph/kg_writer/_common.py

Shared helpers for the kg_writer package. Internal module (leading
underscore): importers outside this package should go through the
writer functions in the per-node modules, which call into these
helpers.

Hexagonal contract
------------------
After the v1.3 split this module is strictly Neo4j-flavored. It does
NOT import from ``agentic.memory.pg_vector``. The cross-store seams
(cosine dedup probe, embedding mirror, sync sweep) live in
``agentic.memory.cross_store_sync`` and the per-node writers import
those helpers from there. If you find yourself adding a
``from agentic.memory.pg_vector ...`` line here, route it through
cross_store_sync instead.

Contents:
  * Deduplication thresholds (DevNotes v1.1, Section 2;
    confirmed in DevNotes v1.3, Section 2.4).
  * Timestamp and id generators.
  * Application-layer null check (replaces the Enterprise-only
    IS NOT NULL property-existence constraints).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


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


__all__ = [
    "MERGE_THRESHOLD",
    "REVIEW_THRESHOLD",
    "_now_iso",
    "_new_id",
    "_require",
]
