"""
agentic/memory/cross_store_sync.py

Orchestration seam between the two memory backends.

This is the only module in the memory layer that imports from BOTH
``agentic.memory.knowledge_graph`` and ``agentic.memory.pg_vector``.
Every other module stays on its own side of the fence (hexagonal
architecture). If you find yourself adding a ``from pg_vector ...``
import to a knowledge_graph module, route it through here instead.

What lives here
---------------
1. ``sync_embedding_to_pgvector``
       Writer-side bridge. Called by ``kg_writer`` after a Neo4j
       CREATE: mirror the dense vector into pgvector then flip
       ``embedding_synced = true`` on the Neo4j node. On any failure
       the flag stays false so the retry sweep reconciles.

2. ``invalidate_message_full``
       Soft-delete bridge. Calls ``kg_deleter.invalidate_message``
       then archives every embeddable row it deactivated. Returns a
       single combined report.

3. ``purge_message_full`` / ``purge_user_full``
       Hard-delete bridges. Run the Neo4j purge then the pgvector
       purge.

4. ``sweep_unsynced`` / ``sweep_until_drained``
       Retry sweep. Reads Neo4j for ``embedding_synced = false``,
       embeds the content, calls ``upsert_<label>``, flips the flag
       on success.

Why this is one file, not a package
-----------------------------------
Every helper here is short, all of them share the same set of
``EMBEDDABLE_LABELS`` / per-label config, and they all coordinate the
same two collaborators. Splitting them across files would multiply
imports without adding clarity. If this file ever grows past ~500
lines or sprouts non-trivial state, split it then.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from agentic.memory.neo4j_client import get_client

# Knowledge graph side (Neo4j is the source of truth for structure)
from agentic.memory.knowledge_graph.kg_modifier import mark_embedding_synced
from agentic.memory.knowledge_graph.kg_deleter import (
    invalidate_message as _kg_invalidate_message,
    purge_message      as _kg_purge_message,
    purge_user         as _kg_purge_user,
)

# pgvector side (Postgres mirrors structure for ANN search)
from agentic.memory.pg_vector import (
    SearchHit,
    embed_text,
    upsert_memory,
    upsert_experience,
    upsert_thought,
    upsert_trigger,
    search_memory,
    search_experience,
    search_thought,
    search_trigger,
    archive_node    as _pg_archive_node,
    purge_node      as _pg_purge_node,
    purge_user      as _pg_purge_user,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deduplication thresholds (DevNotes v1.1, Section 2; v1.3 Section 1.4)
# Re-exported from kg_writer/_common for callers that prefer to import
# them next to the seam they actually use.
# ---------------------------------------------------------------------------

MERGE_THRESHOLD:  float = 0.85
REVIEW_THRESHOLD: float = 0.65


# ---------------------------------------------------------------------------
# Per-label config: how to read each unsynced row out of Neo4j and
# which upsert / searcher to call. Mirrors what the writers know natively.
# ---------------------------------------------------------------------------

_LABEL_CONFIG: dict[str, dict[str, Any]] = {
    "Memory": {
        "content_field":      "summary",
        "importance_field":   "importance",
        "importance_default": 0.5,
        "anchor_edge":        "HAS_MEMORY",
        "upsert":             upsert_memory,
        "search":             search_memory,
    },
    "Experience": {
        "content_field":      "description",
        "importance_field":   "significance",
        "importance_default": 0.5,
        "anchor_edge":        "EXPERIENCED",
        "upsert":             upsert_experience,
        "search":             search_experience,
    },
    "Thought": {
        "content_field":      "content",
        "importance_field":   "believability",
        "importance_default": 0.5,
        "anchor_edge":        "HAS_THOUGHT",
        "upsert":             upsert_thought,
        "search":             search_thought,
    },
    "Trigger": {
        "content_field":      "description",
        "importance_field":   None,           # not on the node; use default
        "importance_default": 0.5,
        "anchor_edge":        "HAS_TRIGGER",
        "upsert":             upsert_trigger,
        "search":             search_trigger,
    },
}


def _upserter_for(label: str):
    return _LABEL_CONFIG[label]["upsert"]


# ===========================================================================
# 1. Writer bridge: mirror a freshly created Neo4j node into pgvector.
# ===========================================================================

async def sync_embedding_to_pgvector(
    *,
    label: str,
    node_id: str,
    user_id: str,
    content: str,
    embedding: list[float] | None,
    importance: float = 0.5,
) -> bool:
    """
    Mirror a freshly-CREATEd Neo4j node into its pgvector table and,
    on success, flip ``embedding_synced`` to true on the Neo4j node.

    Returns True when the pair is in sync, False when the embedding
    was None or the pgvector write failed (the Neo4j node remains
    ``embedding_synced = false`` and the retry sweep reconciles).

    Errors are swallowed after logging so a transient PostgreSQL
    hiccup never blocks the primary KG write path.
    """
    if label not in _LABEL_CONFIG:
        raise ValueError(f"label {label!r} is not embeddable")

    if embedding is None:
        # No vector to mirror; node stays embedding_synced=false on
        # purpose so the retry job knows it has work to do once the
        # embedder comes online.
        return False

    upsert = _upserter_for(label)
    ok = await upsert(
        user_id=user_id,
        neo4j_node_id=node_id,
        content=content,
        embedding=embedding,
        importance=importance,
    )
    if not ok:
        return False

    try:
        await mark_embedding_synced(label, node_id, synced=True)
        return True
    except Exception as exc:
        logger.warning(
            "Failed to flip embedding_synced on %s/%s: %s. "
            "Retry sweep will reconcile.",
            label, node_id, exc,
        )
        return False


# ===========================================================================
# 1b. Cosine dedup probe used by the writers.
# ===========================================================================

async def find_similar_node(
    *,
    label: str,
    embedding: list[float] | None,
    user_id: str,
    min_similarity: float = REVIEW_THRESHOLD,
) -> dict[str, Any] | None:
    """
    Return the single closest active node of ``label`` for ``user_id``
    whose cosine similarity to ``embedding`` is at or above
    ``min_similarity``, or None if nothing qualifies.

    This is the writer-side dedup seam. It used to live inside
    ``kg_writer/_common.py`` but was moved here so the writer package
    no longer imports from pg_vector. Writers call this helper, decide
    merge vs create, and never know which storage answered the probe.

    On any pgvector failure (offline, mis-configured, embedding None)
    the function returns None and the caller falls through to a fresh
    CREATE. The 0.85 / 0.65 thresholds are unaffected; only the storage
    backing them has moved.
    """
    if embedding is None:
        return None

    cfg = _LABEL_CONFIG.get(label)
    if cfg is None:
        return None

    searcher = cfg["search"]
    hits: list[SearchHit] = await searcher(
        user_id, embedding, top_k=1, min_similarity=min_similarity,
    )
    if not hits:
        return None

    top = hits[0]
    return {
        "id":          top.neo4j_node_id,
        "description": top.content,
        "similarity":  top.similarity,
    }


# ===========================================================================
# 2. Soft delete bridge.
# ===========================================================================

async def invalidate_message_full(
    message_id: str,
    *,
    reason: str = "user_deleted_message",
) -> dict[str, int]:
    """
    Run ``kg_deleter.invalidate_message`` then archive every embeddable
    row that the deleter deactivated. Returns the combined report::

        {
            "edges_touched":     int,
            "nodes_deactivated": int,
            "pgvector_archived": int,
        }
    """
    kg_report = await _kg_invalidate_message(message_id, reason=reason)

    archived = 0
    for row in kg_report.get("deactivated_rows", []):
        label   = row.get("label")
        node_id = row.get("id")
        if not label or not node_id or label not in _LABEL_CONFIG:
            continue
        archived += await _pg_archive_node(label, node_id)

    return {
        "edges_touched":     kg_report.get("edges_touched", 0),
        "nodes_deactivated": kg_report.get("nodes_deactivated", 0),
        "pgvector_archived": archived,
    }


# ===========================================================================
# 3. Hard delete bridges.
# ===========================================================================

async def purge_message_full(message_id: str) -> dict[str, int]:
    """
    Run ``kg_deleter.purge_message`` then purge every embeddable row
    it physically deleted from Neo4j. Returns the combined report.
    """
    kg_report = await _kg_purge_message(message_id)

    purged = 0
    for row in kg_report.get("deleted_rows", []):
        label   = row.get("label")
        node_id = row.get("id")
        if not label or not node_id or label not in _LABEL_CONFIG:
            continue
        purged += await _pg_purge_node(label, node_id)

    return {
        "edges_with_pruned_provenance":
            kg_report.get("edges_with_pruned_provenance", 0),
        "nodes_deleted":         kg_report.get("nodes_deleted", 0),
        "pgvector_rows_deleted": purged,
    }


async def purge_user_full(user_id: str) -> dict[str, Any]:
    """
    Run ``kg_deleter.purge_user`` then drop every pgvector row tied
    to the user across all four mirror tables. Returns the combined
    report.
    """
    kg_report = await _kg_purge_user(user_id)
    pg_deleted = await _pg_purge_user(user_id)
    return {
        "nodes_deleted":         kg_report.get("nodes_deleted", 0),
        "sessions_deleted":      kg_report.get("sessions_deleted", 0),
        "user_deleted":          kg_report.get("user_deleted", 0),
        "pgvector_rows_deleted": sum(pg_deleted.values()),
        "pgvector_per_label":    pg_deleted,
    }


# ===========================================================================
# 4. Retry sweep.
# ===========================================================================

async def _read_unsynced_batch(
    label: str,
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    """
    Return up to ``batch_size`` active, unsynced rows of ``label``.

    Reads only the fields the upsert needs. ``user_id`` comes from the
    anchor edge because the user is not stored as a property on the
    derived node. Rows with no live anchor edge are skipped: they are
    orphans and the soft-delete pass should mark them inactive.
    """
    cfg            = _LABEL_CONFIG[label]
    content_fld    = cfg["content_field"]
    importance_fld = cfg["importance_field"]
    anchor_edge    = cfg["anchor_edge"]

    importance_expr = (
        f"coalesce(n.{importance_fld}, $importance_default)"
        if importance_fld
        else "$importance_default"
    )

    cypher = f"""
        MATCH (u:User)-[r:{anchor_edge}]->(n:{label})
        WHERE n.active           = true
          AND n.embedding_synced = false
          AND r.t_invalid IS NULL
        RETURN n.id              AS id,
               u.id              AS user_id,
               n.{content_fld}   AS content,
               {importance_expr} AS importance
        ORDER BY coalesce(n.created_at, n.timestamp, n.first_seen) ASC
        LIMIT $batch_size
    """

    return await get_client().execute_read(
        cypher,
        {
            "batch_size":         int(batch_size),
            "importance_default": float(cfg["importance_default"]),
        },
    )


async def _reconcile_row(label: str, row: dict[str, Any]) -> bool:
    """Embed, upsert, flip the flag. Returns True iff the row is in sync."""
    cfg     = _LABEL_CONFIG[label]
    upsert  = cfg["upsert"]

    node_id    = row.get("id")
    user_id    = row.get("user_id")
    content    = row.get("content")
    importance = row.get("importance", cfg["importance_default"])

    if not node_id or not user_id or not content:
        logger.warning(
            "Skipping %s row with missing required field(s): "
            "id=%r user_id=%r content_present=%s",
            label, node_id, user_id, bool(content),
        )
        return False

    try:
        embedding = await embed_text(content)
    except Exception as exc:
        logger.warning(
            "Embedder failed for %s/%s: %s. Will retry next sweep.",
            label, node_id, exc,
        )
        return False

    ok = await upsert(
        user_id=user_id,
        neo4j_node_id=node_id,
        content=content,
        embedding=embedding,
        importance=float(importance),
    )
    if not ok:
        return False

    try:
        await mark_embedding_synced(label, node_id, synced=True)
        return True
    except Exception as exc:
        logger.warning(
            "pgvector upsert ok but flag flip failed for %s/%s: %s. "
            "Next sweep will retry; upsert is idempotent.",
            label, node_id, exc,
        )
        return False


async def sweep_unsynced(
    *,
    batch_size: int = 100,
    label_filter: Iterable[str] | None = None,
) -> dict[str, dict[str, int]]:
    """
    Reconcile up to ``batch_size`` unsynced rows per embeddable label.
    Returns a dict keyed by label with ``scanned`` / ``synced`` /
    ``failed`` counts. Failed = scanned - synced.
    """
    if label_filter is None:
        labels = sorted(_LABEL_CONFIG.keys())
    else:
        labels = sorted(set(label_filter) & set(_LABEL_CONFIG.keys()))

    report: dict[str, dict[str, int]] = {
        label: {"scanned": 0, "synced": 0, "failed": 0}
        for label in labels
    }

    for label in labels:
        try:
            batch = await _read_unsynced_batch(label, batch_size=batch_size)
        except Exception as exc:
            logger.warning(
                "Could not read unsynced batch for %s: %s. "
                "Skipping this label for the current sweep.",
                label, exc,
            )
            continue

        report[label]["scanned"] = len(batch)
        for row in batch:
            if await _reconcile_row(label, row):
                report[label]["synced"] += 1
            else:
                report[label]["failed"] += 1

        if batch:
            logger.info(
                "retry sweep %s: scanned=%d synced=%d failed=%d",
                label,
                report[label]["scanned"],
                report[label]["synced"],
                report[label]["failed"],
            )

    return report


async def sweep_until_drained(
    *,
    batch_size: int = 100,
    max_passes: int = 10,
    label_filter: Iterable[str] | None = None,
) -> dict[str, dict[str, int]]:
    """
    Repeatedly call ``sweep_unsynced`` until every label reports
    ``scanned == 0`` or ``max_passes`` is hit. Useful for backfills
    and tests. Returns the cumulative tally across passes.
    """
    cumulative: dict[str, dict[str, int]] = {}
    for _ in range(max(1, int(max_passes))):
        pass_report = await sweep_unsynced(
            batch_size=batch_size, label_filter=label_filter,
        )

        for label, counts in pass_report.items():
            bucket = cumulative.setdefault(
                label, {"scanned": 0, "synced": 0, "failed": 0},
            )
            for key in ("scanned", "synced", "failed"):
                bucket[key] += counts[key]

        if all(c["scanned"] == 0 for c in pass_report.values()):
            break

    return cumulative


__all__ = [
    # Dedup thresholds (re-exported for writer convenience)
    "MERGE_THRESHOLD",
    "REVIEW_THRESHOLD",
    # Writer seams
    "sync_embedding_to_pgvector",
    "find_similar_node",
    # Lifecycle bridges
    "invalidate_message_full",
    "purge_message_full",
    "purge_user_full",
    # Retry sweep
    "sweep_unsynced",
    "sweep_until_drained",
]
