"""
agentic/memory/kg_deleter

Delete-side of the knowledge graph lifecycle.

Two escalation tiers, plus a nuclear option:

    soft_delete.invalidate_message(message_id)
        Per-message soft delete. Removes the message id from
        ``source_messages`` on every active edge. When that empties
        the list, the edge gets ``t_invalid = datetime()`` and an
        ``invalidation_reason`` so it stays in the graph for audit but
        drops out of "currently true" queries. Nodes that lose their
        last live anchor edge are flipped ``active = false``.

    hard_delete.purge_message(message_id)
        Per-message hard delete. Same scoping but actually
        ``DETACH DELETE``s edges and orphan derived nodes. Use for the
        GDPR right-to-erasure flow.

    hard_delete.purge_user(user_id)
        Full-account erasure: drop every node and edge tied to the
        user, drop the User node last. Topic catalog stays intact
        (per ADR 002, owned by Go).

This package was split out of kg_writer/lifecycle.py so the read,
write, modify, and delete concerns each get their own module. Public
names are re-exported here so callers do not have to know which
submodule a function lives in.
"""

from __future__ import annotations

from agentic.memory.knowledge_graph.kg_deleter.soft_delete import invalidate_message
from agentic.memory.knowledge_graph.kg_deleter.hard_delete import purge_message, purge_user
from agentic.memory.knowledge_graph.kg_deleter._common import DERIVED_LABELS

__all__ = [
    "invalidate_message",
    "purge_message",
    "purge_user",
    "DERIVED_LABELS",
]
