"""
agentic/memory/knowledge_graph/kg_deleter/hard_delete.py

Hard delete: physically remove edges and nodes.

These functions are destructive and irreversible. Use ``soft_delete``
unless you have a documented reason (right-to-erasure, content
moderation order, security incident). The bi-temporal trail soft delete
preserves is what the therapist review and replay flows depend on; once
you hard-delete, that audit history is gone.

Two flows live here:

    purge_message(message_id)
        Drop every edge whose ``source_messages`` would empty after
        removing this id, and every derived node that loses its last
        incoming edge as a result. Edges shared with other messages
        only have the message id removed from their list (no delete).

    purge_user(user_id)
        Drop every node and edge tied to a single user. Sessions, all
        seven derived labels, the Person nodes that name them as
        owner, and finally the User node itself. Topic catalog stays
        untouched (shared across users, owned by the Go service per
        ADR 002).

Hexagonal contract
------------------
This module is strictly Neo4j-flavored. It does NOT import from
``agentic.memory.pg_vector`` and does NOT cascade the purge into the
pgvector mirror itself. The cross-store cascade lives in
``agentic.memory.cross_store_sync.purge_message_full`` /
``purge_user_full`` which call into here, read ``deleted_rows`` from
the report, and route the pgvector hard delete through the adapter.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client
from agentic.memory.knowledge_graph.kg_deleter._common import DERIVED_LABELS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-message hard delete
# ---------------------------------------------------------------------------

async def purge_message(message_id: str) -> dict[str, Any]:
    """
    Hard-delete every KG fact whose provenance includes ``message_id``.

    Returns::

        {
            "edges_with_pruned_provenance": int,
            "nodes_deleted":                int,
            "deleted_rows": list[{"id": str, "label": str}],
        }

    ``deleted_rows`` is what ``cross_store_sync`` consumes to mirror
    the hard delete into pgvector. Callers that do not care about the
    cross-store cascade can ignore the field.
    """
    if not message_id:
        raise ValueError("message_id is required")

    client = get_client()

    # Step 1: collect destination node ids before we delete edges, so
    # step 3 can decide which nodes are now orphaned.
    candidates = await client.execute_read(
        """
        MATCH ()-[r]->(dst)
        WHERE $message_id IN coalesce(r.source_messages, [])
        RETURN DISTINCT dst.id AS id
        """,
        {"message_id": message_id},
    )
    candidate_ids = [row["id"] for row in candidates]

    # Step 2: delete every edge whose source_messages list, after
    # removing this message id, would be empty. Edges shared with
    # other messages only have the message id removed from their list.
    edge_report = await client.execute_write(
        """
        MATCH (src)-[r]->(dst)
        WHERE $message_id IN coalesce(r.source_messages, [])
        WITH r,
             [m IN coalesce(r.source_messages, []) WHERE m <> $message_id] AS remaining
        FOREACH (_ IN CASE WHEN size(remaining) = 0 THEN [1] ELSE [] END |
            DELETE r
        )
        WITH r, remaining
        WHERE r IS NOT NULL
        SET r.source_messages = remaining
        RETURN count(r) AS edges_kept_with_pruned_provenance
        """,
        {"message_id": message_id},
    )
    edges_kept = (
        edge_report[0]["edges_kept_with_pruned_provenance"]
        if edge_report else 0
    )

    # Step 3: collect (id, label) for every node about to be deleted so
    # the cross-store cascade can target the right pgvector mirror, then
    # DETACH DELETE every previously-touched derived node that has zero
    # remaining incoming edges of any kind.
    deleted_rows: list[dict[str, Any]] = []
    if candidate_ids:
        deleted_rows = await client.execute_write(
            """
            MATCH (n)
            WHERE n.id IN $ids
              AND any(label IN labels(n) WHERE label IN $derived_labels)
              AND NOT EXISTS { MATCH (n)<-[]-() }
            WITH n,
                 [l IN labels(n) WHERE l IN $derived_labels][0] AS label,
                 n.id AS id
            DETACH DELETE n
            RETURN id, label
            """,
            {
                "ids":            candidate_ids,
                "derived_labels": sorted(DERIVED_LABELS),
            },
        ) or []

    report = {
        "edges_with_pruned_provenance": edges_kept,
        "nodes_deleted":                len(deleted_rows),
        "deleted_rows":                 deleted_rows,
    }
    logger.info(
        "purge_message(%s) -> edges_kept=%d nodes_deleted=%d",
        message_id, edges_kept, len(deleted_rows),
    )
    return report


# ---------------------------------------------------------------------------
# Right-to-erasure: full account wipe
# ---------------------------------------------------------------------------

async def purge_user(user_id: str) -> dict[str, int]:
    """
    Hard-delete every node owned by ``user_id`` and the User node
    itself. GDPR Article 17 / UU PDP path: destructive, irreversible,
    intended for the rare case where the user closes their account and
    asks for a full data wipe.

    What it covers in Neo4j:
      * All derived nodes reachable from the User via any edge type.
      * Person nodes scoped to ``owner_user_id = user_id``.
      * Every Session node owned by the User and every node reachable
        from those Sessions.
      * The User node itself.

    Topic nodes are NOT removed because Topic is a shared catalog
    owned by the Go service. Only the User-scoped edges into Topic
    get removed via DETACH DELETE.

    The pgvector wipe is handled by ``cross_store_sync.purge_user_full``;
    this function is the Neo4j half only.
    """
    if not user_id:
        raise ValueError("user_id is required")

    client = get_client()

    report = await client.execute_write(
        """
        // Sessions owned by the user
        OPTIONAL MATCH (u:User {id: $user_id})-[:HAD_SESSION]->(s:Session)
        // Derived nodes owned by the user (any of the seven labels)
        OPTIONAL MATCH (u)-[]-(n)
        WHERE any(label IN labels(n) WHERE label IN $derived_labels)
        // Person nodes scoped to this owner
        OPTIONAL MATCH (p:Person {owner_user_id: $user_id})

        WITH u,
             collect(DISTINCT s) AS sessions,
             collect(DISTINCT n) AS derived_nodes,
             collect(DISTINCT p) AS persons

        // Derived nodes hanging off owned sessions (e.g. Memory linked
        // only via Session, not directly via User)
        UNWIND sessions AS sess
        OPTIONAL MATCH (sess)-[]-(m)
        WHERE any(label IN labels(m) WHERE label IN $derived_labels)

        WITH u, sessions, derived_nodes, persons,
             collect(DISTINCT m) AS session_derived

        WITH u,
             sessions,
             [x IN derived_nodes + persons + session_derived WHERE x IS NOT NULL] AS to_delete

        // Tally before deleting so we can return counts
        WITH u, sessions, to_delete,
             size(to_delete) AS derived_count,
             size(sessions)  AS session_count

        FOREACH (n IN to_delete | DETACH DELETE n)
        FOREACH (s IN sessions  | DETACH DELETE s)
        DETACH DELETE u

        RETURN derived_count AS nodes_deleted,
               session_count AS sessions_deleted
        """,
        {
            "user_id":        user_id,
            "derived_labels": sorted(DERIVED_LABELS),
        },
    )

    summary = (
        {
            "nodes_deleted":    report[0]["nodes_deleted"],
            "sessions_deleted": report[0]["sessions_deleted"],
            "user_deleted":     1,
        }
        if report else
        {
            "nodes_deleted":    0,
            "sessions_deleted": 0,
            "user_deleted":     0,
        }
    )
    logger.warning(
        "purge_user(%s) executed (Neo4j half of right-to-erasure) -> %s",
        user_id, summary,
    )
    return summary
