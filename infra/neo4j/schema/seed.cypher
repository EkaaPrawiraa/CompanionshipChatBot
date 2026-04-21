// =============================================================================
// seed.cypher
//
// Development seed data. Run AFTER constraints.cypher and indexes.cypher.
// This file is for local development and testing ONLY.
// Never run against staging or production.
//
// Creates a single realistic user journey:
//   - 1 User (Andi, ITB student)
//   - 2 Sessions
//   - 1 Assessment (PHQ-9 moderate severity)
//   - 2 Experiences, 2 Emotions, 1 Trigger, 1 Thought, 1 Behavior
//   - 1 Person, 1 Topic, 1 Memory
//   - Relationships wiring the CBT hot-cross bun chain
//
// All IDs are hardcoded UUIDs for reproducibility in tests.
// =============================================================================


// -----------------------------------------------------------------------------
// SECTION 1: CLEANUP
// Wipe any previous seed run so the file stays idempotent.
// -----------------------------------------------------------------------------

MATCH (n)
WHERE n.id IN [
  'user-seed-001',
  'sess-seed-001', 'sess-seed-002',
  'exp-seed-001',  'exp-seed-002',
  'emo-seed-001',  'emo-seed-002',
  'trig-seed-001',
  'thought-seed-001',
  'beh-seed-001',
  'person-seed-001',
  'topic-seed-001',
  'mem-seed-001',
  'assess-seed-001'
]
DETACH DELETE n;


// -----------------------------------------------------------------------------
// SECTION 2: USER
// -----------------------------------------------------------------------------

CREATE (u:User {
  id:                  'user-seed-001',
  display_name:        'Andi Pratama',
  created_at:          datetime('2026-03-01T09:00:00'),
  last_active:         datetime('2026-04-01T20:30:00'),
  session_count:       2,
  onboarding_complete: true
});


// -----------------------------------------------------------------------------
// SECTION 3: SESSIONS
// -----------------------------------------------------------------------------

CREATE (s1:Session {
  id:               'sess-seed-001',
  started_at:       datetime('2026-03-15T20:00:00'),
  ended_at:         datetime('2026-03-15T20:45:00'),
  channel:          'text',
  summary:          'Andi discussed stress about midterm exams and difficulty sleeping. Expressed feeling overwhelmed with academic workload.',
  sentiment_avg:    -0.6,
  phq9_administered: true
});

CREATE (s2:Session {
  id:               'sess-seed-002',
  started_at:       datetime('2026-04-01T20:00:00'),
  ended_at:         null,
  channel:          'voice',
  summary:          null,
  sentiment_avg:    null,
  phq9_administered: false
});


// -----------------------------------------------------------------------------
// SECTION 4: ASSESSMENT (PHQ-9, moderate severity)
// PHQ-9 score 12 = moderate depression (Kroenke et al., 2001).
// q9_score = 0 means no suicidal ideation -- no crisis trigger.
// delta_from_previous = null as this is the first assessment.
// -----------------------------------------------------------------------------

CREATE (a:Assessment {
  id:                 'assess-seed-001',
  instrument:         'PHQ-9',
  score:              12,
  severity_label:     'moderate',
  delta_from_previous: null,
  administered_at:    datetime('2026-03-15T20:05:00'),
  q9_score:           0,
  item_responses:     '{"q1":2,"q2":2,"q3":1,"q4":2,"q5":1,"q6":1,"q7":1,"q8":1,"q9":0}'
});


// -----------------------------------------------------------------------------
// SECTION 5: EXPERIENCES (CBT Situation nodes)
// -----------------------------------------------------------------------------

CREATE (exp1:Experience {
  id:               'exp-seed-001',
  description:      'Failed midterm exam in Algorithms course after studying all night.',
  occurred_at:      datetime('2026-03-14T14:00:00'),
  extracted_at:     datetime('2026-03-15T20:50:00'),
  valence:          -0.8,
  significance:     0.9,
  source_session_id: 'sess-seed-001',
  embedding:        null
});

CREATE (exp2:Experience {
  id:               'exp-seed-002',
  description:      'Argument with roommate about noise levels during study time.',
  occurred_at:      datetime('2026-03-13T22:00:00'),
  extracted_at:     datetime('2026-03-15T20:52:00'),
  valence:          -0.6,
  significance:     0.6,
  source_session_id: 'sess-seed-001',
  embedding:        null
});


// -----------------------------------------------------------------------------
// SECTION 6: EMOTIONS (PAD dimensional model)
// Mehrabian & Russell (1974): Pleasure-Arousal-Dominance.
// Low dominance (0.1) signals helplessness -- a depression marker.
// -----------------------------------------------------------------------------

CREATE (emo1:Emotion {
  id:          'emo-seed-001',
  label:       'anxiety',
  intensity:   0.85,
  valence:     -0.7,
  arousal:     0.8,
  dominance:   0.1,
  timestamp:   datetime('2026-03-15T20:15:00'),
  source_text: 'I feel like I am going to fail everything no matter how hard I try.',
  active:      true
});

CREATE (emo2:Emotion {
  id:          'emo-seed-002',
  label:       'sadness',
  intensity:   0.6,
  valence:     -0.65,
  arousal:     0.3,
  dominance:   0.2,
  timestamp:   datetime('2026-03-15T20:25:00'),
  source_text: 'I just feel so alone dealing with all this.',
  active:      true
});


// -----------------------------------------------------------------------------
// SECTION 7: TRIGGER (recurring stressor pattern)
// -----------------------------------------------------------------------------

CREATE (trig:Trigger {
  id:          'trig-seed-001',
  category:    'academic',
  description: 'High-stakes examinations and academic performance pressure.',
  frequency:   3,
  first_seen:  datetime('2026-03-15T20:50:00'),
  last_seen:   datetime('2026-03-15T20:50:00'),
  active:      true
});


// -----------------------------------------------------------------------------
// SECTION 8: THOUGHT (cognitive distortion -- catastrophizing)
// Beck (1979): Automatic thoughts driving emotional response.
// -----------------------------------------------------------------------------

CREATE (thought:Thought {
  id:           'thought-seed-001',
  content:      'I am going to fail all my courses and disappoint my family.',
  thought_type: 'automatic',
  distortion:   'catastrophizing',
  believability: 0.8,
  challenged:   false,
  timestamp:    datetime('2026-03-15T20:20:00'),
  embedding:    null
});


// -----------------------------------------------------------------------------
// SECTION 9: BEHAVIOR (maladaptive avoidance)
// -----------------------------------------------------------------------------

CREATE (beh:Behavior {
  id:          'beh-seed-001',
  description: 'Stopped attending morning lectures to avoid seeing classmates after exam result.',
  category:    'avoidance',
  adaptive:    false,
  frequency:   2,
  timestamp:   datetime('2026-03-15T20:30:00')
});


// -----------------------------------------------------------------------------
// SECTION 10: PERSON
// -----------------------------------------------------------------------------

CREATE (person:Person {
  id:              'person-seed-001',
  name:            'Pak Dosen Algoritma',
  role:            'professor',
  sentiment:       -0.4,
  mention_count:   2,
  first_mentioned: datetime('2026-03-15T20:50:00')
});


// -----------------------------------------------------------------------------
// SECTION 11: TOPIC
// -----------------------------------------------------------------------------

CREATE (topic:Topic {
  id:            'topic-seed-001',
  name:          'academic_pressure',
  frequency:     3,
  first_seen:    datetime('2026-03-15T20:50:00'),
  last_seen:     datetime('2026-03-15T20:50:00'),
  avg_sentiment: -0.7
});


// -----------------------------------------------------------------------------
// SECTION 12: MEMORY (compressed long-term summary)
// This is what gets injected into the LLM system prompt as personalized
// context on future sessions (RAG pattern).
// -----------------------------------------------------------------------------

CREATE (mem:Memory {
  id:            'mem-seed-001',
  summary:       'Andi is an ITB student experiencing significant academic anxiety. Core pattern: high-stakes exam pressure triggers catastrophizing thoughts and avoidance behavior. PHQ-9 score 12 (moderate). Primary stressor: Algorithms course. Sleep disruption and social withdrawal present.',
  importance:    0.9,
  created_at:    datetime('2026-03-15T20:55:00'),
  last_accessed: datetime('2026-03-15T20:55:00'),
  access_count:  1,
  embedding:     null,
  active:        true
});


// -----------------------------------------------------------------------------
// SECTION 13: RELATIONSHIPS
// Wire the full CBT hot-cross bun chain + structural links.
// All fact-bearing edges carry Graphiti bi-temporal properties:
//   t_valid       -- when the relationship became true (real-world time)
//   t_invalid     -- null = still valid
//   confidence    -- LLM extraction confidence [0,1]
//   source_session -- provenance
// -----------------------------------------------------------------------------

MATCH
  (u:User      {id: 'user-seed-001'}),
  (s1:Session  {id: 'sess-seed-001'}),
  (s2:Session  {id: 'sess-seed-002'}),
  (a:Assessment{id: 'assess-seed-001'}),
  (exp1:Experience {id: 'exp-seed-001'}),
  (exp2:Experience {id: 'exp-seed-002'}),
  (emo1:Emotion    {id: 'emo-seed-001'}),
  (emo2:Emotion    {id: 'emo-seed-002'}),
  (trig:Trigger    {id: 'trig-seed-001'}),
  (thought:Thought {id: 'thought-seed-001'}),
  (beh:Behavior    {id: 'beh-seed-001'}),
  (person:Person   {id: 'person-seed-001'}),
  (topic:Topic     {id: 'topic-seed-001'}),
  (mem:Memory      {id: 'mem-seed-001'})

// -- Structural links ---------------------------------------------------------
CREATE (u)-[:HAD_SESSION {
  t_valid: datetime('2026-03-15T20:00:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(s1)

CREATE (u)-[:HAD_SESSION {
  t_valid: datetime('2026-04-01T20:00:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-002'
}]->(s2)

CREATE (u)-[:HAS_MEMORY {
  t_valid: datetime('2026-03-15T20:55:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(mem)

CREATE (u)-[:HAS_RECURRING_THEME {
  t_valid: datetime('2026-03-15T20:50:00'), t_invalid: null,
  confidence: 0.95, source_session: 'sess-seed-001'
}]->(topic)

CREATE (s1)-[:PRODUCED_ASSESSMENT {
  t_valid: datetime('2026-03-15T20:05:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(a)

// -- User FELT emotions in session (session-scoped record) --------------------
CREATE (u)-[:FELT {
  t_valid: datetime('2026-03-15T20:15:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(emo1)

CREATE (u)-[:FELT {
  t_valid: datetime('2026-03-15T20:25:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(emo2)

// -- CBT hot-cross bun chain: Situation → Trigger → Emotion → Thought → Behavior
CREATE (exp1)-[:TRIGGERED_BY {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.88, source_session: 'sess-seed-001'
}]->(trig)

CREATE (exp1)-[:TRIGGERED_EMOTION {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(emo1)

CREATE (emo1)-[:ACTIVATED_THOUGHT {
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.87, source_session: 'sess-seed-001'
}]->(thought)

CREATE (thought)-[:LED_TO_BEHAVIOR {
  t_valid: datetime('2026-03-15T20:30:00'), t_invalid: null,
  confidence: 0.82, source_session: 'sess-seed-001'
}]->(beh)

CREATE (emo1)-[:LED_TO_BEHAVIOR {
  t_valid: datetime('2026-03-15T20:30:00'), t_invalid: null,
  confidence: 0.78, source_session: 'sess-seed-001'
}]->(beh)

// -- ASSOCIATED_WITH (CBT vicious cycle -- thought reinforces emotion) --------
CREATE (thought)-[:ASSOCIATED_WITH {
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(emo1)

// -- Experience → Person involvement -----------------------------------------
CREATE (exp1)-[:INVOLVES_PERSON {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.8, source_session: 'sess-seed-001'
}]->(person)

// -- Thematic categorization -------------------------------------------------
CREATE (exp1)-[:RELATED_TO_TOPIC {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.92, source_session: 'sess-seed-001'
}]->(topic)

CREATE (emo1)-[:RELATED_TO_TOPIC {
  t_valid: datetime('2026-03-15T20:15:00'), t_invalid: null,
  confidence: 0.88, source_session: 'sess-seed-001'
}]->(topic);


// -----------------------------------------------------------------------------
// SECTION 14: VERIFICATION QUERY
// Run this after seeding to confirm the graph is correctly wired.
// Expected result: 1 row summarizing the full seed graph.
// -----------------------------------------------------------------------------

MATCH (u:User {id: 'user-seed-001'})
OPTIONAL MATCH (u)-[:HAD_SESSION]->(s)
OPTIONAL MATCH (u)-[:FELT]->(emo)
OPTIONAL MATCH (u)-[:HAS_MEMORY]->(m)
OPTIONAL MATCH (u)-[:HAS_RECURRING_THEME]->(top)
RETURN
  u.display_name          AS user,
  count(DISTINCT s)       AS sessions,
  count(DISTINCT emo)     AS emotions,
  count(DISTINCT m)       AS memories,
  count(DISTINCT top)     AS topics;
