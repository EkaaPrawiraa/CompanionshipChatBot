"""
agentic/memory/kg_modifier/per_node.py

Per-label wrappers around ``update_node_property``.

These exist so the writer / chat-side code can call a typed function
(``update_emotion(emotion_id, intensity=0.4)``) instead of passing a
free-text label. Each wrapper just narrows the label argument to a
single value and forwards everything else.

Implementation notes:
  * The keyword-only signatures are mechanical: every key listed in
    ``UPDATABLE_PROPERTIES[<Label>]`` becomes an optional kwarg.
  * Passing nothing is an error (caught by ``validate_updates``).
  * None values ARE allowed and DO get written (so the caller can,
    for example, clear a distortion when the user reframes a thought).
"""

from __future__ import annotations

from typing import Any

from agentic.memory.knowledge_graph.kg_modifier.update_node import update_node_property


# ---------------------------------------------------------------------------
# Helper: collapse kwargs into the dict that update_node_property expects.
# Only kwargs the caller actually passed are forwarded; sentinel ``...``
# means "left default, do not include in the update".
# ---------------------------------------------------------------------------

_NOT_GIVEN: Any = object()


def _collect(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not _NOT_GIVEN}


# ---------------------------------------------------------------------------
# Per-label wrappers
# ---------------------------------------------------------------------------

async def update_emotion(
    emotion_id: str,
    *,
    label:             Any = _NOT_GIVEN,
    intensity:         Any = _NOT_GIVEN,
    valence:           Any = _NOT_GIVEN,
    arousal:           Any = _NOT_GIVEN,
    dominance:         Any = _NOT_GIVEN,
    source_text:       Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on an :Emotion node."""
    return await update_node_property(
        "Emotion",
        emotion_id,
        _collect(
            label=label,
            intensity=intensity,
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            source_text=source_text,
            sensitivity_level=sensitivity_level,
        ),
    )


async def update_thought(
    thought_id: str,
    *,
    content:           Any = _NOT_GIVEN,
    thought_type:      Any = _NOT_GIVEN,
    distortion:        Any = _NOT_GIVEN,
    believability:     Any = _NOT_GIVEN,
    challenged:        Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
    embedding_synced:  Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on a :Thought node."""
    return await update_node_property(
        "Thought",
        thought_id,
        _collect(
            content=content,
            thought_type=thought_type,
            distortion=distortion,
            believability=believability,
            challenged=challenged,
            sensitivity_level=sensitivity_level,
            embedding_synced=embedding_synced,
        ),
    )


async def update_trigger(
    trigger_id: str,
    *,
    category:          Any = _NOT_GIVEN,
    description:       Any = _NOT_GIVEN,
    aliases:           Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
    embedding_synced:  Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on a :Trigger node."""
    return await update_node_property(
        "Trigger",
        trigger_id,
        _collect(
            category=category,
            description=description,
            aliases=aliases,
            sensitivity_level=sensitivity_level,
            embedding_synced=embedding_synced,
        ),
    )


async def update_behavior(
    behavior_id: str,
    *,
    description:       Any = _NOT_GIVEN,
    category:          Any = _NOT_GIVEN,
    adaptive:          Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on a :Behavior node."""
    return await update_node_property(
        "Behavior",
        behavior_id,
        _collect(
            description=description,
            category=category,
            adaptive=adaptive,
            sensitivity_level=sensitivity_level,
        ),
    )


async def update_experience(
    experience_id: str,
    *,
    description:       Any = _NOT_GIVEN,
    valence:           Any = _NOT_GIVEN,
    significance:      Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
    embedding_synced:  Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on an :Experience node."""
    return await update_node_property(
        "Experience",
        experience_id,
        _collect(
            description=description,
            valence=valence,
            significance=significance,
            sensitivity_level=sensitivity_level,
            embedding_synced=embedding_synced,
        ),
    )


async def update_person(
    person_id: str,
    *,
    name:              Any = _NOT_GIVEN,
    role:              Any = _NOT_GIVEN,
    sentiment:         Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on a :Person node."""
    return await update_node_property(
        "Person",
        person_id,
        _collect(
            name=name,
            role=role,
            sentiment=sentiment,
            sensitivity_level=sensitivity_level,
        ),
    )


async def update_memory(
    memory_id: str,
    *,
    summary:           Any = _NOT_GIVEN,
    importance:        Any = _NOT_GIVEN,
    sensitivity_level: Any = _NOT_GIVEN,
    embedding_synced:  Any = _NOT_GIVEN,
) -> int:
    """Patch one or more properties on a :Memory node."""
    return await update_node_property(
        "Memory",
        memory_id,
        _collect(
            summary=summary,
            importance=importance,
            sensitivity_level=sensitivity_level,
            embedding_synced=embedding_synced,
        ),
    )


async def mark_embedding_synced(
    label: str,
    node_id: str,
    *,
    synced: bool = True,
) -> int:
    """
    Generic flip of ``embedding_synced`` for any embeddable label
    (Memory / Experience / Thought / Trigger). Used by the writers
    immediately after the pgvector upsert succeeds, and by the retry
    job once a stuck node finally syncs.
    """
    return await update_node_property(
        label, node_id, {"embedding_synced": bool(synced)},
    )
