"""
agentic/memory/kg_deleter/_common.py

Shared helpers for the deleter package.

* DERIVED_LABELS  -- closed allow-list of derived (AI-coupled) node
                     labels. The deleter never touches User, Session,
                     Assessment, or Topic nodes (those are owned by
                     the Go service per ADR 002). Mirrors the same
                     allow-list used by kg_modifier and kg_retriever.

* validate_label  -- raise unless the label is in the allow-list.
"""

from __future__ import annotations


DERIVED_LABELS: frozenset[str] = frozenset({
    "Experience",
    "Emotion",
    "Thought",
    "Trigger",
    "Behavior",
    "Person",
    "Memory",
})


def validate_label(label: str) -> str:
    """Raise unless ``label`` is in the deleter allow-list."""
    if label not in DERIVED_LABELS:
        raise ValueError(
            f"label {label!r} not in deleter allow-list {sorted(DERIVED_LABELS)}"
        )
    return label
