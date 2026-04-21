// =============================================================================
// constraints.cypher
//
// Uniqueness and existence constraints for all 11 node types.
// Run this file first, before indexes.cypher.
//
// Execution order:
//   1. constraints.cypher   ← this file
//   2. indexes.cypher
//   3. seed.cypher          (dev only)
//
// Neo4j 5.x syntax. All constraints use IF NOT EXISTS so the file
// is safe to re-run (idempotent).
// =============================================================================


// -----------------------------------------------------------------------------
// SECTION 1: USER
// Central anchor node. Every piece of personal data traces back here.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT user_id_unique IF NOT EXISTS
  FOR (u:User)
  REQUIRE u.id IS UNIQUE;

CREATE CONSTRAINT user_id_not_null IF NOT EXISTS
  FOR (u:User)
  REQUIRE u.id IS NOT NULL;

CREATE CONSTRAINT user_display_name_not_null IF NOT EXISTS
  FOR (u:User)
  REQUIRE u.display_name IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 2: SESSION
// Anchors a single conversation. All nodes extracted during a session
// carry source_session_id pointing back here.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT session_id_unique IF NOT EXISTS
  FOR (s:Session)
  REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT session_id_not_null IF NOT EXISTS
  FOR (s:Session)
  REQUIRE s.id IS NOT NULL;

CREATE CONSTRAINT session_started_at_not_null IF NOT EXISTS
  FOR (s:Session)
  REQUIRE s.started_at IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 3: EXPERIENCE
// Life events / situations. Maps to CBT "Situation" in the hot-cross bun model.
// source_session_id is enforced so every Experience is traceable to a session.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT experience_id_unique IF NOT EXISTS
  FOR (e:Experience)
  REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT experience_id_not_null IF NOT EXISTS
  FOR (e:Experience)
  REQUIRE e.id IS NOT NULL;

CREATE CONSTRAINT experience_source_session_not_null IF NOT EXISTS
  FOR (e:Experience)
  REQUIRE e.source_session_id IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 4: EMOTION
// PAD-dimensional emotional state (Pleasure-Arousal-Dominance).
// Feeds escalation logic: valence < -0.6 AND intensity > 0.7 triggers
// reminder suppression (Haque & Rubya, 2023).
// -----------------------------------------------------------------------------

CREATE CONSTRAINT emotion_id_unique IF NOT EXISTS
  FOR (em:Emotion)
  REQUIRE em.id IS UNIQUE;

CREATE CONSTRAINT emotion_id_not_null IF NOT EXISTS
  FOR (em:Emotion)
  REQUIRE em.id IS NOT NULL;

CREATE CONSTRAINT emotion_label_not_null IF NOT EXISTS
  FOR (em:Emotion)
  REQUIRE em.label IS NOT NULL;

CREATE CONSTRAINT emotion_timestamp_not_null IF NOT EXISTS
  FOR (em:Emotion)
  REQUIRE em.timestamp IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 5: TRIGGER
// Recurring stressor patterns. Maps to "Activating Event" in CBT / Ellis ABCDE.
// category and description are enforced to keep retrieval meaningful.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT trigger_id_unique IF NOT EXISTS
  FOR (t:Trigger)
  REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT trigger_id_not_null IF NOT EXISTS
  FOR (t:Trigger)
  REQUIRE t.id IS NOT NULL;

CREATE CONSTRAINT trigger_category_not_null IF NOT EXISTS
  FOR (t:Trigger)
  REQUIRE t.category IS NOT NULL;

CREATE CONSTRAINT trigger_description_not_null IF NOT EXISTS
  FOR (t:Trigger)
  REQUIRE t.description IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 6: THOUGHT
// Automatic thoughts and cognitive distortions (Beck, 1979).
// Core CBT node. content is enforced because it is the extraction target
// and the basis for semantic deduplication.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT thought_id_unique IF NOT EXISTS
  FOR (th:Thought)
  REQUIRE th.id IS UNIQUE;

CREATE CONSTRAINT thought_id_not_null IF NOT EXISTS
  FOR (th:Thought)
  REQUIRE th.id IS NOT NULL;

CREATE CONSTRAINT thought_content_not_null IF NOT EXISTS
  FOR (th:Thought)
  REQUIRE th.content IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 7: BEHAVIOR
// Coping behaviors. Completes the CBT hot-cross bun model alongside
// Experience, Emotion, and Thought.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT behavior_id_unique IF NOT EXISTS
  FOR (b:Behavior)
  REQUIRE b.id IS UNIQUE;

CREATE CONSTRAINT behavior_id_not_null IF NOT EXISTS
  FOR (b:Behavior)
  REQUIRE b.id IS NOT NULL;

CREATE CONSTRAINT behavior_description_not_null IF NOT EXISTS
  FOR (b:Behavior)
  REQUIRE b.description IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 8: PERSON
// People in the user's life. Tracks relationship sentiment across sessions.
// name is enforced as the deduplication anchor for entity resolution.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT person_id_unique IF NOT EXISTS
  FOR (p:Person)
  REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT person_id_not_null IF NOT EXISTS
  FOR (p:Person)
  REQUIRE p.id IS NOT NULL;

CREATE CONSTRAINT person_name_not_null IF NOT EXISTS
  FOR (p:Person)
  REQUIRE p.name IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 9: TOPIC
// Recurring conversation themes. Longitudinal pattern linking via
// HAS_RECURRING_THEME on User. name is the deduplication key.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
  FOR (top:Topic)
  REQUIRE top.id IS UNIQUE;

CREATE CONSTRAINT topic_id_not_null IF NOT EXISTS
  FOR (top:Topic)
  REQUIRE top.id IS NOT NULL;

CREATE CONSTRAINT topic_name_not_null IF NOT EXISTS
  FOR (top:Topic)
  REQUIRE top.name IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 10: ASSESSMENT
// PHQ-9, GAD-7, IPIP scoring. PHQ-9 item 9 >= 1 is the primary crisis signal
// (Kroenke et al., 2001). instrument type is enforced for routing logic.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT assessment_id_unique IF NOT EXISTS
  FOR (a:Assessment)
  REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT assessment_id_not_null IF NOT EXISTS
  FOR (a:Assessment)
  REQUIRE a.id IS NOT NULL;

CREATE CONSTRAINT assessment_instrument_not_null IF NOT EXISTS
  FOR (a:Assessment)
  REQUIRE a.instrument IS NOT NULL;

CREATE CONSTRAINT assessment_administered_at_not_null IF NOT EXISTS
  FOR (a:Assessment)
  REQUIRE a.administered_at IS NOT NULL;


// -----------------------------------------------------------------------------
// SECTION 11: MEMORY
// LLM-compressed long-term summaries (RAG pattern). active flag enforced
// so decay logic can safely exclude archived nodes from retrieval queries.
// importance is enforced for salience-ranked hybrid retrieval (signal 3).
// -----------------------------------------------------------------------------

CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT memory_id_not_null IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.id IS NOT NULL;

CREATE CONSTRAINT memory_summary_not_null IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.summary IS NOT NULL;

CREATE CONSTRAINT memory_importance_not_null IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.importance IS NOT NULL;

CREATE CONSTRAINT memory_active_not_null IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.active IS NOT NULL;
