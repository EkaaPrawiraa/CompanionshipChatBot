"""
agentic/memory/kg_retriever/node_readers.py

Per-label point-reads.

Each ``read_<label>`` returns a single dict (or None when the id is
unknown) of the public properties of that node. They never decrypt:
the integration step will compose ``decode_for_property`` on top once
the encryption layer is wired in.

The list-style readers (``list_active_*``) cover the few cases where
context_builder needs more than one row at a time but a full signal
function in ``signals.py`` would be overkill.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client
from agentic.memory.knowledge_graph.kg_retriever._common import validate_label

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic point-read
# ---------------------------------------------------------------------------

async def _read_node(label: str, node_id: str) -> dict[str, Any] | None:
    """Internal: fetch one node by id, scoped by label."""
    label = validate_label(label)
    rows = await get_client().execute_read(
        f"""
        MATCH (n:{label} {{id: $id}})
        RETURN properties(n) AS props
        LIMIT 1
        """,
        {"id": node_id},
    )
    return rows[0]["props"] if rows else None


# ---------------------------------------------------------------------------
# Per-node readers
# ---------------------------------------------------------------------------

async def read_emotion(emotion_id: str) -> dict[str, Any] | None:
    """Return the public properties of an :Emotion node, or None."""
    return await _read_node("Emotion", emotion_id)


async def read_thought(thought_id: str) -> dict[str, Any] | None:
    """Return the public properties of a :Thought node, or None."""
    return await _read_node("Thought", thought_id)


async def read_trigger(trigger_id: str) -> dict[str, Any] | None:
    return await _read_node("Trigger", trigger_id)


async def read_behavior(behavior_id: str) -> dict[str, Any] | None:
    return await _read_node("Behavior", behavior_id)


async def read_experience(experience_id: str) -> dict[str, Any] | None:
    return await _read_node("Experience", experience_id)


async def read_person(person_id: str) -> dict[str, Any] | None:
    return await _read_node("Person", person_id)


async def read_memory(memory_id: str) -> dict[str, Any] | None:
    """Return the public properties of a :Memory node, or None."""
    return await _read_node("Memory", memory_id)


# ---------------------------------------------------------------------------
# Small list-style readers
# ---------------------------------------------------------------------------

async def list_active_thoughts_by_distortion(
    user_id: str,
    distortion: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return up to ``limit`` active, unchallenged Thought nodes for a
    user that match the given distortion type. Newest first.
    """
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_THOUGHT]->(t:Thought)
        WHERE t.active = true
          AND t.challenged = false
          AND t.distortion = $distortion
        RETURN t.id            AS id,
               t.content       AS content,
               t.believability AS believability,
               t.timestamp     AS timestamp
        ORDER BY t.timestamp DESC
        LIMIT $limit
        """,
        {"user_id": user_id, "distortion": distortion, "limit": limit},
    )


async def list_active_triggers(
    user_id: str,
    *,
    category: str | None = None,
    min_frequency: int = 1,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return active Trigger nodes for a user, optionally filtered by
    category. Sorted by frequency descending so the most recurring
    antecedents come first.
    """
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_TRIGGER]->(t:Trigger)
        WHERE t.active = true
          AND t.frequency >= $min_freq
          AND ($category IS NULL OR t.category = $category)
        RETURN t.id          AS id,
               t.category    AS category,
               t.description AS description,
               t.frequency   AS frequency
        ORDER BY t.frequency DESC
        LIMIT $limit
        """,
        {
            "user_id":  user_id,
            "category": category,
            "min_freq": min_frequency,
            "limit":    limit,
        },
    )
