// =============================================================================
// indexes.cypher
//
// Performance, fulltext, and vector indexes for all node types.
// Run AFTER constraints.cypher.
//
// Execution order:
//   1. constraints.cypher
//   2. indexes.cypher      ← this file
//   3. seed.cypher         (dev only)
//
// Index categories used in this file:
//   [LOOKUP]    -- standard b-tree / range index on single property
//   [COMPOSITE] -- multi-property index for compound filter queries
//   [FULLTEXT]  -- tokenized text search (APOC / Cypher fulltext)
//   [VECTOR]    -- ANN vector index for pgvector-style cosine search
//                  (requires Neo4j 5.11+ with vector index support)
//
// All indexes use IF NOT EXISTS for idempotency.
// =============================================================================


// =============================================================================
// SECTION 1: USER
// =============================================================================

// [LOOKUP] Fast lookup by last_active -- used in social attachment guardrail:
// session_count in 7-day window > 20 triggers nudge (Haque & Rubya, 2023).
CREATE INDEX user_last_active_idx IF NOT EXISTS
  FOR (u:User)
  ON (u.last_active);

// [LOOKUP] Onboarding gate -- checked on every session start.
CREATE INDEX user_onboarding_idx IF NOT EXISTS
  FOR (u:User)
  ON (u.onboarding_complete);


// =============================================================================
// SECTION 2: SESSION
// =============================================================================

// [LOOKUP] Recency retrieval signal (hybrid retrieval signal 1):
// always fetch last 2 session summaries for short-term context bridging.
CREATE INDEX session_started_at_idx IF NOT EXISTS
  FOR (s:Session)
  ON (s.started_at);

// [LOOKUP] Session end time -- used to detect active sessions (ended_at IS NULL).
CREATE INDEX session_ended_at_idx IF NOT EXISTS
  FOR (s:Session)
  ON (s.ended_at);

// [LOOKUP] PHQ-9 duplicate delivery guard -- checked before offering assessment
// in the same session.
CREATE INDEX session_phq9_idx IF NOT EXISTS
  FOR (s:Session)
  ON (s.phq9_administered);

// [COMPOSITE] Most common session query pattern: filter by user anchor +
// sort by recency. Used in context_fetcher.go for short-term retrieval.
CREATE INDEX session_user_recency_idx IF NOT EXISTS
  FOR (s:Session)
  ON (s.started_at, s.ended_at);


// =============================================================================
// SECTION 3: EXPERIENCE
// =============================================================================

// [LOOKUP] Temporal reasoning: "experiences from the last 3 months".
CREATE INDEX experience_occurred_at_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.occurred_at);

// [LOOKUP] Salience retrieval -- significance feeds hybrid retrieval signal 3.
CREATE INDEX experience_significance_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.significance);

// [LOOKUP] Provenance trace: all experiences from a given session.
CREATE INDEX experience_source_session_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.source_session_id);

// [VECTOR] Semantic similarity search on Experience descriptions.
// Top-5 cosine retrieval (hybrid retrieval signal 2).
// Dimension 1536 matches text-embedding-3-small output size.
// Change to 3072 if using text-embedding-3-large.
CREATE VECTOR INDEX experience_embedding_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.embedding)
  OPTIONS {
    indexConfig: {
      `vector.dimensions`:   1536,
      `vector.similarity_function`: 'cosine'
    }
  };

// [FULLTEXT] Free-text description search for entity resolution and
// deduplication review (0.65-0.85 similarity range triggers LLM merge prompt).
CREATE FULLTEXT INDEX experience_description_ft_idx IF NOT EXISTS
  FOR (e:Experience)
  ON EACH [e.description];


// =============================================================================
// SECTION 4: EMOTION
// =============================================================================

// [LOOKUP] Mood trajectory queries: emotions ordered by timestamp.
// Used in sentiment_avg computation and PHQ-9 trend graph.
CREATE INDEX emotion_timestamp_idx IF NOT EXISTS
  FOR (em:Emotion)
  ON (em.timestamp);

// [LOOKUP] Active flag filter -- archived emotions excluded from retrieval.
CREATE INDEX emotion_active_idx IF NOT EXISTS
  FOR (em:Emotion)
  ON (em.active);

// [LOOKUP] Discrete label lookup -- salience query filters by emotion_category
// matching current detected emotion (hybrid retrieval signal 3).
CREATE INDEX emotion_label_idx IF NOT EXISTS
  FOR (em:Emotion)
  ON (em.label);

// [COMPOSITE] Escalation threshold check:
// valence < -0.6 AND intensity > 0.7 → suppress reminders for 48 hours.
// Composite index covers both columns in a single scan.
CREATE INDEX emotion_escalation_idx IF NOT EXISTS
  FOR (em:Emotion)
  ON (em.valence, em.intensity);

// [COMPOSITE] Salience retrieval signal 3 filter:
// active = true AND importance_score > 0.5, ORDER BY importance_score DESC.
// Note: importance_score lives on Memory nodes, but Emotion.active +
// Emotion.label is the companion filter used in KG salience queries.
CREATE INDEX emotion_active_label_idx IF NOT EXISTS
  FOR (em:Emotion)
  ON (em.active, em.label);


// =============================================================================
// SECTION 5: TRIGGER
// =============================================================================

// [LOOKUP] Active trigger filter -- inactive triggers excluded from
// pattern detection queries.
CREATE INDEX trigger_active_idx IF NOT EXISTS
  FOR (t:Trigger)
  ON (t.active);

// [LOOKUP] Frequency ranking -- most recurring triggers surface first
// in psychologist pre-screening profile (therapist/profile_builder.go).
CREATE INDEX trigger_frequency_idx IF NOT EXISTS
  FOR (t:Trigger)
  ON (t.frequency);

// [LOOKUP] Category filter -- e.g., "academic", "social", "family".
CREATE INDEX trigger_category_idx IF NOT EXISTS
  FOR (t:Trigger)
  ON (t.category);

// [COMPOSITE] Pattern detection query: active triggers in a category,
// ranked by frequency. Used in dialogue_policy.py routing.
CREATE INDEX trigger_active_category_freq_idx IF NOT EXISTS
  FOR (t:Trigger)
  ON (t.active, t.category, t.frequency);

// [FULLTEXT] Entity resolution on trigger descriptions --
// same deduplication pipeline as Experience (cosine + fulltext).
CREATE FULLTEXT INDEX trigger_description_ft_idx IF NOT EXISTS
  FOR (t:Trigger)
  ON EACH [t.description];


// =============================================================================
// SECTION 6: THOUGHT
// =============================================================================

// [LOOKUP] Distortion type filter -- e.g., "catastrophizing", "mind_reading".
// Used in CBT reframe routing (cbt_reframe.md prompt selection).
CREATE INDEX thought_distortion_idx IF NOT EXISTS
  FOR (th:Thought)
  ON (th.distortion);

// [LOOKUP] Challenged flag -- tracks whether a thought has been cognitively
// reframed in session. Feeds progress metrics.
CREATE INDEX thought_challenged_idx IF NOT EXISTS
  FOR (th:Thought)
  ON (th.challenged);

// [LOOKUP] Timestamp for recency ordering of automatic thoughts.
CREATE INDEX thought_timestamp_idx IF NOT EXISTS
  FOR (th:Thought)
  ON (th.timestamp);

// [VECTOR] Semantic similarity on Thought content.
// Used in deduplication (threshold 0.85 = merge, 0.65 = LLM review).
CREATE VECTOR INDEX thought_embedding_idx IF NOT EXISTS
  FOR (th:Thought)
  ON (th.embedding)
  OPTIONS {
    indexConfig: {
      `vector.dimensions`:   1536,
      `vector.similarity_function`: 'cosine'
    }
  };

// [FULLTEXT] Thought content search -- supports keyword-level deduplication
// before embedding similarity check.
CREATE FULLTEXT INDEX thought_content_ft_idx IF NOT EXISTS
  FOR (th:Thought)
  ON EACH [th.content];


// =============================================================================
// SECTION 7: BEHAVIOR
// =============================================================================

// [LOOKUP] Adaptive / maladaptive classification filter.
// Used in recommendation engine to surface adaptive alternatives.
CREATE INDEX behavior_adaptive_idx IF NOT EXISTS
  FOR (b:Behavior)
  ON (b.adaptive);

// [LOOKUP] Behavior category -- e.g., "avoidance", "rumination", "exercise".
CREATE INDEX behavior_category_idx IF NOT EXISTS
  FOR (b:Behavior)
  ON (b.category);

// [LOOKUP] Frequency ranking -- high-frequency behaviors are prioritized
// in CBT behavioral activation suggestions.
CREATE INDEX behavior_frequency_idx IF NOT EXISTS
  FOR (b:Behavior)
  ON (b.frequency);

// [COMPOSITE] Recommendation engine query: adaptive behaviors in a category,
// ranked by frequency.
CREATE INDEX behavior_adaptive_category_idx IF NOT EXISTS
  FOR (b:Behavior)
  ON (b.adaptive, b.category);


// =============================================================================
// SECTION 8: PERSON
// =============================================================================

// [LOOKUP] Sentiment filter -- Person nodes with all-negative sentiment
// after 3+ sessions trigger social reconnection prompt (Haque & Rubya, 2023).
CREATE INDEX person_sentiment_idx IF NOT EXISTS
  FOR (p:Person)
  ON (p.sentiment);

// [LOOKUP] Mention count -- most mentioned people surface first in
// psychologist pre-screening profile.
CREATE INDEX person_mention_count_idx IF NOT EXISTS
  FOR (p:Person)
  ON (p.mention_count);

// [LOOKUP] Role filter -- e.g., "family", "friend", "professor".
CREATE INDEX person_role_idx IF NOT EXISTS
  FOR (p:Person)
  ON (p.role);

// [FULLTEXT] Name search -- entity resolution for "my mom" vs "mama" vs
// the user's actual mother's name. Feeds the LLM merge review prompt.
CREATE FULLTEXT INDEX person_name_ft_idx IF NOT EXISTS
  FOR (p:Person)
  ON EACH [p.name];


// =============================================================================
// SECTION 9: TOPIC
// =============================================================================

// [LOOKUP] Frequency ranking -- recurring topics surface first in
// longitudinal pattern summaries.
CREATE INDEX topic_frequency_idx IF NOT EXISTS
  FOR (top:Topic)
  ON (top.frequency);

// [LOOKUP] Average sentiment per topic -- identifies emotionally charged
// recurring themes (e.g., "family" avg_sentiment = -0.6).
CREATE INDEX topic_avg_sentiment_idx IF NOT EXISTS
  FOR (top:Topic)
  ON (top.avg_sentiment);

// [LOOKUP] Last seen -- used in topic trend queries ("topics discussed
// in the last 30 days").
CREATE INDEX topic_last_seen_idx IF NOT EXISTS
  FOR (top:Topic)
  ON (top.last_seen);

// [FULLTEXT] Name search -- deduplication of topic labels
// ("exam stress" vs "academic pressure" vs "test anxiety").
CREATE FULLTEXT INDEX topic_name_ft_idx IF NOT EXISTS
  FOR (top:Topic)
  ON EACH [top.name];


// =============================================================================
// SECTION 10: ASSESSMENT
// =============================================================================

// [LOOKUP] Re-administration interval check:
// administered_at used to determine if 14 days have elapsed since last PHQ-9.
CREATE INDEX assessment_administered_at_idx IF NOT EXISTS
  FOR (a:Assessment)
  ON (a.administered_at);

// [LOOKUP] Instrument type filter -- routes PHQ-9 vs GAD-7 vs IPIP queries.
CREATE INDEX assessment_instrument_idx IF NOT EXISTS
  FOR (a:Assessment)
  ON (a.instrument);

// [LOOKUP] Score lookup -- used in delta_from_previous calculation and
// severity trend visualization.
CREATE INDEX assessment_score_idx IF NOT EXISTS
  FOR (a:Assessment)
  ON (a.score);

// [COMPOSITE] Most common assessment query: instrument type + recency.
// "Latest PHQ-9 for this user" is executed before every session opening.
CREATE INDEX assessment_instrument_date_idx IF NOT EXISTS
  FOR (a:Assessment)
  ON (a.instrument, a.administered_at);

// [LOOKUP] Crisis gate: PHQ-9 item 9 score.
// q9_score >= 1 triggers immediate crisis protocol.
// Indexed separately because it is read on every PHQ-9 result write.
CREATE INDEX assessment_q9_score_idx IF NOT EXISTS
  FOR (a:Assessment)
  ON (a.q9_score);


// =============================================================================
// SECTION 11: MEMORY
// =============================================================================

// [LOOKUP] Active flag filter -- archived memories (active = false) are
// excluded from all three hybrid retrieval signals.
// Decay rule: active set to false after 180 days without reinforcement.
CREATE INDEX memory_active_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.active);

// [LOOKUP] Importance score -- primary filter for salience retrieval signal 3:
// importance > 0.5, ORDER BY importance DESC, LIMIT 5.
CREATE INDEX memory_importance_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.importance);

// [LOOKUP] Last accessed -- feeds memory decay function:
// importance halved after 60 days without access.
CREATE INDEX memory_last_accessed_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.last_accessed);

// [LOOKUP] Created at -- bi-temporal t_valid anchor (Graphiti model).
CREATE INDEX memory_created_at_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.created_at);

// [COMPOSITE] Core salience retrieval query:
// WHERE m.active = true AND m.importance > 0.5
// ORDER BY m.importance DESC LIMIT 5
// This composite covers both predicates in one index scan.
CREATE INDEX memory_active_importance_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.active, m.importance);

// [COMPOSITE] Decay maintenance query (nightly background job):
// WHERE m.active = true AND m.last_accessed < (now - 60 days)
CREATE INDEX memory_active_last_accessed_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.active, m.last_accessed);

// [VECTOR] Primary semantic retrieval index (hybrid retrieval signal 2).
// pgvector cosine similarity -- top-5 Memory nodes closest to current
// user message embedding.
CREATE VECTOR INDEX memory_embedding_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.embedding)
  OPTIONS {
    indexConfig: {
      `vector.dimensions`:   1536,
      `vector.similarity_function`: 'cosine'
    }
  };

// [FULLTEXT] Keyword fallback when cosine similarity is inconclusive.
// Also used in therapist profile builder to surface key memory summaries.
CREATE FULLTEXT INDEX memory_summary_ft_idx IF NOT EXISTS
  FOR (m:Memory)
  ON EACH [m.summary];
