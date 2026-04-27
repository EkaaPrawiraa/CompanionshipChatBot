"""
agentic/memory/kg_writer

Knowledge-graph write pipeline.

After the modular refactor, kg_writer owns ONLY the per-node CREATE /
MERGE writers. Schemas, relationship builders, deletion, modification,
and rule-based algorithms live in their own packages:

    agentic.memory.kg_retriever  -- schemas.py + relationships.py
                                    + read paths and signal queries
    agentic.memory.kg_deleter    -- soft / hard delete
    agentic.memory.kg_modifier   -- per-node patches
    agentic.memory.kg_algorithm  -- supersession, decay
    agentic.memory.kg_encryption -- standalone encryption layer

This file re-exports the symbols downstream code is used to importing
from kg_writer (schemas, relationship builders, supersede_thought,
run_memory_decay, lifecycle helpers) so the move is non-breaking.
The submodules themselves are now thin: only the per-node writers and
the shared dedup helpers in ``_common.py`` live here.

Per ADR 002 the Go service (backend/services/memory/internal/repository/
neo4j_repo.go) owns all writes for the four pure-CRUD node types,
User, Session, Assessment, Topic, so this Python package contains no
writers for them.
"""

from __future__ import annotations

# ── Deduplication thresholds ───────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_writer._common import (
    MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
)

# ── Input schemas (now hosted by kg_retriever) ─────────────────────────
from agentic.memory.knowledge_graph.kg_retriever.schemas import (
    BehaviorInput,
    EmotionInput,
    ExperienceInput,
    MemoryInput,
    PersonInput,
    ThoughtInput,
    TriggerInput,
)

# ── Per-node writers ──────────────────────────────────────────────────
from agentic.memory.knowledge_graph.kg_writer.behavior_kg   import write_behavior
from agentic.memory.knowledge_graph.kg_writer.emotion_kg    import write_emotion
from agentic.memory.knowledge_graph.kg_writer.experience_kg import write_experience
from agentic.memory.knowledge_graph.kg_writer.memory_kg     import write_memory
from agentic.memory.knowledge_graph.kg_writer.person_kg     import write_person
from agentic.memory.knowledge_graph.kg_writer.thought_kg    import write_thought
from agentic.memory.knowledge_graph.kg_writer.trigger_kg    import write_trigger

# ── Relationship builders (now hosted by kg_retriever) ─────────────────
from agentic.memory.knowledge_graph.kg_retriever.relationships import (
    # CBT chain
    link_emotion_to_thought,
    link_experience_to_emotion,
    link_experience_to_trigger,
    link_thought_emotion_association,
    link_to_behavior,
    # Contextual
    link_experience_to_person,
    link_session_to_memory,
    link_to_topic,
    link_user_recurring_theme,
    # Bi-temporal maintenance
    invalidate_edge,
)

# ── Algorithmic operations (now hosted by kg_algorithm) ────────────────
from agentic.memory.knowledge_graph.kg_algorithm.supersession import supersede_thought
from agentic.memory.knowledge_graph.kg_algorithm.decay        import run_memory_decay

# ── Lifecycle (now split across kg_deleter / kg_modifier) ──────────────
from agentic.memory.knowledge_graph.kg_deleter.soft_delete  import invalidate_message
from agentic.memory.knowledge_graph.kg_deleter.hard_delete  import purge_message, purge_user
from agentic.memory.knowledge_graph.kg_modifier.update_node import update_node_property


__all__ = [
    # thresholds
    "MERGE_THRESHOLD",
    "REVIEW_THRESHOLD",
    # schemas
    "BehaviorInput",
    "EmotionInput",
    "ExperienceInput",
    "MemoryInput",
    "PersonInput",
    "ThoughtInput",
    "TriggerInput",
    # writers
    "write_behavior",
    "write_emotion",
    "write_experience",
    "write_memory",
    "write_person",
    "write_thought",
    "write_trigger",
    # relationship builders -- CBT chain
    "link_emotion_to_thought",
    "link_experience_to_emotion",
    "link_experience_to_trigger",
    "link_thought_emotion_association",
    "link_to_behavior",
    # relationship builders -- contextual
    "link_experience_to_person",
    "link_session_to_memory",
    "link_to_topic",
    "link_user_recurring_theme",
    # bi-temporal maintenance
    "invalidate_edge",
    # supersession & decay (re-exported from kg_algorithm)
    "supersede_thought",
    "run_memory_decay",
    # lifecycle (re-exported from kg_deleter / kg_modifier)
    "invalidate_message",
    "purge_message",
    "purge_user",
    "update_node_property",
]
