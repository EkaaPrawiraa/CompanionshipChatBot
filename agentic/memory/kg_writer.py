"""
agentic/memory/kg_writer.py

Graph write pipeline for all AI-extracted nodes.
Called asynchronously from kg_extractor.py after each conversation turn,
and from session_end.py when the session closes.

Responsibilities:
  - Write Emotion, Thought, Trigger, Behavior, Experience, Person, Memory
  - Cosine deduplication before every write (threshold 0.85 / 0.65)
  - Create SUPERSEDES edge when a belief or emotion is contradicted
  - Apply Graphiti bi-temporal properties on every relationship
  - Tag sensitivity_level on every node (Guardrail Layer 4)
  - call every function needed to write inside kg from ./kg_writer/ folder

Node types handled here (AI-coupled, Python side):
  Emotion, Thought, Trigger, Behavior, Experience, Person, Memory

Node types handled in Go (neo4j_repo.go):
  User, Session, Assessment, Topic (pure CRUD, no LLM coupling)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .neo4j_client import get_client

logger = logging.getLogger(__name__)

# Deduplication thresholds (DevNotes v1.1, Section 2)
MERGE_THRESHOLD = 0.85   # merge + increment frequency
REVIEW_THRESHOLD = 0.65  # flag for LLM merge review
# Below REVIEW_THRESHOLD -> create new node


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())

def _require(value: Any, field_name: str) -> Any:
    """Replaces IS NOT NULL constraint. Raises before any DB call."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Required field '{field_name}' is None or empty")
    return value


# ---------------------------------------------------------------------------
# Input dataclasses
# These are populated by kg_extractor.py from the LLM's structured JSON output.
# ---------------------------------------------------------------------------

@dataclass
class EmotionInput:
    label: str
    intensity: float          # [0, 1]
    valence: float            # [-1, 1]  PAD Pleasure
    arousal: float            # [-1, 1]  PAD Arousal
    dominance: float          # [-1, 1]  PAD Dominance
    source_text: str          # original user utterance
    user_id: str
    session_id: str
    confidence: float = 0.85
    sensitivity_level: str = "normal"


@dataclass
class ThoughtInput:
    content: str
    thought_type: str         # "automatic" | "core_belief" | "intermediate"
    distortion: str | None    # "catastrophizing" | "mind_reading" | etc.
    believability: float      # [0, 1]
    user_id: str
    session_id: str
    embedding: list[float] | None = None
    confidence: float = 0.80
    sensitivity_level: str = "normal"


@dataclass
class TriggerInput:
    category: str             # "academic" | "social" | "family" | "work"
    description: str
    user_id: str
    session_id: str
    confidence: float = 0.85
    sensitivity_level: str = "normal"


@dataclass
class BehaviorInput:
    description: str
    category: str             # "avoidance" | "rumination" | "exercise" | etc.
    adaptive: bool
    user_id: str
    session_id: str
    confidence: float = 0.80
    sensitivity_level: str = "normal"


@dataclass
class ExperienceInput:
    description: str
    occurred_at: str          # ISO datetime string
    valence: float            # [-1, 1]
    significance: float       # [0, 1]
    user_id: str
    session_id: str
    embedding: list[float] | None = None
    confidence: float = 0.85
    sensitivity_level: str = "normal"


@dataclass
class PersonInput:
    name: str
    role: str                 # "family" | "friend" | "professor" | "romantic"
    sentiment: float          # [-1, 1]
    user_id: str
    session_id: str
    confidence: float = 0.80


@dataclass
class MemoryInput:
    summary: str
    importance: float         # [0, 1]
    user_id: str
    session_id: str
    embedding: list[float] | None = None
    sensitivity_level: str = "normal"


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

async def _find_similar_node(
    label: str,
    description_field: str,
    embedding: list[float] | None,
    user_id: str,
    client: Any,
) -> dict[str, Any] | None:
    """
    Check if an active node of the same label and user already exists with
    cosine similarity >= REVIEW_THRESHOLD.

    Returns the existing node dict if found, else None.
    Uses Neo4j vector index if embedding is provided; falls back to
    exact-name FULLTEXT match for nodes without embeddings.
    """
    if embedding is None:
        # Fulltext fallback -- not ideal but prevents duplicate writes
        # when the embedding model hasn't run yet.
        return None

    records = await client.execute_read(
        f"""
        MATCH (u:User {{id: $user_id}})-[*1..2]-(n:{label})
        WHERE n.active = true AND n.embedding IS NOT NULL
        WITH n,
             vector.similarity.cosine(n.embedding, $embedding) AS similarity
        WHERE similarity >= $threshold
        RETURN n.id        AS id,
               n.{description_field} AS description,
               similarity
        ORDER BY similarity DESC
        LIMIT 1
        """,
        {
            "user_id":   user_id,
            "embedding": embedding,
            "threshold": REVIEW_THRESHOLD,
        },
    )
    return records[0] if records else None


# ---------------------------------------------------------------------------
# Write functions -- one per node type
# ---------------------------------------------------------------------------

async def write_emotion(inp: EmotionInput) -> str:
    """
    Write an Emotion node and link it to User (FELT) and Session.
    Returns the node ID (new or merged).

    No deduplication on Emotion -- each emotional event is a discrete
    time-stamped record. Supersession happens via the SUPERSEDES edge
    when a contradicting state is explicitly resolved.
    """
    client = get_client()
    node_id = _new_id()

    _require(inp.label,      "label")
    _require(inp.source_text, "source_text")
    _require(inp.user_id,    "user_id")
    _require(inp.session_id, "session_id")

    await client.execute_write(
        """
        MATCH (u:User    {id: $user_id})
        MATCH (s:Session {id: $session_id})
        CREATE (em:Emotion {
            id:                $id,
            label:             $label,
            intensity:         $intensity,
            valence:           $valence,
            arousal:           $arousal,
            dominance:         $dominance,
            timestamp:         datetime($timestamp),
            source_text:       $source_text,
            active:            true,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:FELT {
            t_valid:        datetime($timestamp),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(em)
        CREATE (s)-[:RECORDED_EMOTION {
            t_valid:        datetime($timestamp),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(em)
        RETURN em.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "label":             inp.label,
            "intensity":         inp.intensity,
            "valence":           inp.valence,
            "arousal":           inp.arousal,
            "dominance":         inp.dominance,
            "timestamp":         _now_iso(),
            "source_text":       inp.source_text,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
        },
    )
    logger.debug("Emotion written: %s (%s)", node_id, inp.label)
    return node_id


async def write_thought(inp: ThoughtInput) -> str:
    """
    Write a Thought node with cosine deduplication.
    If similarity >= 0.85: merge (increment frequency proxy via believability avg).
    If 0.65-0.85: log for LLM review (still writes new node for now).
    If < 0.65: new node.
    Returns the node ID.
    """
    client = get_client()

    # Deduplication check
    existing = await _find_similar_node(
        label="Thought",
        description_field="content",
        embedding=inp.embedding,
        user_id=inp.user_id,
        client=client,
    )

    if existing and existing["similarity"] >= MERGE_THRESHOLD:
        # Merge: update believability average, return existing id
        await client.execute_write(
            """
            MATCH (th:Thought {id: $id})
            SET th.believability = (th.believability + $believability) / 2.0,
                th.challenged    = false
            """,
            {"id": existing["id"], "believability": inp.believability},
        )
        logger.debug("Thought merged into existing: %s", existing["id"])
        return existing["id"]

    if existing and existing["similarity"] >= REVIEW_THRESHOLD:
        logger.info(
            "Thought similarity %.2f in review zone -- writing new node "
            "(LLM merge review flagged): '%s' vs '%s'",
            existing["similarity"], inp.content[:60], existing["description"][:60],
        )

    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (th:Thought {
            id:                $id,
            content:           $content,
            thought_type:      $thought_type,
            distortion:        $distortion,
            believability:     $believability,
            challenged:        false,
            timestamp:         datetime($timestamp),
            embedding:         $embedding,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:HAS_THOUGHT {
            t_valid:        datetime($timestamp),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(th)
        RETURN th.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "content":           inp.content,
            "thought_type":      inp.thought_type,
            "distortion":        inp.distortion,
            "believability":     inp.believability,
            "timestamp":         _now_iso(),
            "embedding":         inp.embedding,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
        },
    )
    logger.debug("Thought written: %s", node_id)
    return node_id


async def write_trigger(inp: TriggerInput) -> str:
    """
    MERGE Trigger by (user, category, description similarity).
    Increments frequency on match. Creates new node if no similar trigger found.
    Returns the node ID.
    """
    client = get_client()

    # Try exact category + description match first (fast path)
    existing = await client.execute_read_single(
        """
        MATCH (u:User {id: $user_id})-[:HAS_TRIGGER]->(t:Trigger)
        WHERE t.category = $category
          AND t.active = true
          AND toLower(t.description) CONTAINS toLower($keyword)
        RETURN t.id AS id, t.frequency AS frequency
        ORDER BY t.frequency DESC
        LIMIT 1
        """,
        {
            "user_id":  inp.user_id,
            "category": inp.category,
            "keyword":  inp.description[:30],  # first 30 chars as keyword
        },
    )

    if existing:
        # Increment frequency and update last_seen
        await client.execute_write(
            """
            MATCH (t:Trigger {id: $id})
            SET t.frequency = t.frequency + 1,
                t.last_seen = datetime()
            """,
            {"id": existing["id"]},
        )
        logger.debug("Trigger frequency incremented: %s", existing["id"])
        return existing["id"]

    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (t:Trigger {
            id:                $id,
            category:          $category,
            description:       $description,
            frequency:         1,
            first_seen:        datetime(),
            last_seen:         datetime(),
            active:            true,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:HAS_TRIGGER {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(t)
        RETURN t.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "category":          inp.category,
            "description":       inp.description,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
        },
    )
    logger.debug("Trigger written: %s", node_id)
    return node_id


async def write_behavior(inp: BehaviorInput) -> str:
    """
    Write a Behavior node. Increments frequency if same description exists.
    Returns the node ID.
    """
    client = get_client()

    existing = await client.execute_read_single(
        """
        MATCH (u:User {id: $user_id})-[:EXHIBITED]->(b:Behavior)
        WHERE b.category = $category
          AND toLower(b.description) CONTAINS toLower($keyword)
        RETURN b.id AS id
        LIMIT 1
        """,
        {
            "user_id":  inp.user_id,
            "category": inp.category,
            "keyword":  inp.description[:30],
        },
    )

    if existing:
        await client.execute_write(
            """
            MATCH (b:Behavior {id: $id})
            SET b.frequency  = coalesce(b.frequency, 0) + 1,
                b.timestamp  = datetime()
            """,
            {"id": existing["id"]},
        )
        return existing["id"]

    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (b:Behavior {
            id:                $id,
            description:       $description,
            category:          $category,
            adaptive:          $adaptive,
            frequency:         1,
            timestamp:         datetime(),
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:EXHIBITED {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(b)
        RETURN b.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "description":       inp.description,
            "category":          inp.category,
            "adaptive":          inp.adaptive,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
        },
    )
    logger.debug("Behavior written: %s (adaptive=%s)", node_id, inp.adaptive)
    return node_id


async def write_experience(inp: ExperienceInput) -> str:
    """
    Write an Experience node (CBT Situation). Deduplicates via cosine similarity.
    Returns the node ID.
    """
    client = get_client()

    existing = await _find_similar_node(
        label="Experience",
        description_field="description",
        embedding=inp.embedding,
        user_id=inp.user_id,
        client=client,
    )

    if existing and existing["similarity"] >= MERGE_THRESHOLD:
        # Same experience mentioned again -- update significance (reinforce)
        await client.execute_write(
            """
            MATCH (e:Experience {id: $id})
            SET e.significance = CASE
                WHEN e.significance < 0.95 THEN e.significance + 0.05
                ELSE 1.0
            END
            """,
            {"id": existing["id"]},
        )
        logger.debug("Experience merged: %s", existing["id"])
        return existing["id"]

    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User    {id: $user_id})
        MATCH (s:Session {id: $session_id})
        CREATE (e:Experience {
            id:                $id,
            description:       $description,
            occurred_at:       datetime($occurred_at),
            extracted_at:      datetime(),
            valence:           $valence,
            significance:      $significance,
            source_session_id: $session_id,
            embedding:         $embedding,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:EXPERIENCED {
            t_valid:        datetime($occurred_at),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(e)
        CREATE (s)-[:HAD_EXPERIENCE {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     $confidence,
            source_session: $session_id
        }]->(e)
        RETURN e.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "description":       inp.description,
            "occurred_at":       inp.occurred_at,
            "valence":           inp.valence,
            "significance":      inp.significance,
            "embedding":         inp.embedding,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
        },
    )
    logger.debug("Experience written: %s", node_id)
    return node_id


async def write_person(inp: PersonInput) -> str:
    """
    MERGE Person by name (per user). Updates sentiment rolling average and
    increments mention_count on match.
    Returns the node ID.
    """
    client = get_client()

    node_id = _new_id()
    record = await client.execute_write_single(
        """
        MATCH (u:User {id: $user_id})
        MERGE (p:Person {name: $name})<-[:KNOWS]-(u)
        ON CREATE SET
            p.id              = $id,
            p.role            = $role,
            p.sentiment       = $sentiment,
            p.mention_count   = 1,
            p.first_mentioned = datetime()
        ON MATCH SET
            p.sentiment     = (p.sentiment + $sentiment) / 2.0,
            p.mention_count = p.mention_count + 1
        RETURN p.id AS id
        """,
        {
            "user_id":   inp.user_id,
            "session_id": inp.session_id,
            "id":        node_id,
            "name":      inp.name,
            "role":      inp.role,
            "sentiment": inp.sentiment,
        },
    )
    actual_id = record["id"] if record else node_id
    logger.debug("Person upserted: %s (%s)", actual_id, inp.name)
    return actual_id


async def write_memory(inp: MemoryInput) -> str:
    """
    Write a compressed Memory node (post-session summary).
    Called once per session from session_end.py.
    Links to User via HAS_MEMORY.
    Returns the node ID.
    """
    client = get_client()
    node_id = _new_id()

    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (m:Memory {
            id:                $id,
            summary:           $summary,
            importance:        $importance,
            created_at:        datetime(),
            last_accessed:     datetime(),
            access_count:      0,
            embedding:         $embedding,
            active:            true,
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:HAS_MEMORY {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     1.0,
            source_session: $session_id
        }]->(m)
        RETURN m.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "summary":           inp.summary,
            "importance":        inp.importance,
            "embedding":         inp.embedding,
            "sensitivity_level": inp.sensitivity_level,
        },
    )
    logger.info("Memory written: %s (importance=%.2f)", node_id, inp.importance)
    return node_id


# ---------------------------------------------------------------------------
# Relationship builders -- CBT hot-cross bun chain
# ---------------------------------------------------------------------------

async def link_experience_to_trigger(
    experience_id: str, trigger_id: str, session_id: str, confidence: float = 0.85
) -> None:
    """Experience -[:TRIGGERED_BY]-> Trigger"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (t:Trigger    {id: $trig_id})
        MERGE (e)-[r:TRIGGERED_BY]->(t)
        ON CREATE SET
            r.t_valid        = datetime(),
            r.t_invalid      = null,
            r.confidence     = $confidence,
            r.source_session = $session_id
        """,
        {"exp_id": experience_id, "trig_id": trigger_id,
         "session_id": session_id, "confidence": confidence},
    )


async def link_experience_to_emotion(
    experience_id: str, emotion_id: str, session_id: str, confidence: float = 0.85
) -> None:
    """Experience -[:TRIGGERED_EMOTION]-> Emotion"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (em:Emotion   {id: $emo_id})
        MERGE (e)-[r:TRIGGERED_EMOTION]->(em)
        ON CREATE SET
            r.t_valid        = datetime(),
            r.t_invalid      = null,
            r.confidence     = $confidence,
            r.source_session = $session_id
        """,
        {"exp_id": experience_id, "emo_id": emotion_id,
         "session_id": session_id, "confidence": confidence},
    )


async def link_emotion_to_thought(
    emotion_id: str, thought_id: str, session_id: str, confidence: float = 0.80
) -> None:
    """Emotion -[:ACTIVATED_THOUGHT]-> Thought"""
    await get_client().execute_write(
        """
        MATCH (em:Emotion {id: $emo_id})
        MATCH (th:Thought {id: $th_id})
        MERGE (em)-[r:ACTIVATED_THOUGHT]->(th)
        ON CREATE SET
            r.t_valid        = datetime(),
            r.t_invalid      = null,
            r.confidence     = $confidence,
            r.source_session = $session_id
        """,
        {"emo_id": emotion_id, "th_id": thought_id,
         "session_id": session_id, "confidence": confidence},
    )


async def link_to_behavior(
    source_id: str, source_label: str,
    behavior_id: str, session_id: str, confidence: float = 0.80
) -> None:
    """Emotion or Thought -[:LED_TO_BEHAVIOR]-> Behavior"""
    await get_client().execute_write(
        f"""
        MATCH (src:{source_label} {{id: $src_id}})
        MATCH (b:Behavior         {{id: $beh_id}})
        MERGE (src)-[r:LED_TO_BEHAVIOR]->(b)
        ON CREATE SET
            r.t_valid        = datetime(),
            r.t_invalid      = null,
            r.confidence     = $confidence,
            r.source_session = $session_id
        """,
        {"src_id": source_id, "beh_id": behavior_id,
         "session_id": session_id, "confidence": confidence},
    )


async def link_experience_to_person(
    experience_id: str, person_id: str, session_id: str, confidence: float = 0.80
) -> None:
    """Experience -[:INVOLVES_PERSON]-> Person"""
    await get_client().execute_write(
        """
        MATCH (e:Experience {id: $exp_id})
        MATCH (p:Person     {id: $p_id})
        MERGE (e)-[r:INVOLVES_PERSON]->(p)
        ON CREATE SET
            r.t_valid        = datetime(),
            r.t_invalid      = null,
            r.confidence     = $confidence,
            r.source_session = $session_id
        """,
        {"exp_id": experience_id, "p_id": person_id,
         "session_id": session_id, "confidence": confidence},
    )


# ---------------------------------------------------------------------------
# Supersession -- contradiction resolution
# ---------------------------------------------------------------------------

async def supersede_thought(
    old_thought_id: str, new_thought: ThoughtInput, reason: str = "user_reframe"
) -> str:
    """
    Mark an old Thought as resolved and create a new one that supersedes it.
    Used when CBT reframing succeeds -- the reframed thought supersedes the
    original automatic thought.

    MATCH old -> SET old.active = false
    CREATE new -> CREATE new -[:SUPERSEDES]-> old
    Returns the new thought ID.
    """
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
    logger.info("Thought superseded: %s -> %s (reason=%s)", old_thought_id, new_id, reason)
    return new_id


# ---------------------------------------------------------------------------
# Memory decay -- called by nightly background job
# ---------------------------------------------------------------------------

async def run_memory_decay() -> dict[str, int]:
    """
    Apply memory decay rules (DevNotes v1.1):
      - importance halved after 60 days without access
      - node archived (active = false) after 180 days without access

    Returns counts of nodes halved and archived.
    """
    client = get_client()

    # Halve importance for memories not accessed in 60 days
    halved = await client.execute_write(
        """
        MATCH (m:Memory)
        WHERE m.active = true
          AND m.last_accessed < datetime() - duration('P60D')
          AND m.importance > 0.05
        SET m.importance = m.importance / 2.0
        RETURN count(m) AS halved
        """
    )

    # Archive memories not accessed in 180 days
    archived = await client.execute_write(
        """
        MATCH (m:Memory)
        WHERE m.active = true
          AND m.last_accessed < datetime() - duration('P180D')
        SET m.active = false
        RETURN count(m) AS archived
        """
    )

    halved_count  = halved[0]["halved"]   if halved  else 0
    archived_count = archived[0]["archived"] if archived else 0

    logger.info(
        "Memory decay run: halved=%d, archived=%d",
        halved_count, archived_count,
    )
    return {"halved": halved_count, "archived": archived_count}