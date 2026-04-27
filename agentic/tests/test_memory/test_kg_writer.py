"""
agentic/tests/test_memory/test_kg_writer.py

End-to-end integration tests for the Neo4j knowledge graph writer layer.

Scope
-----
Every AI-coupled writer in ``agentic.memory.kg_writer`` plus the full
relationship builder set, the supersession helper, the memory decay job,
and the idle-flush worker in ``agentic.memory.neo4j_client``.

These tests hit a real Neo4j. If the database is not reachable the
``conftest.py`` reachability gate auto-skips the module.

Reading order
-------------
1. Node writers, one block per node type, following the CBT hot-cross bun:
   Experience -> Trigger -> Emotion -> Thought -> Behavior -> Person ->
   Memory.
2. Deduplication checks (Thought/Experience cosine, Trigger/Behavior
   keyword).
3. Relationship builders (full edge set).
4. Supersession + decay + idle-flush worker.

Each test owns its own namespace via the ``test_namespace`` fixture, so
nodes are torn down deterministically.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from agentic.memory import neo4j_client as nc
from agentic.memory.knowledge_graph.kg_writer import (
    BehaviorInput,
    EmotionInput,
    ExperienceInput,
    MemoryInput,
    PersonInput,
    ThoughtInput,
    TriggerInput,
    invalidate_edge,
    link_emotion_to_thought,
    link_experience_to_emotion,
    link_experience_to_person,
    link_experience_to_trigger,
    link_session_to_memory,
    link_thought_emotion_association,
    link_to_behavior,
    link_to_topic,
    link_user_recurring_theme,
    run_memory_decay,
    supersede_thought,
    write_behavior,
    write_emotion,
    write_experience,
    write_memory,
    write_person,
    write_thought,
    write_trigger,
)

from .conftest import neo4j_required

pytestmark = [pytest.mark.asyncio, neo4j_required]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(hours_ago: int = 0) -> str:
    """Small timestamp helper with an offset, in ISO 8601 UTC form."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _emb(dim: int = 1536, base: float = 0.01) -> list[float]:
    """
    Cheap deterministic embedding of unit-ish scale so cosine similarity
    behaves predictably. Real production embeddings are 1536-dim, so we
    use that to keep the test representative of the actual index.
    """
    return [base + (i % 7) * 1e-4 for i in range(dim)]


def _emb_similar(base: list[float], jitter: float = 1e-6) -> list[float]:
    """A near-duplicate embedding for dedup merge-path tests."""
    return [v + jitter for v in base]


def _emb_unrelated(dim: int = 1536) -> list[float]:
    """An embedding that should not collide with _emb() under cosine."""
    return [0.5 + (i % 3) * 0.1 for i in range(dim)]


# ---------------------------------------------------------------------------
# 1. Node writers
# ---------------------------------------------------------------------------

class TestExperienceWriter:
    async def test_create_experience_with_bitemporal_edges(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        exp_id = await write_experience(ExperienceInput(
            description="I bombed my midterm in fluid mechanics",
            occurred_at=_iso(hours_ago=2),
            extracted_at=_iso(),
            valence=-0.7,
            significance=0.8,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=_emb(),
        ))

        assert exp_id, "write_experience must return a node id"

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[r1:EXPERIENCED]->(e:Experience {id: $eid})
            MATCH (s:Session {id: $sid})-[r2:HAD_EXPERIENCE]->(e)
            RETURN e.description   AS description,
                   e.valence       AS valence,
                   e.significance  AS significance,
                   e.active        AS active,
                   r1.t_invalid    AS user_edge_invalid,
                   r2.source_session AS session_edge_provenance
            """,
            {
                "uid": test_namespace["user_id"],
                "sid": test_namespace["session_id"],
                "eid": exp_id,
            },
        )
        assert row is not None, "experience + both edges must be present"
        assert row["valence"] == pytest.approx(-0.7)
        assert row["active"] is True
        assert row["user_edge_invalid"] is None
        assert row["session_edge_provenance"] == test_namespace["session_id"]

    async def test_experience_dedup_merges_and_boosts_significance(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        emb = _emb()
        base_inp = ExperienceInput(
            description="I failed my thesis defense rehearsal",
            occurred_at=_iso(hours_ago=1),
            extracted_at=_iso(),
            valence=-0.6,
            significance=0.5,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=emb,
        )
        first_id = await write_experience(base_inp)

        # Near-identical embedding must collapse into the same node.
        second_id = await write_experience(ExperienceInput(
            description="Failed the thesis rehearsal again",
            occurred_at=_iso(),
            extracted_at=_iso(),
            valence=-0.65,
            significance=0.5,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=_emb_similar(emb),
        ))
        assert first_id == second_id, "cosine dedup must merge the two nodes"

        row = await neo4j_client.execute_read_single(
            "MATCH (e:Experience {id: $id}) RETURN e.significance AS sig",
            {"id": first_id},
        )
        assert row["sig"] > 0.5, "significance must be bumped on merge"

    async def test_experience_requires_extracted_at(
        self, test_namespace: dict
    ) -> None:
        with pytest.raises(ValueError, match="extracted_at"):
            await write_experience(ExperienceInput(
                description="x",
                occurred_at=_iso(),
                extracted_at="",
                valence=0.0,
                significance=0.5,
                user_id=test_namespace["user_id"],
                session_id=test_namespace["session_id"],
            ))


class TestTriggerWriter:
    async def test_create_trigger_with_aliases(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        trig_id = await write_trigger(TriggerInput(
            category="academic",
            description="Upcoming finals week",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            aliases=["midterm panic"],
        ))

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[:HAS_TRIGGER]->(t:Trigger {id: $tid})
            RETURN t.frequency AS frequency,
                   t.active    AS active,
                   t.aliases   AS aliases
            """,
            {"uid": test_namespace["user_id"], "tid": trig_id},
        )
        assert row["frequency"] == 1
        assert row["active"] is True
        assert row["aliases"] == ["midterm panic"]

    async def test_trigger_merge_increments_frequency_and_folds_aliases(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        # The trigger writer dedups by checking whether the new description's
        # first 30-char keyword is *contained in* an existing description in
        # the same category. So the second insert's description must be a
        # substring (prefix) of the first for the merge path to fire.
        first_id = await write_trigger(TriggerInput(
            category="academic",
            description="Upcoming finals week pressure is overwhelming",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        second_id = await write_trigger(TriggerInput(
            category="academic",
            description="Upcoming finals week",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            aliases=["exam stress"],
        ))
        assert first_id == second_id

        row = await neo4j_client.execute_read_single(
            "MATCH (t:Trigger {id: $id}) RETURN t.frequency AS f, t.aliases AS a",
            {"id": first_id},
        )
        assert row["f"] == 2
        assert "exam stress" in row["a"]
        assert "Upcoming finals week" in row["a"]


class TestEmotionWriter:
    async def test_emotion_writes_felt_and_recorded_emotion_edges(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        emo_id = await write_emotion(EmotionInput(
            label="anxious",
            intensity=0.85,
            valence=-0.6,
            arousal=0.8,
            dominance=-0.3,
            source_text="I can't stop thinking about tomorrow",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[:FELT]->(em:Emotion {id: $eid})
            MATCH (s:Session {id: $sid})-[:RECORDED_EMOTION]->(em)
            RETURN em.label     AS label,
                   em.intensity AS intensity,
                   em.active    AS active
            """,
            {
                "uid": test_namespace["user_id"],
                "sid": test_namespace["session_id"],
                "eid": emo_id,
            },
        )
        assert row is not None
        assert row["label"] == "anxious"
        assert row["intensity"] == pytest.approx(0.85)
        assert row["active"] is True


class TestThoughtWriter:
    async def test_thought_creates_with_challenged_false(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        th_id = await write_thought(ThoughtInput(
            content="If I fail this, my whole career is over",
            thought_type="automatic",
            distortion="catastrophizing",
            believability=0.9,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=_emb(),
        ))

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[:HAS_THOUGHT]->(th:Thought {id: $tid})
            RETURN th.content     AS content,
                   th.challenged  AS challenged,
                   th.distortion  AS distortion,
                   th.believability AS believability
            """,
            {"uid": test_namespace["user_id"], "tid": th_id},
        )
        assert row["challenged"] is False
        assert row["distortion"] == "catastrophizing"
        assert row["believability"] == pytest.approx(0.9)

    async def test_thought_dedup_averages_believability_and_resets_challenged(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        emb = _emb()
        first_id = await write_thought(ThoughtInput(
            content="I'm not smart enough",
            thought_type="core_belief",
            distortion="labeling",
            believability=0.8,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=emb,
        ))
        # Manually flip challenged so we can verify the dedup reset behaviour.
        await neo4j_client.execute_write(
            "MATCH (th:Thought {id: $id}) SET th.challenged = true",
            {"id": first_id},
        )

        second_id = await write_thought(ThoughtInput(
            content="I am not intelligent enough for this",
            thought_type="core_belief",
            distortion="labeling",
            believability=0.4,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=_emb_similar(emb),
        ))
        assert first_id == second_id

        row = await neo4j_client.execute_read_single(
            "MATCH (th:Thought {id: $id}) "
            "RETURN th.believability AS b, th.challenged AS c",
            {"id": first_id},
        )
        assert row["b"] == pytest.approx((0.8 + 0.4) / 2)
        assert row["c"] is False, "merge path must reset challenged to false"


class TestBehaviorWriter:
    async def test_behavior_create_then_increment(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        first_id = await write_behavior(BehaviorInput(
            description="Stayed in bed instead of attending class",
            category="avoidance",
            adaptive=False,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        second_id = await write_behavior(BehaviorInput(
            description="Stayed in bed instead of attending lab",
            category="avoidance",
            adaptive=False,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        assert first_id == second_id

        row = await neo4j_client.execute_read_single(
            "MATCH (b:Behavior {id: $id}) RETURN b.frequency AS f",
            {"id": first_id},
        )
        assert row["f"] == 2


class TestPersonWriter:
    async def test_person_upsert_updates_sentiment_and_mentions(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        first_id = await write_person(PersonInput(
            name="Amelia",
            role="friend",
            sentiment=0.4,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            relationship_quality="supportive",
        ))
        second_id = await write_person(PersonInput(
            name="Amelia",
            role="friend",
            sentiment=-0.2,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            relationship_quality="complicated",
        ))
        assert first_id == second_id

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[r:HAS_RELATIONSHIP_WITH]->(p:Person {id: $pid})
            RETURN p.sentiment     AS sentiment,
                   p.mention_count AS mc,
                   r.quality       AS quality
            """,
            {"uid": test_namespace["user_id"], "pid": first_id},
        )
        assert row["mc"] == 2
        assert row["sentiment"] == pytest.approx((0.4 + -0.2) / 2)
        assert row["quality"] == "complicated"


class TestMemoryWriter:
    async def test_memory_writes_has_memory_and_contains_memory(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        mem_id = await write_memory(MemoryInput(
            summary="Session covered midterm anxiety and reframed a "
                    "catastrophizing thought",
            importance=0.7,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            embedding=_emb(),
        ))

        row = await neo4j_client.execute_read_single(
            """
            MATCH (u:User {id: $uid})-[:HAS_MEMORY]->(m:Memory {id: $mid})
            MATCH (s:Session {id: $sid})-[:CONTAINS_MEMORY]->(m)
            RETURN m.importance   AS imp,
                   m.access_count AS ac,
                   m.active       AS active
            """,
            {
                "uid": test_namespace["user_id"],
                "sid": test_namespace["session_id"],
                "mid": mem_id,
            },
        )
        assert row is not None
        assert row["imp"] == pytest.approx(0.7)
        assert row["ac"] == 0
        assert row["active"] is True


# ---------------------------------------------------------------------------
# 2. Relationship builders
# ---------------------------------------------------------------------------

class TestRelationshipBuilders:
    async def _scaffold(
        self, neo4j_client, test_namespace, seed_topic=None
    ) -> dict[str, str]:
        """Create a mini CBT chain we can wire edges against."""
        exp_id = await write_experience(ExperienceInput(
            description="Presentation went badly",
            occurred_at=_iso(hours_ago=1),
            extracted_at=_iso(),
            valence=-0.5,
            significance=0.6,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        trig_id = await write_trigger(TriggerInput(
            category="academic",
            description="Public speaking",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        emo_id = await write_emotion(EmotionInput(
            label="ashamed",
            intensity=0.7,
            valence=-0.8,
            arousal=0.6,
            dominance=-0.5,
            source_text="Everyone saw me stumble",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        th_id = await write_thought(ThoughtInput(
            content="Everyone thinks I'm incompetent",
            thought_type="automatic",
            distortion="mind_reading",
            believability=0.75,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        beh_id = await write_behavior(BehaviorInput(
            description="Skipped lab the next morning",
            category="avoidance",
            adaptive=False,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        per_id = await write_person(PersonInput(
            name="Prof Reza",
            role="professor",
            sentiment=-0.2,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
            relationship_quality="complicated",
        ))
        return {
            "exp": exp_id, "trig": trig_id, "emo": emo_id,
            "th":  th_id,  "beh":  beh_id,  "per": per_id,
        }

    async def test_full_cbt_chain(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        ids = await self._scaffold(neo4j_client, test_namespace)
        sid = test_namespace["session_id"]

        await link_experience_to_trigger(ids["exp"], ids["trig"], sid)
        await link_experience_to_emotion(ids["exp"], ids["emo"], sid)
        await link_emotion_to_thought(ids["emo"], ids["th"], sid)
        await link_thought_emotion_association(ids["th"], ids["emo"], sid, strength=0.9)
        await link_to_behavior(ids["emo"], "Emotion", ids["beh"], sid)
        await link_to_behavior(ids["th"],  "Thought", ids["beh"], sid)

        row = await neo4j_client.execute_read_single(
            """
            MATCH (e:Experience {id: $exp})-[:TRIGGERED_BY]->(t:Trigger {id: $trig})
            MATCH (e)-[:TRIGGERED_EMOTION]->(em:Emotion {id: $emo})
            MATCH (em)-[:ACTIVATED_THOUGHT]->(th:Thought {id: $th})
            MATCH (th)-[aw1:ASSOCIATED_WITH]->(em)
            MATCH (em)-[aw2:ASSOCIATED_WITH]->(th)
            MATCH (em)-[:LED_TO_BEHAVIOR]->(b:Behavior {id: $beh})
            MATCH (th)-[:LED_TO_BEHAVIOR]->(b)
            RETURN aw1.strength AS fwd_strength, aw2.strength AS back_strength
            """,
            {
                "exp": ids["exp"], "trig": ids["trig"], "emo": ids["emo"],
                "th":  ids["th"],  "beh":  ids["beh"],
            },
        )
        assert row is not None, "full CBT chain must be traversable"
        assert row["fwd_strength"] == pytest.approx(0.9)
        assert row["back_strength"] == pytest.approx(0.9)

    async def test_contextual_links_and_recurring_theme(
        self,
        neo4j_client: nc.Neo4jClient,
        test_namespace: dict,
        seed_topic: str,
    ) -> None:
        ids = await self._scaffold(neo4j_client, test_namespace)
        sid = test_namespace["session_id"]

        await link_experience_to_person(ids["exp"], ids["per"], sid)
        await link_to_topic(ids["exp"], "Experience", seed_topic, sid)
        await link_to_topic(ids["emo"], "Emotion",    seed_topic, sid)
        await link_user_recurring_theme(
            test_namespace["user_id"], seed_topic, sid,
        )
        # Re-running the recurring theme must bump times_reinforced.
        await link_user_recurring_theme(
            test_namespace["user_id"], seed_topic, sid,
        )

        row = await neo4j_client.execute_read_single(
            """
            MATCH (e:Experience {id: $exp})-[:INVOLVES_PERSON]->(p:Person {id: $per})
            MATCH (e)-[:RELATED_TO_TOPIC]->(t:Topic {id: $top})
            MATCH (em:Emotion {id: $emo})-[:RELATED_TO_TOPIC]->(t)
            MATCH (u:User {id: $uid})-[r:HAS_RECURRING_THEME]->(t)
            RETURN r.times_reinforced AS reps
            """,
            {
                "exp": ids["exp"], "per": ids["per"], "top": seed_topic,
                "emo": ids["emo"], "uid": test_namespace["user_id"],
            },
        )
        assert row is not None
        assert row["reps"] == 2

    async def test_link_session_to_memory_is_idempotent(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        mem_id = await write_memory(MemoryInput(
            summary="tests idempotency",
            importance=0.4,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        # Re-link twice; MERGE must collapse to a single edge.
        await link_session_to_memory(test_namespace["session_id_2"], mem_id)
        await link_session_to_memory(test_namespace["session_id_2"], mem_id)

        row = await neo4j_client.execute_read_single(
            """
            MATCH (s:Session {id: $sid})-[r:CONTAINS_MEMORY]->(m:Memory {id: $mid})
            RETURN count(r) AS c
            """,
            {"sid": test_namespace["session_id_2"], "mid": mem_id},
        )
        assert row["c"] == 1

    async def test_link_to_behavior_rejects_unknown_source_label(
        self, test_namespace: dict
    ) -> None:
        with pytest.raises(ValueError):
            await link_to_behavior(
                source_id="anything",
                source_label="User",  # not in the allow-list
                behavior_id="anything",
                session_id=test_namespace["session_id"],
            )


# ---------------------------------------------------------------------------
# 3. Supersession + invalidation
# ---------------------------------------------------------------------------

class TestSupersessionAndInvalidation:
    async def test_supersede_thought_preserves_old_and_creates_new(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        old_id = await write_thought(ThoughtInput(
            content="I'll never recover from this",
            thought_type="automatic",
            distortion="fortune_telling",
            believability=0.85,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))

        new_id = await supersede_thought(
            old_thought_id=old_id,
            new_thought=ThoughtInput(
                content="This is painful but I have bounced back before",
                thought_type="automatic",
                distortion=None,
                believability=0.55,
                user_id=test_namespace["user_id"],
                session_id=test_namespace["session_id"],
            ),
            reason="cbt_reframe",
        )
        assert new_id != old_id

        row = await neo4j_client.execute_read_single(
            """
            MATCH (new:Thought {id: $new_id})-[s:SUPERSEDES]->(old:Thought {id: $old_id})
            RETURN old.active    AS old_active,
                   new.challenged AS new_challenged,
                   new.distortion AS new_distortion,
                   s.reason        AS reason
            """,
            {"old_id": old_id, "new_id": new_id},
        )
        assert row["old_active"] is False
        assert row["new_challenged"] is True
        assert row["new_distortion"] is None
        assert row["reason"] == "cbt_reframe"

    async def test_invalidate_edge_sets_t_invalid_and_is_queryable(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        exp_id = await write_experience(ExperienceInput(
            description="Argument with a roommate",
            occurred_at=_iso(),
            extracted_at=_iso(),
            valence=-0.4,
            significance=0.3,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        trig_id = await write_trigger(TriggerInput(
            category="social",
            description="Roommate conflict",
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        await link_experience_to_trigger(exp_id, trig_id, test_namespace["session_id"])

        # Confirm the edge is initially valid.
        count = await invalidate_edge(
            "Experience", exp_id,
            "TRIGGERED_BY",
            "Trigger", trig_id,
            reason="user_correction",
        )
        assert count == 1

        row = await neo4j_client.execute_read_single(
            """
            MATCH (:Experience {id: $exp})-[r:TRIGGERED_BY]->(:Trigger {id: $trig})
            RETURN r.t_invalid           AS t_invalid,
                   r.invalidation_reason AS reason
            """,
            {"exp": exp_id, "trig": trig_id},
        )
        assert row["t_invalid"] is not None
        assert row["reason"] == "user_correction"

    async def test_invalidate_edge_rejects_unknown_edge_type(
        self, test_namespace: dict
    ) -> None:
        with pytest.raises(ValueError):
            await invalidate_edge(
                src_label="Experience",
                src_id="x",
                edge_type="DEFINITELY_NOT_REAL",
                dst_label="Trigger",
                dst_id="y",
            )


# ---------------------------------------------------------------------------
# 4. Decay + idle-flush worker
# ---------------------------------------------------------------------------

class TestDecayAndIdleFlush:
    async def test_memory_decay_halves_and_archives(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        mem_id = await write_memory(MemoryInput(
            summary="old stale memory",
            importance=0.8,
            user_id=test_namespace["user_id"],
            session_id=test_namespace["session_id"],
        ))
        # Artificially age the memory so the 60/180 day windows trip.
        await neo4j_client.execute_write(
            """
            MATCH (m:Memory {id: $id})
            SET m.last_accessed = datetime() - duration('P200D')
            """,
            {"id": mem_id},
        )

        counters = await run_memory_decay()
        assert counters["halved"]   >= 1
        assert counters["archived"] >= 1

        row = await neo4j_client.execute_read_single(
            "MATCH (m:Memory {id: $id}) RETURN m.importance AS imp, m.active AS a",
            {"id": mem_id},
        )
        assert row["imp"] < 0.8
        assert row["a"] is False

    async def test_find_idle_sessions_sees_our_session(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        # The namespace fixture created session_id_2 with last_activity 2.5h
        # ago, so it is past the default 60-minute idle threshold.
        rows = await nc.find_idle_sessions(idle_minutes=60)
        assert any(r["session_id"] == test_namespace["session_id_2"] for r in rows), (
            "session_id_2 (last_activity 2.5h ago) must appear in the idle sweep"
        )

    async def test_run_idle_memory_flush_invokes_callback(
        self, neo4j_client: nc.Neo4jClient, test_namespace: dict
    ) -> None:
        # The namespace creates a second session that is already past the
        # idle threshold. We supply a flush callback that just records the
        # call and writes a sentinel memory so mark_session_flushed stays
        # honest.
        called: list[tuple[str, str]] = []

        async def flush(user_id: str, session_id: str) -> None:
            called.append((user_id, session_id))
            await write_memory(MemoryInput(
                summary=f"auto flush for {session_id}",
                importance=0.2,
                user_id=user_id,
                session_id=session_id,
            ))

        result = await nc.run_idle_memory_flush(
            flush=flush,
            idle_minutes=60,
            batch_size=25,
        )
        assert result["flushed"] >= 1
        assert any(
            s == test_namespace["session_id_2"] for _, s in called
        ), "our idle session must have been passed to the callback"

        # Second run must NOT re-flush the same session because the CONTAINS_MEMORY
        # edge is now present (filter in find_idle_sessions).
        second = await nc.run_idle_memory_flush(flush=flush, idle_minutes=60)
        assert all(
            s != test_namespace["session_id_2"] for _, s in called[len(result):] or []
        ), "session must be skipped on the second sweep"
        assert second["flushed"] <= result["flushed"]

    async def test_idle_worker_starts_and_stops_cleanly(
        self, neo4j_client: nc.Neo4jClient
    ) -> None:
        async def noop_flush(_uid: str, _sid: str) -> None:
            return None

        task = nc.start_idle_memory_worker(
            flush=noop_flush,
            interval_seconds=3600,
            idle_minutes=60,
        )
        assert task is not None
        await asyncio.sleep(0)  # let the loop tick once
        await nc.stop_idle_memory_worker()
        assert task.cancelled() or task.done()
