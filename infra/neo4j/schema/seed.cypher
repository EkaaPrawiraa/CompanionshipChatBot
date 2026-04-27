// =============================================================================
// seed.cypher
//
// Development seed data. Run AFTER constraints.cypher and indexes.cypher.
// This file is for local development and testing ONLY.
// Never run against staging or production.
//
// Aligns with the canonical schema in docs/architecture/kg_schema.md
// (11 node types, 18 relationship types) and matches what the Python
// writers in agentic/memory/kg_writer/ produce, including the three
// bookkeeping :User anchor edges (HAS_THOUGHT, HAS_TRIGGER, EXHIBITED)
// that the Python side uses for fast user-scoped traversal.
//
// Creates a single realistic user journey:
//   - 1 User (Andi, ITB student)
//   - 2 Sessions
//   - 1 Assessment (PHQ-9 moderate severity, no Q9 crisis flag)
//   - 2 Experiences, 2 Emotions, 1 Trigger, 2 Thoughts, 1 Behavior
//   - 1 Person, 1 Topic, 1 Memory
//   - The full CBT hot-cross bun chain
//   - A SUPERSEDES showcase: the catastrophizing Thought is reframed
//     mid-session and replaced by a new Thought with challenged=true
//
// All ids are hardcoded for reproducibility in tests.
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
  'thought-seed-001', 'thought-seed-002',
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
  preferred_language:  'id',
  session_count:       2,
  onboarding_complete: true
});


// -----------------------------------------------------------------------------
// SECTION 3: SESSIONS
// s1 is closed (with summary), s2 is currently active.
// -----------------------------------------------------------------------------

CREATE (s1:Session {
  id:                'sess-seed-001',
  started_at:        datetime('2026-03-15T20:00:00'),
  ended_at:          datetime('2026-03-15T20:45:00'),
  channel:           'text',
  summary:           'Andi discussed stress about midterm exams and difficulty sleeping. Expressed feeling overwhelmed with academic workload. Catastrophizing thought reframed during session.',
  sentiment_avg:     -0.6,
  phq9_administered: true
});

CREATE (s2:Session {
  id:                'sess-seed-002',
  started_at:        datetime('2026-04-01T20:00:00'),
  ended_at:          null,
  channel:           'voice',
  summary:           null,
  sentiment_avg:     null,
  phq9_administered: false
});


// -----------------------------------------------------------------------------
// SECTION 4: ASSESSMENT
// PHQ-9 score 12 = moderate depression (Kroenke et al., 2001).
// item_responses is the source of truth; the crisis gate reads
// item_responses['q9'] (per docs/architecture/kg_schema.md section 8).
// delta_from_previous is null because this is the user's first assessment.
// -----------------------------------------------------------------------------

CREATE (a:Assessment {
  id:                  'assess-seed-001',
  instrument:          'PHQ-9',
  score:               1,
  severity_label:      'moderate',
  delta_from_previous: null,
  administered_at:     datetime('2026-03-15T20:05:00'),
  session_id:          'sess-seed-001',
  item_responses:      '{"q1":2,"q2":2,"q3":1,"q4":2,"q5":1,"q6":1,"q7":1,"q8":1,"q9":0}'
});


// -----------------------------------------------------------------------------
// SECTION 5: EXPERIENCES (CBT Situation nodes)
// -----------------------------------------------------------------------------

CREATE (exp1:Experience {
  id:                'exp-seed-001',
  description:       'Failed midterm exam in Algorithms course after studying all night.',
  occurred_at:       datetime('2026-03-14T14:00:00'),
  extracted_at:      datetime('2026-03-15T20:50:00'),
  valence:           -0.8,
  significance:      0.9,
  source_session_id: 'sess-seed-001',
  embedding:         null,
  active:            true,
  sensitivity_level: 'normal'
});

CREATE (exp2:Experience {
  id:                'exp-seed-002',
  description:       'Argument with roommate about noise levels during study time.',
  occurred_at:       datetime('2026-03-13T22:00:00'),
  extracted_at:      datetime('2026-03-15T20:52:00'),
  valence:           -0.6,
  significance:      0.6,
  source_session_id: 'sess-seed-001',
  embedding:         null,
  active:            true,
  sensitivity_level: 'normal'
});


// -----------------------------------------------------------------------------
// SECTION 6: EMOTIONS (PAD dimensional model)
// Mehrabian & Russell (1974): Pleasure-Arousal-Dominance.
// Low dominance (0.1) signals helplessness, a depression marker.
// -----------------------------------------------------------------------------

CREATE (emo1:Emotion {
  id:                'emo-seed-001',
  label:             'anxiety',
  intensity:         0.85,
  valence:           -0.7,
  arousal:           0.8,
  dominance:         0.1,
  timestamp:         datetime('2026-03-15T20:15:00'),
  source_text:       'I feel like I am going to fail everything no matter how hard I try.',
  active:            true,
  sensitivity_level: 'normal'
});

CREATE (emo2:Emotion {
  id:                'emo-seed-002',
  label:             'sadness',
  intensity:         0.6,
  valence:           -0.65,
  arousal:           0.3,
  dominance:         0.2,
  timestamp:         datetime('2026-03-15T20:25:00'),
  source_text:       'I just feel so alone dealing with all this.',
  active:            true,
  sensitivity_level: 'normal'
});


// -----------------------------------------------------------------------------
// SECTION 7: TRIGGER
// Carries the aliases array per KG schema section 2.5; alternative
// phrasings collected during deduplication live here.
// -----------------------------------------------------------------------------

CREATE (trig:Trigger {
  id:                'trig-seed-001',
  category:          'academic',
  description:       'High-stakes examinations and academic performance pressure.',
  frequency:         3,
  first_seen:        datetime('2026-03-15T20:50:00'),
  last_seen:         datetime('2026-03-15T20:50:00'),
  active:            true,
  aliases:           ['midterm panic', 'exam stress'],
  sensitivity_level: 'normal'
});


// -----------------------------------------------------------------------------
// SECTION 8: THOUGHT -- original catastrophizing automatic thought
// Beck (1979): automatic thoughts driving the emotional response.
// active=true here; the supersession in section 13 will flip it to false.
// -----------------------------------------------------------------------------

CREATE (th1:Thought {
  id:                'thought-seed-001',
  content:           'I am going to fail all my courses and disappoint my family.',
  thought_type:      'automatic',
  distortion:        'catastrophizing',
  believability:     0.8,
  challenged:        false,
  timestamp:         datetime('2026-03-15T20:20:00'),
  embedding:         null,
  active:            true,
  sensitivity_level: 'normal'
});


// -----------------------------------------------------------------------------
// SECTION 9: REFRAMED THOUGHT (supersession demo)
// Created mid-session after the chatbot's CBT reframing prompt; the
// SUPERSEDES edge to thought-seed-001 is added in section 13.
// challenged=true, distortion=null, believability lowered.
// -----------------------------------------------------------------------------

CREATE (th2:Thought {
  id:                'thought-seed-002',
  content:           'Failing one exam is painful but the degree is not over; I can talk to the lecturer about retakes.',
  thought_type:      'automatic',
  distortion:        null,
  believability:     0.55,
  challenged:        true,
  timestamp:         datetime('2026-03-15T20:35:00'),
  embedding:         null,
  active:            true,
  sensitivity_level: 'normal'
});


// -----------------------------------------------------------------------------
// SECTION 10: BEHAVIOR (maladaptive avoidance)
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
// SECTION 11: PERSON
// owner_user_id scopes the node so two users with a same-named contact
// do not collide; matches person_kg.write_person.
// -----------------------------------------------------------------------------

CREATE (person:Person {
  id:              'person-seed-001',
  name:            'Pak Dosen Algoritma',
  role:            'professor',
  sentiment:       -0.4,
  mention_count:   2,
  first_mentioned: datetime('2026-03-15T20:50:00'),
  last_mentioned:  datetime('2026-03-15T20:50:00'),
  owner_user_id:   'user-seed-001'
});


// -----------------------------------------------------------------------------
// SECTION 12: TOPIC
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
// SECTION 13: MEMORY (compressed long-term summary)
// Injected into the LLM system prompt as personalized context on
// future sessions (RAG pattern).
// -----------------------------------------------------------------------------

CREATE (mem:Memory {
  id:                'mem-seed-001',
  summary:           'Andi is an ITB student experiencing significant academic anxiety. Core pattern: high-stakes exam pressure triggers catastrophizing thoughts and avoidance behavior. PHQ-9 score 12 (moderate). Primary stressor: Algorithms course. Sleep disruption and social withdrawal present. CBT reframe accepted in session 1.',
  importance:        0.9,
  created_at:        datetime('2026-03-15T20:55:00'),
  last_accessed:     datetime('2026-03-15T20:55:00'),
  access_count:      1,
  embedding:         null,
  active:            true,
  sensitivity_level: 'normal'
});


// =============================================================================
// SECTION 14: RELATIONSHIPS
// Wires the full schema. Every fact-bearing edge carries the Graphiti
// bi-temporal property set:
//   t_valid        -- when the relationship became true (real-world time)
//   t_invalid      -- null = still valid
//   confidence     -- LLM extraction confidence [0, 1]
//   source_session -- provenance
// =============================================================================

MATCH
  (u:User           {id: 'user-seed-001'}),
  (s1:Session       {id: 'sess-seed-001'}),
  (s2:Session       {id: 'sess-seed-002'}),
  (a:Assessment     {id: 'assess-seed-001'}),
  (exp1:Experience  {id: 'exp-seed-001'}),
  (exp2:Experience  {id: 'exp-seed-002'}),
  (emo1:Emotion     {id: 'emo-seed-001'}),
  (emo2:Emotion     {id: 'emo-seed-002'}),
  (trig:Trigger     {id: 'trig-seed-001'}),
  (th1:Thought      {id: 'thought-seed-001'}),
  (th2:Thought      {id: 'thought-seed-002'}),
  (beh:Behavior     {id: 'beh-seed-001'}),
  (person:Person    {id: 'person-seed-001'}),
  (topic:Topic      {id: 'topic-seed-001'}),
  (mem:Memory       {id: 'mem-seed-001'})

// -- 14.1 USER-LEVEL CONNECTIONS ---------------------------------------------
CREATE (u)-[:HAD_SESSION {
  t_valid: datetime('2026-03-15T20:00:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(s1)
CREATE (u)-[:HAD_SESSION {
  t_valid: datetime('2026-04-01T20:00:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-002'
}]->(s2)

CREATE (u)-[:EXPERIENCED {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(exp1)
CREATE (u)-[:EXPERIENCED {
  t_valid: datetime('2026-03-13T22:00:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(exp2)

CREATE (u)-[:FELT {
  t_valid: datetime('2026-03-15T20:15:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(emo1)
CREATE (u)-[:FELT {
  t_valid: datetime('2026-03-15T20:25:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(emo2)

CREATE (u)-[:HAS_RELATIONSHIP_WITH {
  quality: 'complicated',
  t_valid: datetime('2026-03-15T20:50:00'), t_invalid: null,
  confidence: 0.8, source_session: 'sess-seed-001'
}]->(person)

CREATE (u)-[:HAS_RECURRING_THEME {
  first_reinforced: datetime('2026-03-15T20:50:00'),
  last_reinforced:  datetime('2026-03-15T20:50:00'),
  times_reinforced: 3,
  t_valid: datetime('2026-03-15T20:50:00'), t_invalid: null,
  confidence: 0.95, source_session: 'sess-seed-001'
}]->(topic)

CREATE (u)-[:HAS_MEMORY {
  t_valid: datetime('2026-03-15T20:55:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(mem)

CREATE (u)-[:COMPLETED_ASSESSMENT {
  administered_at: datetime('2026-03-15T20:05:00'),
  t_valid: datetime('2026-03-15T20:05:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(a)

// -- 14.2 USER bookkeeping anchors (Python writers add these) ----------------
//   These are not in the design doc's 18 canonical edges but are
//   produced by thought_kg / trigger_kg / behavior_kg so the retrieval
//   layer can fan out from the user without joining via Experience or
//   Emotion. Both thoughts get HAS_THOUGHT (the old one stays linked
//   for historical replay even though it is active=false).
CREATE (u)-[:HAS_THOUGHT {
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.87, source_session: 'sess-seed-001'
}]->(th1)
CREATE (u)-[:HAS_THOUGHT {
  t_valid: datetime('2026-03-15T20:35:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(th2)
CREATE (u)-[:HAS_TRIGGER {
  t_valid: datetime('2026-03-15T20:50:00'), t_invalid: null,
  confidence: 0.88, source_session: 'sess-seed-001'
}]->(trig)
CREATE (u)-[:EXHIBITED {
  t_valid: datetime('2026-03-15T20:30:00'), t_invalid: null,
  confidence: 0.82, source_session: 'sess-seed-001'
}]->(beh)

// -- 14.3 SESSION-LEVEL CONNECTIONS ------------------------------------------
CREATE (s1)-[:HAD_EXPERIENCE {
  t_valid: datetime('2026-03-15T20:50:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(exp1)
CREATE (s1)-[:HAD_EXPERIENCE {
  t_valid: datetime('2026-03-15T20:52:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(exp2)

CREATE (s1)-[:RECORDED_EMOTION {
  t_valid: datetime('2026-03-15T20:15:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(emo1)
CREATE (s1)-[:RECORDED_EMOTION {
  t_valid: datetime('2026-03-15T20:25:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(emo2)

CREATE (s1)-[:CONTAINS_MEMORY {
  t_valid: datetime('2026-03-15T20:55:00'), t_invalid: null,
  confidence: 1.0, source_session: 'sess-seed-001'
}]->(mem)

// -- 14.4 CBT HOT-CROSS BUN CHAIN --------------------------------------------
//        Experience -> Trigger
//        Experience -> Emotion
//        Emotion    -> Thought
//        Thought   <-> Emotion  (ASSOCIATED_WITH, both directions)
//        Emotion    -> Behavior
//        Thought    -> Behavior
CREATE (exp1)-[:TRIGGERED_BY {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.88, source_session: 'sess-seed-001'
}]->(trig)

CREATE (exp1)-[:TRIGGERED_EMOTION {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.9, source_session: 'sess-seed-001'
}]->(emo1)
CREATE (exp2)-[:TRIGGERED_EMOTION {
  t_valid: datetime('2026-03-13T22:00:00'), t_invalid: null,
  confidence: 0.78, source_session: 'sess-seed-001'
}]->(emo2)

CREATE (emo1)-[:ACTIVATED_THOUGHT {
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.87, source_session: 'sess-seed-001'
}]->(th1)

// ASSOCIATED_WITH is bidirectional in the schema; Neo4j has no native
// bidirectional edge type, so we materialize both directions with the
// same strength (per relationships.link_thought_emotion_association).
CREATE (th1)-[:ASSOCIATED_WITH {
  strength: 0.9,
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(emo1)
CREATE (emo1)-[:ASSOCIATED_WITH {
  strength: 0.9,
  t_valid: datetime('2026-03-15T20:20:00'), t_invalid: null,
  confidence: 0.85, source_session: 'sess-seed-001'
}]->(th1)

CREATE (emo1)-[:LED_TO_BEHAVIOR {
  t_valid: datetime('2026-03-15T20:30:00'), t_invalid: null,
  confidence: 0.78, source_session: 'sess-seed-001'
}]->(beh)
CREATE (th1)-[:LED_TO_BEHAVIOR {
  t_valid: datetime('2026-03-15T20:30:00'), t_invalid: null,
  confidence: 0.82, source_session: 'sess-seed-001'
}]->(beh)

// -- 14.5 CONTEXTUAL LINKS ---------------------------------------------------
CREATE (exp1)-[:INVOLVES_PERSON {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.8, source_session: 'sess-seed-001'
}]->(person)

CREATE (exp1)-[:RELATED_TO_TOPIC {
  t_valid: datetime('2026-03-14T14:00:00'), t_invalid: null,
  confidence: 0.92, source_session: 'sess-seed-001'
}]->(topic)
CREATE (exp2)-[:RELATED_TO_TOPIC {
  t_valid: datetime('2026-03-13T22:00:00'), t_invalid: null,
  confidence: 0.78, source_session: 'sess-seed-001'
}]->(topic)
CREATE (emo1)-[:RELATED_TO_TOPIC {
  t_valid: datetime('2026-03-15T20:15:00'), t_invalid: null,
  confidence: 0.88, source_session: 'sess-seed-001'
}]->(topic)

// -- 14.6 SUPERSESSION (CBT reframe demonstration) ---------------------------
//   The reframed thought (th2) supersedes the catastrophizing one (th1).
//   th1 stays in the graph for historical replay but is marked inactive.
//   th2 carries the SUPERSEDES edge with reason and timestamp.
CREATE (th2)-[:SUPERSEDES {
  at:     datetime('2026-03-15T20:35:00'),
  reason: 'cbt_reframe',
  source_session: 'sess-seed-001'
}]->(th1)
SET th1.active = false;


// =============================================================================
// SECTION 15: VERIFICATION QUERY
// Run after seeding to confirm the graph is correctly wired.
// Expected:
//   sessions=2 experiences=2 emotions=2 thoughts=2
//   memories=1 topics=1 people=1 assessments=1
//   active_thoughts=1   (th1 was superseded)
//   superseded_count=1
// =============================================================================

MATCH (u:User {id: 'user-seed-001'})
OPTIONAL MATCH (u)-[:HAD_SESSION]->(s)
OPTIONAL MATCH (u)-[:EXPERIENCED]->(e)
OPTIONAL MATCH (u)-[:FELT]->(em)
OPTIONAL MATCH (u)-[:HAS_THOUGHT]->(th)
OPTIONAL MATCH (u)-[:HAS_THOUGHT]->(thAct) WHERE thAct.active = true
OPTIONAL MATCH (u)-[:HAS_MEMORY]->(m)
OPTIONAL MATCH (u)-[:HAS_RECURRING_THEME]->(top)
OPTIONAL MATCH (u)-[:HAS_RELATIONSHIP_WITH]->(p)
OPTIONAL MATCH (u)-[:COMPLETED_ASSESSMENT]->(a)
OPTIONAL MATCH (newTh:Thought)-[:SUPERSEDES]->(:Thought)
RETURN
  u.display_name              AS user,
  count(DISTINCT s)           AS sessions,
  count(DISTINCT e)           AS experiences,
  count(DISTINCT em)          AS emotions,
  count(DISTINCT th)          AS thoughts,
  count(DISTINCT thAct)       AS active_thoughts,
  count(DISTINCT m)           AS memories,
  count(DISTINCT top)         AS topics,
  count(DISTINCT p)           AS people,
  count(DISTINCT a)           AS assessments,
  count(DISTINCT newTh)       AS superseded_count;
