"""
agentic/memory/kg_modifier

Modify the properties of an existing derived node without altering
its structural relationships.

Two ways in:

    update_node_property(label, node_id, updates)
        Generic, allow-listed surgical patch. Use when the caller
        already knows the label.

    update_emotion / update_thought / update_trigger / update_behavior /
    update_experience / update_person / update_memory
        Per-label wrappers around update_node_property. They exist so
        the writers can call a typed function instead of passing a
        bare label string.

    mark_embedding_synced(label, node_id, synced=True)
        Convenience helper for the cross-store sync flow (DevNotes
        v1.3, Section 1.4): writers and the retry job call it after
        the matching pgvector row has been upserted.

Substantive edits (the user rewrote a message in a way that changes
what was extracted) should go through the
``kg_deleter.invalidate_message`` then re-run-the-writers flow:
that preserves the bi-temporal history. ``update_node_property`` is
only meant for surgical patches such as typo corrections, sentiment
re-scoring after a follow-up message, or sensitivity-level upgrades.
"""

from __future__ import annotations

from agentic.memory.knowledge_graph.kg_modifier.update_node import update_node_property
from agentic.memory.knowledge_graph.kg_modifier.per_node import (
    update_emotion,
    update_thought,
    update_trigger,
    update_behavior,
    update_experience,
    update_person,
    update_memory,
    mark_embedding_synced,
)

__all__ = [
    "update_node_property",
    "update_emotion",
    "update_thought",
    "update_trigger",
    "update_behavior",
    "update_experience",
    "update_person",
    "update_memory",
    "mark_embedding_synced",
]
