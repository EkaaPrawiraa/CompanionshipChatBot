"""
agentic/memory/kg_modifier/_common.py

Shared allow-lists for the modifier package.

Two pieces of data live here:

    DERIVED_LABELS
        Closed allow-list of derived (AI-coupled) node labels we are
        willing to patch. Mirrors the same constant used by
        ``kg_deleter`` and ``kg_retriever``. User and Session live
        outside this set because their lifecycle is owned by the Go
        service (ADR 002).

    UPDATABLE_PROPERTIES
        Per-label allow-list of properties we are willing to overwrite.
        Anything not in this map raises ValueError to keep callers
        from accidentally rewriting structural properties (id,
        embedding, active, t_valid, etc.).

If a new label or property is added to the schema, update this file
first; the writer/reader changes can come after.
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


#
# ``embedding_synced`` (DevNotes v1.3, Section 1.4) is patchable on every
# embeddable label so the writers and the retry job can flip it from
# false to true once the matching pgvector row has been written. It is
# the only flag that is allowed to be set programmatically without LLM
# review.
#
UPDATABLE_PROPERTIES: dict[str, frozenset[str]] = {
    "Experience": frozenset({
        "description", "valence", "significance", "sensitivity_level",
        "embedding_synced",
    }),
    "Emotion": frozenset({
        "label", "intensity", "valence", "arousal", "dominance",
        "source_text", "sensitivity_level",
    }),
    "Thought": frozenset({
        "content", "thought_type", "distortion", "believability",
        "challenged", "sensitivity_level",
        "embedding_synced",
    }),
    "Trigger": frozenset({
        "category", "description", "aliases", "sensitivity_level",
        "embedding_synced",
    }),
    "Behavior": frozenset({
        "description", "category", "adaptive", "sensitivity_level",
    }),
    "Person": frozenset({
        "name", "role", "sentiment", "sensitivity_level",
    }),
    "Memory": frozenset({
        "summary", "importance", "sensitivity_level",
        "embedding_synced",
    }),
}


def validate_label(label: str) -> str:
    """Raise unless ``label`` is in the modifier allow-list."""
    if label not in DERIVED_LABELS:
        raise ValueError(
            f"label {label!r} not in modifier allow-list {sorted(DERIVED_LABELS)}"
        )
    return label


def validate_updates(label: str, updates: dict) -> None:
    """
    Raise unless every key in ``updates`` is patchable on ``label``.

    Empty ``updates`` also raises -- a no-op call is almost always a
    bug somewhere upstream.
    """
    if not updates:
        raise ValueError("updates dict cannot be empty")
    allowed = UPDATABLE_PROPERTIES[label]
    illegal = [k for k in updates if k not in allowed]
    if illegal:
        raise ValueError(
            f"properties {illegal} are not in the updatable allow-list "
            f"for {label}: {sorted(allowed)}"
        )
