"""
agentic/memory/kg_retriever/relationships.py

Cross-cutting relationship builders, the full edge set required by
the canonical KG schema (KG_Schema_Design.md, section 3).

Moved out of kg_writer so the schema-and-edge surface area lives next
to the retrieval logic that consumes it. The kg_writer package now
imports its relationship builders from this module (see
``agentic.memory.kg_writer.__init__``) so existing callers keep
working.

This module owns the relationships that span more than one node type;
the per-node writers only own the User-anchor edges they create at the
same time as the node itself (e.g. emotion_kg also creates
(:Session)-[:RECORDED_EMOTION]->(:Emotion) because that edge has the
same lifetime as the Emotion node).

Edges implemented here, grouped by concern:

  CBT hot-cross bun chain
    1. (Experience)-[:TRIGGERED_BY]->(Trigger)
    2. (Experience)-[:TRIGGERED_EMOTION]->(Emotion)
    3. (Emotion)-[:ACTIVATED_THOUGHT]->(Thought)
    4. (Thought)<-[:ASSOCIATED_WITH]->(Emotion)        bidirectional
    5. (Emotion|Thought)-[:LED_TO_BEHAVIOR]->(Behavior)

  Contextual links
    6. (Experience)-[:INVOLVES_PERSON]->(Person)
    7. (Experience|Emotion)-[:RELATED_TO_TOPIC]->(Topic)
    8. (User)-[:HAS_RECURRING_THEME]->(Topic)
    9. (Session)-[:CONTAINS_MEMORY]->(Memory)
        -- normally created inline by memory_kg.write_memory; this
           helper exists for backfill or out-of-band linkage.

  Bi-temporal maintenance
   10. invalidate_edge(...) -- set t_invalid on a fact-bearing edge
                               so it stays queryable for history but is
                               filtered out of "currently true" queries.

Conventions for every edge in this module:

  * MERGE-based, idempotent. Re-running is safe.
  * On CREATE the bi-temporal properties are set:
        t_valid         = datetime()
        t_invalid       = null
        confidence      = caller-supplied
        source_session  = caller-supplied
        source_messages = [message_id] when caller supplies one, else []
  * On MATCH ``confidence``, ``source_session`` are refreshed and the
    new ``source_message_id`` (when supplied) is appended to
    ``source_messages`` so the lifecycle module can find this edge from
    any of its contributing messages. The original t_valid is preserved
    as the moment we first learned the fact.

Callers must hand in real node ids. If either endpoint is missing the
MATCH fails and the MERGE becomes a no-op rather than raising; check
ids upstream if strict behaviour is required.
"""

from __future__ import annotations

import logging

from agentic.memory.neo4j_client import get_client

logger = logging.getLogger(__name__)


# ============================================================================
# CBT hot-cross bun chain
# ============================================================================

# ---------------------------------------------------------------------------
# 1. Experience -> Trigger
# ---------------------------------------------------------------------------

async def link_experience_to_trigger(
    experience_id: str,
    trigger_id:    str,
    session_id:    str,
    confidence:    float = 0.85,
    source_message_id: str | None = None,
) -> None:
    """(:Experience)-[:TRIGGERED_BY]->(:Trigger)"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (t:Trigger    {id: $trig_id})
        MERGE (e)-[r:TRIGGERED_BY]->(t)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "exp_id":     experience_id,
            "trig_id":    trigger_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 2. Experience -> Emotion
# ---------------------------------------------------------------------------

async def link_experience_to_emotion(
    experience_id: str,
    emotion_id:    str,
    session_id:    str,
    confidence:    float = 0.85,
    source_message_id: str | None = None,
) -> None:
    """(:Experience)-[:TRIGGERED_EMOTION]->(:Emotion)"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (em:Emotion   {id: $emo_id})
        MERGE (e)-[r:TRIGGERED_EMOTION]->(em)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "exp_id":     experience_id,
            "emo_id":     emotion_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 3. Emotion -> Thought
# ---------------------------------------------------------------------------

async def link_emotion_to_thought(
    emotion_id:  str,
    thought_id:  str,
    session_id:  str,
    confidence:  float = 0.80,
    source_message_id: str | None = None,
) -> None:
    """(:Emotion)-[:ACTIVATED_THOUGHT]->(:Thought)"""
    await get_client().execute_write(
        """
        MATCH (em:Emotion {id: $emo_id})
        MATCH (th:Thought {id: $th_id})
        MERGE (em)-[r:ACTIVATED_THOUGHT]->(th)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "emo_id":     emotion_id,
            "th_id":      thought_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 4. Thought <-> Emotion  (ASSOCIATED_WITH, bidirectional)
# ---------------------------------------------------------------------------

async def link_thought_emotion_association(
    thought_id:  str,
    emotion_id:  str,
    session_id:  str,
    strength:    float = 0.80,
    confidence:  float = 0.80,
    source_message_id: str | None = None,
) -> None:
    """
    (:Thought)<-[:ASSOCIATED_WITH]->(:Emotion)

    The CBT vicious cycle: thoughts reinforce emotions and emotions
    reinforce thoughts. Per the canonical schema this edge is
    bidirectional, modelled as two directed MERGEs in Neo4j (which has
    no native bidirectional edge type) so each direction can be matched
    independently in retrieval.

    ``strength`` is a [0, 1] score for how tightly coupled the pair is;
    it is exposed on both directions identically.
    """
    await get_client().execute_write(
        """
        MATCH (th:Thought {id: $th_id})
        MATCH (em:Emotion {id: $emo_id})

        MERGE (th)-[r1:ASSOCIATED_WITH]->(em)
        ON CREATE SET
            r1.strength        = $strength,
            r1.t_valid         = datetime(),
            r1.t_invalid       = null,
            r1.confidence      = $confidence,
            r1.source_session  = $session_id,
            r1.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r1.strength        = $strength,
            r1.confidence      = $confidence,
            r1.source_session  = $session_id,
            r1.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r1.source_messages, [])
                THEN coalesce(r1.source_messages, [])
                ELSE coalesce(r1.source_messages, []) + $message_id
            END

        MERGE (em)-[r2:ASSOCIATED_WITH]->(th)
        ON CREATE SET
            r2.strength        = $strength,
            r2.t_valid         = datetime(),
            r2.t_invalid       = null,
            r2.confidence      = $confidence,
            r2.source_session  = $session_id,
            r2.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r2.strength        = $strength,
            r2.confidence      = $confidence,
            r2.source_session  = $session_id,
            r2.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r2.source_messages, [])
                THEN coalesce(r2.source_messages, [])
                ELSE coalesce(r2.source_messages, []) + $message_id
            END
        """,
        {
            "th_id":      thought_id,
            "emo_id":     emotion_id,
            "session_id": session_id,
            "strength":   strength,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 5. Emotion or Thought -> Behavior
# ---------------------------------------------------------------------------

async def link_to_behavior(
    source_id:     str,
    source_label:  str,
    behavior_id:   str,
    session_id:    str,
    confidence:    float = 0.80,
    source_message_id: str | None = None,
) -> None:
    """
    (:Emotion | :Thought)-[:LED_TO_BEHAVIOR]->(:Behavior)

    ``source_label`` must be hard-coded to "Emotion" or "Thought"; it
    is interpolated into the Cypher string, so never pass user input.
    """
    if source_label not in ("Emotion", "Thought"):
        raise ValueError(
            f"source_label must be 'Emotion' or 'Thought', got {source_label!r}"
        )

    await get_client().execute_write(
        f"""
        MATCH (src:{source_label} {{id: $src_id}})
        MATCH (b:Behavior         {{id: $beh_id}})
        MERGE (src)-[r:LED_TO_BEHAVIOR]->(b)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "src_id":     source_id,
            "beh_id":     behavior_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ============================================================================
# Contextual links
# ============================================================================

# ---------------------------------------------------------------------------
# 6. Experience -> Person
# ---------------------------------------------------------------------------

async def link_experience_to_person(
    experience_id: str,
    person_id:     str,
    session_id:    str,
    confidence:    float = 0.80,
    source_message_id: str | None = None,
) -> None:
    """(:Experience)-[:INVOLVES_PERSON]->(:Person)"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (p:Person     {id: $p_id})
        MERGE (e)-[r:INVOLVES_PERSON]->(p)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "exp_id":     experience_id,
            "p_id":       person_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 7. Experience | Emotion -> Topic
# ---------------------------------------------------------------------------

async def link_to_topic(
    source_id:     str,
    source_label:  str,
    topic_id:      str,
    session_id:    str,
    confidence:    float = 0.75,
    source_message_id: str | None = None,
) -> None:
    """
    (:Experience | :Emotion)-[:RELATED_TO_TOPIC]->(:Topic)

    ``source_label`` must be hard-coded to "Experience" or "Emotion";
    it is interpolated into the Cypher string, so never pass user
    input. Per the canonical schema the same RELATED_TO_TOPIC edge
    type is used for both source types.
    """
    if source_label not in ("Experience", "Emotion"):
        raise ValueError(
            f"source_label must be 'Experience' or 'Emotion', got {source_label!r}"
        )

    await get_client().execute_write(
        f"""
        MATCH (src:{source_label} {{id: $src_id}})
        MATCH (top:Topic           {{id: $top_id}})
        MERGE (src)-[r:RELATED_TO_TOPIC]->(top)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "src_id":     source_id,
            "top_id":     topic_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 8. User -> Topic  (HAS_RECURRING_THEME)
# ---------------------------------------------------------------------------

async def link_user_recurring_theme(
    user_id:    str,
    topic_id:   str,
    session_id: str,
    confidence: float = 0.85,
    source_message_id: str | None = None,
) -> None:
    """
    (:User)-[:HAS_RECURRING_THEME]->(:Topic)

    A longitudinal pattern link, refreshed each time the topic appears
    in a new session. ``last_reinforced`` is updated on every match so
    decay can identify themes that have gone quiet.
    """
    await get_client().execute_write(
        """
        MATCH (u:User   {id: $user_id})
        MATCH (top:Topic {id: $top_id})
        MERGE (u)-[r:HAS_RECURRING_THEME]->(top)
        ON CREATE SET
            r.t_valid          = datetime(),
            r.t_invalid        = null,
            r.first_reinforced = datetime(),
            r.last_reinforced  = datetime(),
            r.times_reinforced = 1,
            r.confidence       = $confidence,
            r.source_session   = $session_id,
            r.source_messages  = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.last_reinforced  = datetime(),
            r.times_reinforced = coalesce(r.times_reinforced, 1) + 1,
            r.confidence       = $confidence,
            r.source_session   = $session_id,
            r.source_messages  = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END
        """,
        {
            "user_id":    user_id,
            "top_id":     topic_id,
            "session_id": session_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ---------------------------------------------------------------------------
# 9. Session -> Memory  (provenance helper)
# ---------------------------------------------------------------------------

async def link_session_to_memory(
    session_id:  str,
    memory_id:   str,
    confidence:  float = 1.0,
    source_message_id: str | None = None,
) -> None:
    """
    (:Session)-[:CONTAINS_MEMORY]->(:Memory)

    memory_kg.write_memory already creates this edge inline at the
    moment the Memory node is created. This helper exists for backfill
    scripts and for the rare case where a Memory needs to be attached
    to an additional session after the fact (e.g. cross-session
    summarisation).
    """
    await get_client().execute_write(
        """
        MATCH (s:Session {id: $session_id})
        MATCH (m:Memory  {id: $memory_id})
        MERGE (s)-[r:CONTAINS_MEMORY]->(m)
        ON CREATE SET
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        """,
        {
            "session_id": session_id,
            "memory_id":  memory_id,
            "confidence": confidence,
            "message_id": source_message_id,
        },
    )


# ============================================================================
# Bi-temporal maintenance
# ============================================================================

# A small allow-list of edge types that this helper will touch. Edge
# types are interpolated into the Cypher string, so we MUST validate
# them against this set to keep the call injection-safe.
_INVALIDATABLE_EDGES: frozenset[str] = frozenset({
    # CBT chain
    "TRIGGERED_BY",
    "TRIGGERED_EMOTION",
    "ACTIVATED_THOUGHT",
    "ASSOCIATED_WITH",
    "LED_TO_BEHAVIOR",
    # User connections
    "EXPERIENCED",
    "FELT",
    "HAS_THOUGHT",
    "HAS_TRIGGER",
    "EXHIBITED",
    "HAS_RELATIONSHIP_WITH",
    "HAS_RECURRING_THEME",
    "HAS_MEMORY",
    "COMPLETED_ASSESSMENT",
    # Session connections
    "HAD_EXPERIENCE",
    "RECORDED_EMOTION",
    "CONTAINS_MEMORY",
    # Contextual
    "INVOLVES_PERSON",
    "RELATED_TO_TOPIC",
})


async def invalidate_edge(
    src_label:  str,
    src_id:     str,
    edge_type:  str,
    dst_label:  str,
    dst_id:     str,
    reason:     str = "user_correction",
) -> int:
    """
    Set ``t_invalid = datetime()`` on the matching fact-bearing edge so
    the relationship stays in the graph for history but drops out of
    "currently true" queries that filter on ``t_invalid IS NULL``.

    Returns the number of edges that were invalidated (0 if no match).

    All three label/type arguments are validated against allow-lists or
    a small fixed alphabet because they get interpolated into the
    Cypher string.
    """
    if edge_type not in _INVALIDATABLE_EDGES:
        raise ValueError(
            f"edge_type {edge_type!r} not in invalidation allow-list"
        )

    # Restrict labels to identifier characters; defensive even though
    # callers should be passing well-known node labels.
    for arg_name, value in (("src_label", src_label), ("dst_label", dst_label)):
        if not value.isidentifier():
            raise ValueError(f"{arg_name} {value!r} is not a valid Neo4j label")

    records = await get_client().execute_write(
        f"""
        MATCH (src:{src_label} {{id: $src_id}})
              -[r:{edge_type}]->
              (dst:{dst_label} {{id: $dst_id}})
        WHERE r.t_invalid IS NULL
        SET r.t_invalid           = datetime(),
            r.invalidation_reason = $reason
        RETURN count(r) AS invalidated
        """,
        {
            "src_id": src_id,
            "dst_id": dst_id,
            "reason": reason,
        },
    )
    invalidated = records[0]["invalidated"] if records else 0
    if invalidated:
        logger.info(
            "Invalidated %d edge(s): (%s %s)-[:%s]->(%s %s) reason=%s",
            invalidated, src_label, src_id, edge_type, dst_label, dst_id, reason,
        )
    return invalidated
