"""
agentic/memory/knowledge_graph/kg_deleter/soft_delete.py

Soft delete: invalidate every fact whose provenance includes a given
message id, without physically removing edges or nodes.

This is the default for "user clicked Delete on a message" because it
preserves the bi-temporal history needed for audit, replay, and
therapist review. The hard-delete equivalent lives in ``hard_delete.py``
and should only be used for the UU PDP / GDPR right-to-erasure flow.

Hexagonal contract
------------------
This module is strictly Neo4j-flavored. It does NOT import from
``agentic.memory.pg_vector`` and does NOT cascade the archive into the
pgvector mirror itself. The cross-store cascade is handled by
``agentic.memory.cross_store_sync.invalidate_message_full`` which calls
into here, reads the ``deactivated_rows`` from the report, and archives
each one through the pg_vector adapter.

Algorithm
---------
Phase 1: prune the message id from ``source_messages`` on every
active edge that lists it. If the list empties as a result, set
``t_invalid = datetime()`` and stamp ``invalidation_reason`` on the
edge. Edges that still have provenance from other messages stay live
because they have independent corroboration.

Phase 2: deactivate orphaned derived nodes. Scoped to the node ids
phase 1 touched so we never sweep up unrelated nodes that happened to
be inactive for a different reason. Setting ``active = false`` is what
makes the node disappear from retrieval and dedup lookups.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client
from agentic.memory.knowledge_graph.kg_deleter._common import DERIVED_LABELS

logger = logging.getLogger(__name__)


async def invalidate_message(
    message_id: str,
    *,
    reason: str = "user_deleted_message",
) -> dict[str, Any]:
    """
    Soft-delete every KG fact whose provenance includes ``message_id``.

    Returns a report dict::

        {
            "edges_touched":     int,
            "nodes_deactivated": int,
            "deactivated_rows":  list[{"id": str, "label": str}],
        }

    ``deactivated_rows`` is what ``cross_store_sync`` consumes to mirror
    the archive into pgvector. Callers that do not care about the
    cross-store cascade can ignore the field.

    ``reason`` is stamped on every invalidated edge as
    ``invalidation_reason`` and on every deactivated node as
    ``deactivation_reason``. Common values:
      "user_deleted_message"  -- default for chat-side deletes
      "user_edited_message"   -- the message was rewritten and the
                                 extractor will re-run
      "moderation_redaction"  -- staff-side redaction
    """
    if not message_id:
        raise ValueError("message_id is required")

    client = get_client()

    # Phase 1: prune source_messages and possibly invalidate the edge.
    # We capture the touched destination node ids so phase 2 can scope
    # its check.
    phase1 = await client.execute_write(
        """
        MATCH (src)-[r]->(dst)
        WHERE $message_id IN coalesce(r.source_messages, [])
          AND r.t_invalid IS NULL
        WITH r, dst,
             [m IN coalesce(r.source_messages, []) WHERE m <> $message_id] AS remaining
        SET r.source_messages = remaining
        WITH r, dst, remaining
        FOREACH (_ IN CASE WHEN size(remaining) = 0 THEN [1] ELSE [] END |
            SET r.t_invalid           = datetime(),
                r.invalidation_reason = $reason
        )
        WITH dst, count(r) AS edges_touched
        RETURN collect(DISTINCT dst.id) AS touched_node_ids,
               sum(edges_touched)       AS edges_touched
        """,
        {"message_id": message_id, "reason": reason},
    )

    touched_node_ids: list[str] = (
        phase1[0]["touched_node_ids"] if phase1 else []
    )
    edges_touched: int = phase1[0]["edges_touched"] if phase1 else 0

    # Phase 2: deactivate orphaned derived nodes. We scope strictly to
    # the nodes touched in phase 1 so we do not sweep up nodes that
    # were already inactive for another reason. We also return the
    # primary label for each row so the cross-store cascade can find
    # the matching pgvector table.
    deactivated_rows: list[dict[str, Any]] = []
    if touched_node_ids:
        deactivated_rows = await client.execute_write(
            """
            MATCH (n)
            WHERE n.id IN $ids
              AND coalesce(n.active, true) = true
              AND any(label IN labels(n) WHERE label IN $derived_labels)
              AND NOT EXISTS {
                  MATCH (n)<-[r]-()
                  WHERE r.t_invalid IS NULL
              }
            SET n.active              = false,
                n.deactivated_at      = datetime(),
                n.deactivation_reason = $reason
            WITH n,
                 [l IN labels(n) WHERE l IN $derived_labels][0] AS label
            RETURN n.id AS id, label
            """,
            {
                "ids":            touched_node_ids,
                "derived_labels": sorted(DERIVED_LABELS),
                "reason":         reason,
            },
        ) or []

    report = {
        "edges_touched":     edges_touched,
        "nodes_deactivated": len(deactivated_rows),
        "deactivated_rows":  deactivated_rows,
    }
    logger.info(
        "invalidate_message(%s) reason=%s -> edges=%d nodes=%d",
        message_id, reason, edges_touched, len(deactivated_rows),
    )
    return report
