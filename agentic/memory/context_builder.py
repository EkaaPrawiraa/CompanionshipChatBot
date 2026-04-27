"""
agentic/memory/context_builder.py

Hybrid retrieval strategy. Called from memory_retrieval.py (LangGraph
node) before every LLM generation.

The retrieval signals layered into one prompt block:

  Signal 1 -- Recency:           last 2 session summaries
  Signal 2 -- Semantic memories: pgvector cosine top-5 Memory nodes
  Signal 3 -- Salience:          Memory.importance > 0.5, ORDER BY DESC, LIMIT 5
  Signal 4 -- Past experiences:  pgvector cosine top-5 Experience nodes
  Signal 5 -- Important people:  top-5 Person nodes by mention_count and
                                 |sentiment|, plus the experiences
                                 attached to each via :INVOLVES_PERSON
  Plus:                          recent emotions, unchallenged distortions,
                                 recurring triggers

Why this layered shape
----------------------
Memory summaries compress whole sessions, so they answer "what was the
overall arc?" but blur individual events. Past experiences are the raw
situation nodes, so they answer "what specifically happened?". People
retrieval is the bridge: when the user mentions someone by name, the
graph traversal pulls the experiences that involved them, which fixes
the asymmetric recall (bot remembers the person but not what they did).

Why pgvector for the cosine signals
-----------------------------------
Neo4j Community Edition does not expose ``db.index.vector.queryNodes``
or ``vector.similarity.cosine`` (DevNotes v1.3, Section 1.4). All vector
math has moved to the pgvector mirror tables. This module calls
``pg_vector.search_memory`` and ``pg_vector.search_experience`` and uses
the returned ``neo4j_node_id`` to refresh per-node Neo4j state
(``last_accessed``, ``access_count``) which still drives the decay job.

Hexagonal note
--------------
``context_builder`` is a memory-layer orchestrator and is allowed to
import from both halves (``knowledge_graph`` for the Neo4j touch and
``pg_vector`` for the cosine probe). It sits one layer above the two
adapters, alongside ``cross_store_sync``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agentic.memory.pg_vector   import SearchHit, search_experience, search_memory
from agentic.memory.neo4j_client import get_client

logger = logging.getLogger(__name__)

SEMANTIC_TOP_K:        int   = 5
SEMANTIC_FLOOR:        float = 0.5    # cosine similarity floor for signal 2
SALIENCE_TOP_K:        int   = 5
SALIENCE_CUTOFF:       float = 0.5
EXPERIENCE_TOP_K:      int   = 5      # cosine top-k for past experiences (signal 4)
EXPERIENCE_FLOOR:      float = 0.5
PEOPLE_TOP_K:          int   = 5      # signal 5: how many persons to surface per turn
PEOPLE_EXPERIENCE_CAP: int   = 3      # signal 5: experiences attached per person


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class RetrievedContext:
    recency_summaries:    list[str] = field(default_factory=list)
    semantic_memories:    list[str] = field(default_factory=list)
    salient_memories:     list[str] = field(default_factory=list)
    semantic_experiences: list[str] = field(default_factory=list)
    important_people:     list[dict[str, Any]] = field(default_factory=list)
    active_emotions:      list[dict[str, Any]] = field(default_factory=list)
    active_distortions:   list[dict[str, Any]] = field(default_factory=list)
    recurring_triggers:   list[dict[str, Any]] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """
        Format the retrieved context as a structured text block for injection
        into the LLM system prompt. This is what memory_injection.md
        references as ``{kg_context}``.
        """
        lines: list[str] = ["=== Long-term memory context ==="]

        if self.recency_summaries:
            lines.append("\n[Recent sessions]")
            for i, s in enumerate(self.recency_summaries, 1):
                lines.append(f"  {i}. {s}")

        if self.semantic_memories:
            lines.append("\n[Relevant memories]")
            for s in self.semantic_memories:
                lines.append(f"  - {s}")

        if self.salient_memories:
            lines.append("\n[Significant memories]")
            for s in self.salient_memories:
                lines.append(f"  - {s}")

        if self.semantic_experiences:
            lines.append("\n[Past experiences]")
            for s in self.semantic_experiences:
                lines.append(f"  - {s}")

        if self.important_people:
            lines.append("\n[Important people]")
            for p in self.important_people:
                name        = p.get("name", "unknown")
                role        = p.get("role", "unknown")
                sentiment   = p.get("sentiment") or 0.0
                quality     = p.get("relationship_quality", "neutral")
                mentions    = p.get("mention_count", 0) or 0
                experiences = p.get("experiences") or []
                lines.append(
                    f"  - {name} ({role}, sentiment {sentiment:+.2f}, "
                    f"{quality}, mentioned {mentions}x)"
                )
                for exp in experiences:
                    lines.append(f"      * {exp}")

        if self.active_emotions:
            lines.append("\n[Recent emotional states]")
            for e in self.active_emotions:
                lines.append(
                    f"  - {e.get('label', 'unknown')} "
                    f"(intensity {e.get('intensity', 0):.1f}, "
                    f"valence {e.get('valence', 0):.2f})"
                )

        if self.active_distortions:
            lines.append("\n[Unchallenged cognitive distortions]")
            for t in self.active_distortions:
                lines.append(
                    f"  - [{t.get('distortion', 'unknown')}] "
                    f"\"{t.get('content', '')}\" "
                    f"(believability {t.get('believability', 0):.1f})"
                )

        if self.recurring_triggers:
            lines.append("\n[Recurring triggers]")
            for t in self.recurring_triggers:
                lines.append(
                    f"  - [{t.get('category', 'unknown')}] "
                    f"{t.get('description', '')} "
                    f"(seen {t.get('frequency', 1)}x)"
                )

        if len(lines) == 1:
            lines.append("  No prior context available for this user.")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Signal 1: Recency
# ---------------------------------------------------------------------------

async def _fetch_recency(user_id: str) -> list[str]:
    """Always retrieve last 2 session summaries regardless of topic."""
    records = await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAD_SESSION]->(s:Session)
        WHERE s.ended_at IS NOT NULL
          AND s.summary  IS NOT NULL
        RETURN s.summary AS summary
        ORDER BY s.started_at DESC
        LIMIT 2
        """,
        {"user_id": user_id},
    )
    return [r["summary"] for r in records]


# ---------------------------------------------------------------------------
# Signal 2: Semantic similarity (pgvector)
# ---------------------------------------------------------------------------

async def _touch_neo4j_access(node_ids: list[str]) -> None:
    """
    Bump ``last_accessed`` and ``access_count`` on the Neo4j Memory
    nodes that pgvector handed back. The Neo4j-side counters still
    drive the decay job; pgvector only tracks its own copy for retrieval.

    Failures here never propagate: a missed touch on access stats just
    delays decay, it does not corrupt retrieval.
    """
    if not node_ids:
        return
    try:
        await get_client().execute_write(
            """
            UNWIND $ids AS mid
            MATCH (m:Memory {id: mid})
            WHERE m.active = true
            SET m.last_accessed = datetime(),
                m.access_count  = coalesce(m.access_count, 0) + 1
            """,
            {"ids": node_ids},
        )
    except Exception as exc:
        logger.warning("Failed to refresh Memory access stats: %s", exc)


async def _fetch_semantic(
    user_id: str, query_embedding: list[float]
) -> list[str]:
    """
    Top-K active Memory summaries by cosine similarity to the current
    message embedding, retrieved via pgvector. Refreshes the Neo4j-side
    access stats for the hits we return.
    """
    hits: list[SearchHit] = await search_memory(
        user_id,
        query_embedding,
        top_k=SEMANTIC_TOP_K,
        min_similarity=SEMANTIC_FLOOR,
    )
    if not hits:
        return []

    await _touch_neo4j_access([h.neo4j_node_id for h in hits])
    return [h.content for h in hits]


# ---------------------------------------------------------------------------
# Signal 4: Past experiences (pgvector cosine on Experience nodes)
# ---------------------------------------------------------------------------

async def _touch_neo4j_experience_access(node_ids: list[str]) -> None:
    """
    Bump ``last_accessed`` and ``access_count`` on Experience nodes the
    pgvector probe surfaced. Same shape as the Memory touch helper, but
    against the :Experience label so the decay job can drop stale ones
    without affecting Memory counters. Failures never propagate.
    """
    if not node_ids:
        return
    try:
        await get_client().execute_write(
            """
            UNWIND $ids AS eid
            MATCH (e:Experience {id: eid})
            WHERE e.active = true
            SET e.last_accessed = datetime(),
                e.access_count  = coalesce(e.access_count, 0) + 1
            """,
            {"ids": node_ids},
        )
    except Exception as exc:
        logger.warning("Failed to refresh Experience access stats: %s", exc)


async def _fetch_semantic_experiences(
    user_id: str, query_embedding: list[float]
) -> list[str]:
    """
    Top-K Experience descriptions by cosine similarity. This is the
    surface that fixes the "bot remembers the person but not what they
    did" gap: Experience nodes were always written, just never read.
    """
    hits: list[SearchHit] = await search_experience(
        user_id,
        query_embedding,
        top_k=EXPERIENCE_TOP_K,
        min_similarity=EXPERIENCE_FLOOR,
    )
    if not hits:
        return []

    await _touch_neo4j_experience_access([h.neo4j_node_id for h in hits])
    return [h.content for h in hits]


# ---------------------------------------------------------------------------
# Signal 5: Important people + their experiences (Neo4j graph traversal)
# ---------------------------------------------------------------------------

async def _fetch_people(user_id: str) -> list[dict[str, Any]]:
    """
    Top-K Person nodes ranked by ``mention_count`` and absolute
    sentiment, each annotated with up to ``PEOPLE_EXPERIENCE_CAP``
    Experience descriptions reached through ``:INVOLVES_PERSON``.

    The traversal uses ``OPTIONAL MATCH`` so persons with no recorded
    experience still surface (they will just render without bullet
    children). Both the relationship and the Experience are filtered
    on ``t_invalid IS NULL`` and ``active = true`` to honour soft
    deletion.
    """
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[r:HAS_RELATIONSHIP_WITH]->(p:Person)
        WHERE p.active = true
          AND r.t_invalid IS NULL
        OPTIONAL MATCH (p)<-[ip:INVOLVES_PERSON]-(e:Experience)
          WHERE e.active = true
            AND ip.t_invalid IS NULL
        WITH p, r,
             collect(DISTINCT e.description) AS all_experiences
        WITH p, r,
             [d IN all_experiences WHERE d IS NOT NULL][..$exp_cap] AS experiences
        RETURN p.name                  AS name,
               p.role                  AS role,
               p.sentiment             AS sentiment,
               r.quality  AS relationship_quality,
               coalesce(p.mention_count, 0) AS mention_count,
               experiences
        ORDER BY coalesce(p.mention_count, 0) DESC,
                 abs(coalesce(p.sentiment, 0.0)) DESC
        LIMIT $top_k
        """,
        {
            "user_id": user_id,
            "top_k":   PEOPLE_TOP_K,
            "exp_cap": PEOPLE_EXPERIENCE_CAP,
        },
    )


# ---------------------------------------------------------------------------
# Signal 3: Salience
# ---------------------------------------------------------------------------

async def _fetch_salient(user_id: str, emotion_label: str | None) -> list[str]:
    """
    Top-5 Memory nodes with importance > 0.5. ``emotion_label`` is
    accepted for API stability; the affective re-rank is applied later
    in the pipeline so this query stays a pure salience cut.
    """
    del emotion_label  # reserved for downstream affective re-ranker
    records = await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory)
        WHERE m.active = true
          AND m.sensitivity_level = 'normal'
          AND m.importance > $cutoff
        RETURN m.summary    AS summary,
               m.importance AS importance
        ORDER BY m.importance DESC
        LIMIT $top_k
        """,
        {
            "user_id": user_id,
            "cutoff":  SALIENCE_CUTOFF,
            "top_k":   SALIENCE_TOP_K,
        },
    )
    return [r["summary"] for r in records]


# ---------------------------------------------------------------------------
# Supplementary KG reads (active emotions, distortions, triggers)
# ---------------------------------------------------------------------------

async def _fetch_active_emotions(user_id: str) -> list[dict[str, Any]]:
    """Recent active emotions from the last 7 days."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:FELT]->(em:Emotion)
        WHERE em.active = true
          AND em.timestamp > datetime() - duration('P7D')
        RETURN em.label     AS label,
               em.intensity AS intensity,
               em.valence   AS valence
        ORDER BY em.timestamp DESC
        LIMIT 5
        """,
        {"user_id": user_id},
    )


async def _fetch_active_distortions(user_id: str) -> list[dict[str, Any]]:
    """Unchallenged cognitive distortions -- top 3 most recent."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_THOUGHT]->(th:Thought)
        WHERE th.distortion IS NOT NULL
          AND th.challenged = false
        RETURN th.content       AS content,
               th.distortion    AS distortion,
               th.believability AS believability
        ORDER BY th.timestamp DESC
        LIMIT 3
        """,
        {"user_id": user_id},
    )


async def _fetch_recurring_triggers(user_id: str) -> list[dict[str, Any]]:
    """Top-3 most frequent active triggers."""
    return await get_client().execute_read(
        """
        MATCH (u:User {id: $user_id})-[:HAS_TRIGGER]->(t:Trigger)
        WHERE t.active = true
        RETURN t.category    AS category,
               t.description AS description,
               t.frequency   AS frequency
        ORDER BY t.frequency DESC
        LIMIT 3
        """,
        {"user_id": user_id},
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def build_context(
    user_id: str,
    query_embedding: list[float] | None = None,
    current_emotion_label: str | None = None,
) -> RetrievedContext:
    """
    Run every retrieval signal in parallel and assemble RetrievedContext.

    Args:
        user_id: The user whose context to retrieve.
        query_embedding: Embedding of the current user message. If None,
                         signals 2 and 4 (semantic Memory and Experience)
                         are skipped because both rely on cosine similarity.
        current_emotion_label: Detected emotion label for salience boost.

    Returns:
        RetrievedContext with all signals populated. Call .as_prompt_block()
        to get the formatted string for LLM injection.
    """
    async def _empty_list() -> list:
        return []

    semantic_memory_task = (
        _fetch_semantic(user_id, query_embedding)
        if query_embedding
        else _empty_list()
    )
    semantic_experience_task = (
        _fetch_semantic_experiences(user_id, query_embedding)
        if query_embedding
        else _empty_list()
    )

    results = await asyncio.gather(
        _fetch_recency(user_id),
        semantic_memory_task,
        _fetch_salient(user_id, current_emotion_label),
        semantic_experience_task,
        _fetch_people(user_id),
        _fetch_active_emotions(user_id),
        _fetch_active_distortions(user_id),
        _fetch_recurring_triggers(user_id),
        return_exceptions=True,
    )

    def safe(result: Any, default: list) -> list:
        if isinstance(result, Exception):
            logger.warning("Context retrieval signal failed: %s", result)
            return default
        return result

    ctx = RetrievedContext(
        recency_summaries=safe(results[0], []),
        semantic_memories=safe(results[1], []),
        salient_memories=safe(results[2], []),
        semantic_experiences=safe(results[3], []),
        important_people=safe(results[4], []),
        active_emotions=safe(results[5], []),
        active_distortions=safe(results[6], []),
        recurring_triggers=safe(results[7], []),
    )

    # Deduplicate Memory-derived strings against recency (overlap is common).
    # Experience descriptions deliberately stay on their own track even if
    # they coincide with Memory hits, because the LLM benefits from seeing
    # the raw situation alongside the compressed summary.
    seen: set[str] = set(ctx.recency_summaries)
    ctx.semantic_memories = [
        s for s in ctx.semantic_memories if s not in seen and not seen.add(s)  # type: ignore[func-returns-value]
    ]
    ctx.salient_memories = [
        s for s in ctx.salient_memories  if s not in seen and not seen.add(s)  # type: ignore[func-returns-value]
    ]

    logger.debug(
        "Context built for %s: recency=%d semantic=%d salient=%d "
        "experiences=%d people=%d",
        user_id,
        len(ctx.recency_summaries),
        len(ctx.semantic_memories),
        len(ctx.salient_memories),
        len(ctx.semantic_experiences),
        len(ctx.important_people),
    )
    return ctx
