"""
agentic/memory/kg_retriever

Read-only access to the knowledge graph.

This package owns:

    schemas.py        -- input dataclasses (shared with kg_writer)
    relationships.py  -- relationship builders (shared with kg_writer)
    node_readers.py   -- per-label point-reads (read_emotion, ...)
    signals.py        -- the three retrieval signals: recency, semantic,
                         salience, plus active emotions / distortions /
                         triggers used by context_builder
    provenance.py     -- "which facts came from message X?" lookups
    _common.py        -- read-side helpers shared across the modules

Reads are always scoped to ``t_invalid IS NULL`` so soft-deleted edges
do not surface, and they always honour ``active = true`` on derived
nodes so the deleter's deactivation flag is respected.

Import rule: callers should import from this top-level package only.
The submodule layout is an implementation detail.
"""

from __future__ import annotations

# ── shared dataclasses ──────────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.schemas import (
    BehaviorInput,
    EmotionInput,
    ExperienceInput,
    MemoryInput,
    PersonInput,
    ThoughtInput,
    TriggerInput,
)

# ── relationship builders ───────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.relationships import (
    link_emotion_to_thought,
    link_experience_to_emotion,
    link_experience_to_trigger,
    link_thought_emotion_association,
    link_to_behavior,
    link_experience_to_person,
    link_session_to_memory,
    link_to_topic,
    link_user_recurring_theme,
    invalidate_edge,
)

# ── per-node readers ────────────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.node_readers import (
    read_emotion,
    read_thought,
    read_trigger,
    read_behavior,
    read_experience,
    read_person,
    read_memory,
    list_active_thoughts_by_distortion,
    list_active_triggers,
)

# ── retrieval signals ───────────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.signals import (
    fetch_recency,
    fetch_semantic_memories,
    fetch_salient_memories,
    fetch_active_emotions,
    fetch_active_distortions,
    fetch_recurring_triggers,
    fetch_recurring_themes,
)

# ── provenance ──────────────────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.provenance import (
    facts_for_message,
    nodes_for_message,
)


__all__ = [
    # schemas
    "BehaviorInput",
    "EmotionInput",
    "ExperienceInput",
    "MemoryInput",
    "PersonInput",
    "ThoughtInput",
    "TriggerInput",
    # relationships
    "link_emotion_to_thought",
    "link_experience_to_emotion",
    "link_experience_to_trigger",
    "link_thought_emotion_association",
    "link_to_behavior",
    "link_experience_to_person",
    "link_session_to_memory",
    "link_to_topic",
    "link_user_recurring_theme",
    "invalidate_edge",
    # node readers
    "read_emotion",
    "read_thought",
    "read_trigger",
    "read_behavior",
    "read_experience",
    "read_person",
    "read_memory",
    "list_active_thoughts_by_distortion",
    "list_active_triggers",
    # signals
    "fetch_recency",
    "fetch_semantic_memories",
    "fetch_salient_memories",
    "fetch_active_emotions",
    "fetch_active_distortions",
    "fetch_recurring_triggers",
    "fetch_recurring_themes",
    # provenance
    "facts_for_message",
    "nodes_for_message",
]
