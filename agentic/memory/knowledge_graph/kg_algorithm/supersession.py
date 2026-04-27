"""
agentic/memory/kg_algorithm/supersession.py

Contradiction resolution for :Thought nodes.

Lives in kg_algorithm (alongside decay) because supersession is an
algorithmic operation on the graph rather than an extractor-driven
write. The kg_writer package re-exports this symbol so existing
callers do not break.

When a CBT reframe succeeds (either via the cbt_reframe.md prompt or
because the user explicitly challenges an automatic thought), we do
NOT mutate the old thought. Instead:

    1. Mark the old Thought.active = false.
    2. CREATE a new Thought capturing the reframed content
       (challenged = true, distortion = null).
    3. CREATE a SUPERSEDES edge: (new)-[:SUPERSEDES]->(old) with the
       reason and a timestamp, so the full trajectory is queryable.

This preserves the user's historical cognitive state -- crucial for
progress metrics (e.g. "how many distortions has this user reframed
this month"), for the therapist's pre-screening profile, and for
bi-temporal replay of the knowledge graph.

Supersession is a different concern from deduplication (see
thought_kg.py): dedup collapses two near-identical thoughts into one
active node, supersession replaces a thought with a new one while
keeping both in the graph.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_algorithm._common  import _new_id, _require
from agentic.memory.knowledge_graph.kg_retriever.schemas  import ThoughtInput
from agentic.memory.neo4j_client          import get_client

logger = logging.getLogger(__name__)


async def supersede_thought(
    old_thought_id: str,
    new_thought:    ThoughtInput,
    reason:         str = "user_reframe",
) -> str:
    """
    Supersede ``old_thought_id`` with a new thought described by
    ``new_thought``. Returns the id of the new Thought.

    Common reasons:
      * "user_reframe"   -- user explicitly challenged the thought
      * "cbt_reframe"    -- CBT prompt produced an alternative
      * "therapist_note" -- a therapist session superseded it
    """
    _require(old_thought_id,         "old_thought_id")
    _require(new_thought.content,    "new_thought.content")
    _require(new_thought.user_id,    "new_thought.user_id")
    _require(new_thought.session_id, "new_thought.session_id")

    client = get_client()
    new_id = _new_id()

    await client.execute_write(
        """
        MATCH (old:Thought {id: $old_id})
        SET old.active = false

        WITH old
        MATCH (u:User {id: $user_id})
        CREATE (new:Thought {
            id:                $new_id,
            content:           $content,
            thought_type:      $thought_type,
            distortion:        null,
            believability:     $believability,
            challenged:        true,
            timestamp:         datetime(),
            embedding:         $embedding,
            active:            true,
            sensitivity_level: $sensitivity_level
        })
        CREATE (new)-[:SUPERSEDES {
            at:             datetime(),
            reason:         $reason,
            source_session: $session_id
        }]->(old)
        CREATE (u)-[:HAS_THOUGHT {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(new)
        RETURN new.id AS id
        """,
        {
            "old_id":            old_thought_id,
            "user_id":           new_thought.user_id,
            "session_id":        new_thought.session_id,
            "new_id":            new_id,
            "content":           new_thought.content,
            "thought_type":      new_thought.thought_type,
            "believability":     new_thought.believability,
            "embedding":         new_thought.embedding,
            "sensitivity_level": new_thought.sensitivity_level,
            "confidence":        new_thought.confidence,
            "reason":            reason,
        },
    )
    logger.info(
        "Thought superseded: %s -> %s (reason=%s)",
        old_thought_id, new_id, reason,
    )
    return new_id
