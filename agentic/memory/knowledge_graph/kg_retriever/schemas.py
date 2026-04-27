"""
agentic/memory/kg_retriever/schemas.py

Input dataclasses for every AI-coupled writer in the kg_writer package.

Populated by kg_extractor.py from the LLM's structured JSON output,
then handed to the matching ``write_*`` function in the per-node module.

These schemas were moved into kg_retriever so the read path
(retrieval, projection, decoding) and the write path can share a
single source-of-truth shape without a circular import.

Provenance contract
-------------------
Every input carries an optional ``source_message_id``. When set, the
writer stamps it onto the user-anchor edge it produces so the deleter
and modifier modules can answer "which KG facts came from message X?"
That is what makes the user-edit and user-delete flows possible
without scanning the entire graph. Leaving the field None is supported
for back-compat with older ingestion paths but new call sites should
always populate it.

Embedding contract (DevNotes v1.3)
----------------------------------
Embeddable inputs (Memory, Experience, Thought, Trigger) carry an
optional ``embedding: list[float] | None``. The vector itself is
NEVER persisted on the Neo4j node. The writer:

  1. CREATEs the Neo4j node with ``embedding_synced = false`` and no
     embedding property at all.
  2. Hands the embedding plus the new ``neo4j_node_id`` to
     ``agentic.memory.pg_vector.upsert_*`` (via the
     ``cross_store_sync.sync_embedding_to_pgvector`` seam) which
     writes the row in pgvector.
  3. Flips ``embedding_synced`` to ``true`` via
     ``kg_modifier.update_*`` once step 2 succeeds.

If the embedding is None, the writer skips steps 2 and 3; a
background retry job (driven by ``WHERE embedding_synced = false``)
will pick the node up later. Deduplication on Experience and Thought
also routes through ``kg_vector.search`` instead of in-graph cosine.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Emotion  (CBT hot-cross-bun: feelings)
# ---------------------------------------------------------------------------

@dataclass
class EmotionInput:
    """
    Discrete emotional event. Not deduplicated -- each utterance-level
    emotion is time-stamped and preserved as its own node.
    """
    label:        str              # e.g. "anxious", "sad", "grateful"
    intensity:    float            # [0, 1]
    valence:      float            # [-1, 1]  PAD Pleasure
    arousal:      float            # [-1, 1]  PAD Arousal
    dominance:    float            # [-1, 1]  PAD Dominance
    source_text:  str              # original user utterance
    user_id:      str
    session_id:   str
    confidence:        float = 0.85
    sensitivity_level: str   = "normal"
    source_message_id: str | None = None


# ---------------------------------------------------------------------------
# Thought  (CBT hot-cross-bun: thoughts / cognitions)
# ---------------------------------------------------------------------------

@dataclass
class ThoughtInput:
    """
    An automatic thought, intermediate belief, or core belief.

    When deduplicated, the existing node's believability is averaged with
    the new value and ``challenged`` resets to false.
    """
    content:         str
    thought_type:    str              # "automatic" | "core_belief" | "intermediate"
    distortion:      str | None       # "catastrophizing" | "mind_reading" | "all_or_nothing" | "fortune_telling" | "emotional_reasoning" | "should_statements" | "labeling" | "magnification" | "personalization" | "overgeneralization" | None
    believability:   float            # [0, 1]
    user_id:         str
    session_id:      str
    embedding:       list[float] | None = None
    confidence:        float = 0.80
    sensitivity_level: str   = "normal"
    source_message_id: str | None = None


# ---------------------------------------------------------------------------
# Trigger  (CBT hot-cross-bun: antecedent)
# ---------------------------------------------------------------------------

@dataclass
class TriggerInput:
    """
    A recurring antecedent -- what set off the experience.
    Deduplicated by (user, category, description prefix) on the fast
    path; cosine similarity in pgvector on the slow path (DevNotes
    v1.3, Section 1.3 marks Trigger as embeddable for entity dedup
    across phrasings such as "exam stress" / "academic anxiety" /
    "test fear").

    ``aliases`` carries the alternative phrasings collected during
    deduplication. Per real KG schema, the canonical Trigger node
    keeps the aliases list.

    ``embedding`` is the dense vector for the description. Forwarded
    to ``trigger_embeddings`` in pgvector by the writer; never stored
    on the Neo4j node itself.
    """
    category:     str                  # "academic" | "social" | "family" | "work" | ...
    description:  str
    user_id:      str
    session_id:   str
    aliases:      list[str] | None = None
    embedding:    list[float] | None = None
    confidence:        float = 0.85
    sensitivity_level: str   = "normal"
    source_message_id: str | None = None


# ---------------------------------------------------------------------------
# Behavior  (CBT hot-cross-bun: behavior)
# ---------------------------------------------------------------------------

@dataclass
class BehaviorInput:
    """
    Observable action the user took. Marked adaptive / maladaptive so the
    recommendation engine can surface healthier alternatives for the
    maladaptive ones.
    """
    description:  str
    category:     str                  # "avoidance" | "rumination" | "exercise" | ...
    adaptive:     bool
    user_id:      str
    session_id:   str
    confidence:        float = 0.80
    sensitivity_level: str   = "normal"
    source_message_id: str | None = None


# ---------------------------------------------------------------------------
# Experience  (CBT hot-cross-bun: situation)
# ---------------------------------------------------------------------------

@dataclass
class ExperienceInput:
    """
    A concrete situation the user lived through -- the anchor of the
    CBT chain. Deduplicated via cosine similarity on ``embedding``.
    """
    description:   str
    occurred_at:   str                 # ISO datetime string
    extracted_at:  str                 # ISO datetime string
    valence:       float               # [-1, 1]
    significance:  float               # [0, 1]
    user_id:       str
    session_id:    str
    embedding:     list[float] | None = None
    confidence:        float = 0.85
    sensitivity_level: str   = "normal"
    source_message_id: str | None = None


# ---------------------------------------------------------------------------
# Person  (social graph)
# ---------------------------------------------------------------------------

@dataclass
class PersonInput:
    """
    A person mentioned by the user. MERGE-upserted by (user_id, name).
    Sentiment is a running average; mention_count increments on match.

    The User edge is HAS_RELATIONSHIP_WITH (per real KG schema, not
    KNOWS); ``relationship_quality`` is carried on that edge as a
    coarse summary of the bond. Allowed values match the schema doc:
    "supportive", "complicated", "negative", "neutral".
    """
    name:                str
    role:                str   # "parent" | "friend" | "partner" | "professor" | ...
    sentiment:           float                # [-1, 1]
    user_id:             str
    session_id:          str
    relationship_quality: str   = "neutral"   # supportive | complicated | negative | neutral
    confidence:          float  = 0.80
    source_message_id:   str | None = None


# ---------------------------------------------------------------------------
# Memory  (compressed post-session summary)
# ---------------------------------------------------------------------------

@dataclass
class MemoryInput:
    """
    Compressed session summary written once per session from
    session_end.py. Memories decay: importance halves after 60 days
    without access, active flips to false after 180 days.
    """
    summary:     str
    importance:  float                  # [0, 1]
    user_id:     str
    session_id:  str
    embedding:         list[float] | None = None
    sensitivity_level: str = "normal"
    source_message_id: str | None = None
