"""
agentic/memory/context_builder.py

Three-signal hybrid retrieval strategy.
Called from memory_retrieval.py (LangGraph node) before every LLM generation.

The three signals (KG_Schema_Design.docx, Section 5):
  Signal 1 -- Recency:  last 2 session summaries (always retrieved)
  Signal 2 -- Semantic: pgvector cosine top-5 Memory nodes
  Signal 3 -- Salience: importance > 0.5 ordered by importance DESC LIMIT 5

Results are merged, deduplicated, and formatted as a structured context block
that is injected into the LLM system prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .neo4j_client import get_client

logger = logging.getLogger(__name__)

SEMANTIC_TOP_K  = 5
SALIENCE_TOP_K  = 5
SALIENCE_CUTOFF = 0.5


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class RetrievedContext:
    recency_summaries:  list[str] = field(default_factory=list)
    semantic_memories:  list[str] = field(default_factory=list)
    salient_memories:   list[str] = field(default_factory=list)
    active_emotions:    list[dict[str, Any]] = field(default_factory=list)
    active_distortions: list[dict[str, Any]] = field(default_factory=list)
    recurring_triggers: list[dict[str, Any]] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """
        Format the retrieved context as a structured text block for injection
        into the LLM system prompt.

        This is what memory_injection.md references as {kg_context}.
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
# Signal 2: Semantic similarity (pgvector / Neo4j vector index)
# ---------------------------------------------------------------------------

async def _fetch_semantic(
    user_id: str, query_embedding: list[float]
) -> list[str]:
    """
    Top-5 Memory nodes by cosine similarity to the current message embedding.
    Only returns active, normal-sensitivity memories.
    Updates last_accessed and increments access_count on retrieved nodes.
    """
    records = await get_client().execute_write(
        # Write session because we update last_accessed
        """
        MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory)
        WHERE m.active = true
          AND m.sensitivity_level = 'normal'
          AND m.embedding IS NOT NULL
        WITH m,
             vector.similarity.cosine(m.embedding, $embedding) AS similarity
        WHERE similarity > 0.5
        SET m.last_accessed = datetime(),
            m.access_count  = m.access_count + 1
        RETURN m.summary AS summary, similarity
        ORDER BY similarity DESC
        LIMIT $top_k
        """,
        {
            "user_id":   user_id,
            "embedding": query_embedding,
            "top_k":     SEMANTIC_TOP_K,
        },
    )
    return [r["summary"] for r in records]


# ---------------------------------------------------------------------------
# Signal 3: Salience
# ---------------------------------------------------------------------------

async def _fetch_salient(user_id: str, emotion_label: str | None) -> list[str]:
    """
    Top-5 Memory nodes with importance > 0.5, optionally filtered by matching
    emotion label for emotional salience boost.
    """
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
        RETURN th.content      AS content,
               th.distortion   AS distortion,
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
    Run all three retrieval signals in parallel and assemble RetrievedContext.

    Args:
        user_id: The user whose context to retrieve.
        query_embedding: Embedding of the current user message. If None,
                         signal 2 (semantic) is skipped.
        current_emotion_label: Detected emotion label for salience boost.

    Returns:
        RetrievedContext with all signals populated. Call .as_prompt_block()
        to get the formatted string for LLM injection.
    """
    import asyncio

    # Run all queries concurrently
    results = await asyncio.gather(
        _fetch_recency(user_id),
        _fetch_semantic(user_id, query_embedding) if query_embedding else asyncio.coroutine(lambda: [])(),
        _fetch_salient(user_id, current_emotion_label),
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
        active_emotions=safe(results[3], []),
        active_distortions=safe(results[4], []),
        recurring_triggers=safe(results[5], []),
    )

    # Deduplicate semantic and salient (overlap is common)
    seen: set[str] = set(ctx.recency_summaries)
    ctx.semantic_memories = [s for s in ctx.semantic_memories if s not in seen and not seen.add(s)]  # type: ignore[func-returns-value]
    ctx.salient_memories  = [s for s in ctx.salient_memories  if s not in seen and not seen.add(s)]  # type: ignore[func-returns-value]

    logger.debug(
        "Context built for %s: recency=%d semantic=%d salient=%d",
        user_id,
        len(ctx.recency_summaries),
        len(ctx.semantic_memories),
        len(ctx.salient_memories),
    )
    return ctx