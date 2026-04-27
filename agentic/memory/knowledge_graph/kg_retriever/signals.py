"""
agentic/memory/kg_retriever/signals.py

The retrieval signals consumed by ``context_builder.build_context``.

Three-signal hybrid retrieval (KG_Schema_Design.docx, Section 5):
    Signal 1 -- Recency:   last N session summaries.
    Signal 2 -- Semantic:  cosine top-K Memory nodes vs current query.
    Signal 3 -- Salience:  highest-importance Memory nodes for the user.

Plus three supplementary feeds the chat prompt uses to remind the
agent of the user's current state:
    fetch_active_emotions      -- last 7 days of Emotion nodes
    fetch_active_distortions   -- unchallenged distorted Thought nodes
    fetch_recurring_triggers   -- highest-frequency Trigger nodes

All queries respect ``active = true`` on derived nodes and only
return summaries marked ``sensitivity_level = 'normal'`` (sensitive
memories are filtered out of automated retrieval per the privacy model).
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal 1 -- Recency
# ---------------------------------------------------------------------------

async def fetch_recency(user_id: str, *, top_n: int = 2) -> list[str]:
    """Return the most recent session summaries for the user."""
    rows = await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAD_SESSION]->(s:Session)
        WHERE s.ended_at IS NOT NULL
          AND s.summary  IS NOT NULL
        RETURN s.summary AS summary
        ORDER BY s.started_at DESC
        LIMIT $top_n
        """,
        {"user_id": user_id, "top_n": top_n},
    )
    return [r["summary"] for r in rows]


# ---------------------------------------------------------------------------
# Signal 2 -- Semantic
# ---------------------------------------------------------------------------

async def fetch_semantic_memories(
    user_id: str,
    query_embedding: list[float],
    *,
    top_k: int = 5,
    similarity_floor: float = 0.5,
) -> list[str]:
    """
    Cosine-similarity top-K Memory summaries.

    This is a write because we update ``last_accessed`` and increment
    ``access_count`` on the touched nodes. That keeps the decay job
    aware of which memories the agent actually still uses.
    """
    rows = await get_client().execute_write(
        """
        MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory)
        WHERE m.active = true
          AND m.sensitivity_level = 'normal'
          AND m.embedding IS NOT NULL
        WITH m, vector.similarity.cosine(m.embedding, $embedding) AS similarity
        WHERE similarity > $floor
        SET m.last_accessed = datetime(),
            m.access_count  = coalesce(m.access_count, 0) + 1
        RETURN m.summary AS summary, similarity
        ORDER BY similarity DESC
        LIMIT $top_k
        """,
        {
            "user_id":   user_id,
            "embedding": query_embedding,
            "floor":     similarity_floor,
            "top_k":     top_k,
        },
    )
    return [r["summary"] for r in rows]


# ---------------------------------------------------------------------------
# Signal 3 -- Salience
# ---------------------------------------------------------------------------

async def fetch_salient_memories(
    user_id: str,
    *,
    top_k: int = 5,
    importance_floor: float = 0.5,
) -> list[str]:
    """Top-K Memory summaries whose importance is above the cutoff."""
    rows = await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory)
        WHERE m.active = true
          AND m.sensitivity_level = 'normal'
          AND m.importance > $floor
        RETURN m.summary    AS summary,
               m.importance AS importance
        ORDER BY m.importance DESC
        LIMIT $top_k
        """,
        {
            "user_id": user_id,
            "floor":   importance_floor,
            "top_k":   top_k,
        },
    )
    return [r["summary"] for r in rows]


# ---------------------------------------------------------------------------
# Supplementary feeds
# ---------------------------------------------------------------------------

async def fetch_active_emotions(
    user_id: str, *, lookback_days: int = 7, limit: int = 5,
) -> list[dict[str, Any]]:
    """Recent active emotions within ``lookback_days``."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:FELT]->(em:Emotion)
        WHERE em.active = true
          AND em.timestamp > datetime() - duration({days: $lookback})
        RETURN em.label     AS label,
               em.intensity AS intensity,
               em.valence   AS valence
        ORDER BY em.timestamp DESC
        LIMIT $limit
        """,
        {"user_id": user_id, "lookback": lookback_days, "limit": limit},
    )


async def fetch_active_distortions(
    user_id: str, *, limit: int = 3,
) -> list[dict[str, Any]]:
    """Unchallenged cognitive distortions, newest first."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_THOUGHT]->(th:Thought)
        WHERE th.active = true
          AND th.distortion IS NOT NULL
          AND th.challenged = false
        RETURN th.content       AS content,
               th.distortion    AS distortion,
               th.believability AS believability
        ORDER BY th.timestamp DESC
        LIMIT $limit
        """,
        {"user_id": user_id, "limit": limit},
    )


async def fetch_recurring_triggers(
    user_id: str, *, limit: int = 3,
) -> list[dict[str, Any]]:
    """Highest-frequency active triggers."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_TRIGGER]->(t:Trigger)
        WHERE t.active = true
        RETURN t.category    AS category,
               t.description AS description,
               t.frequency   AS frequency
        ORDER BY t.frequency DESC
        LIMIT $limit
        """,
        {"user_id": user_id, "limit": limit},
    )


async def fetch_recurring_themes(
    user_id: str, *, limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Topics the user keeps coming back to. Backed by the
    HAS_RECURRING_THEME edge that link_user_recurring_theme maintains.
    """
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[r:HAS_RECURRING_THEME]->(top:Topic)
        WHERE r.t_invalid IS NULL
        RETURN top.name             AS topic,
               r.times_reinforced   AS times_reinforced,
               r.last_reinforced    AS last_reinforced
        ORDER BY r.times_reinforced DESC, r.last_reinforced DESC
        LIMIT $limit
        """,
        {"user_id": user_id, "limit": limit},
    )
