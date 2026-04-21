// =============================================================================
// schema/verify.cypher
//
// Schema verification suite. Run this after applying constraints, indexes,
// migrations, and seed data to confirm everything is correctly in place.
//
// How to run:
//   Option A -- Neo4j Browser: paste each block one at a time (separated by ===)
//   Option B -- cypher-shell:
//     cypher-shell -a bolt://localhost:7687 -u neo4j -p devpassword \
//       --file infra/neo4j/schema/verify.cypher
//
// Expected outcomes are documented inline for every check.
// A passing schema will produce no FAIL rows anywhere.
// =============================================================================


// =============================================================================
// CHECK 1: Constraints
// Verifies that all 11 node types have their uniqueness constraints applied.
// Expected: 11 rows, all with status = 'PRESENT'
// =============================================================================

SHOW CONSTRAINTS
YIELD name, type, labelsOrTypes, properties
WHERE type = 'UNIQUENESS'
RETURN
  labelsOrTypes[0]  AS node_type,
  properties[0]     AS constrained_property,
  'PRESENT'         AS status
ORDER BY node_type;

// --- Minimum expected rows (uniqueness constraints only):
// User           id
// Session        id
// Experience     id
// Emotion        id
// Trigger        id
// Thought        id
// Behavior       id
// Person         id
// Topic          id
// Assessment     id
// Memory         id


// =============================================================================
// CHECK 2: Indexes summary
// Verifies that indexes were created and are online (not in POPULATING state).
// Expected: All rows should show state = 'ONLINE'
// Any row with state = 'POPULATING' means the index is still building -- wait.
// Any row with state = 'FAILED' means something went wrong.
// =============================================================================

SHOW INDEXES
YIELD name, type, state, labelsOrTypes, properties
WHERE type IN ['RANGE', 'FULLTEXT', 'VECTOR']
RETURN
  name,
  type,
  labelsOrTypes[0]  AS node_type,
  properties        AS indexed_properties,
  state,
  CASE state
    WHEN 'ONLINE'      THEN 'OK'
    WHEN 'POPULATING'  THEN 'WAIT - still building'
    ELSE                    'FAIL - check Neo4j logs'
  END AS health
ORDER BY node_type, type;


// =============================================================================
// CHECK 3: Vector indexes specifically
// Vector indexes are the most critical for semantic retrieval.
// Expected: 3 rows (Memory, Experience, Thought) all ONLINE with dimensions 1536
// =============================================================================

SHOW INDEXES
YIELD name, type, state, labelsOrTypes, properties, options
WHERE type = 'VECTOR'
RETURN
  labelsOrTypes[0]                               AS node_type,
  properties[0]                                  AS property,
  state,
  options.indexConfig['vector.dimensions']       AS dimensions,
  options.indexConfig['vector.similarity_function'] AS similarity_fn,
  CASE state
    WHEN 'ONLINE' THEN 'OK'
    ELSE               'FAIL'
  END AS health;

// Expected:
// Experience   embedding   ONLINE   1536   cosine   OK
// Memory       embedding   ONLINE   1536   cosine   OK
// Thought      embedding   ONLINE   1536   cosine   OK


// =============================================================================
// CHECK 4: Node count summary
// Verifies all 11 node labels exist in the database.
// If you ran seed.cypher, all counts should be >= 1.
// If you did NOT run seed.cypher, all counts will be 0 -- that is still OK,
// it confirms the constraints and indexes are in place.
// =============================================================================

CALL apoc.meta.stats()
YIELD labels
RETURN
  labels['User']       AS user_count,
  labels['Session']    AS session_count,
  labels['Experience'] AS experience_count,
  labels['Emotion']    AS emotion_count,
  labels['Trigger']    AS trigger_count,
  labels['Thought']    AS thought_count,
  labels['Behavior']   AS behavior_count,
  labels['Person']     AS person_count,
  labels['Topic']      AS topic_count,
  labels['Assessment'] AS assessment_count,
  labels['Memory']     AS memory_count;

// If APOC is not installed, use this fallback instead:
// MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label;


// =============================================================================
// CHECK 5: Relationship type coverage
// Verifies all expected relationship types exist in the schema.
// Expected after seed: 16 distinct relationship types.
// Expected without seed: 0 rows (no data yet -- that is fine).
// =============================================================================

CALL apoc.meta.stats()
YIELD relTypesCount
UNWIND keys(relTypesCount) AS rel_type
RETURN rel_type, relTypesCount[rel_type] AS count
ORDER BY rel_type;

// Expected relationship types (from your schema):
// HAD_SESSION, HAS_MEMORY, HAS_RECURRING_THEME, PRODUCED_ASSESSMENT
// FELT, TRIGGERED_BY, TRIGGERED_EMOTION, ACTIVATED_THOUGHT
// LED_TO_BEHAVIOR, ASSOCIATED_WITH, INVOLVES_PERSON, RELATED_TO_TOPIC
// SUPERSEDES (used at runtime, may not appear until first contradiction)
// HAS_RECURRING_TRIGGER (user-level pattern link)


// =============================================================================
// CHECK 6: Seed data CBT chain integrity
// Only meaningful if you ran seed.cypher.
// Walks the full hot-cross bun chain from User to Behavior and verifies
// every link in the chain exists.
// Expected: 1 row with all values non-null.
// =============================================================================

MATCH (u:User {id: 'user-seed-001'})
OPTIONAL MATCH (u)-[:FELT]->(emo:Emotion)
OPTIONAL MATCH (emo)-[:ACTIVATED_THOUGHT]->(thought:Thought)
OPTIONAL MATCH (thought)-[:LED_TO_BEHAVIOR]->(beh:Behavior)
OPTIONAL MATCH (u)-[:HAD_SESSION]->(s:Session)-[:PRODUCED_ASSESSMENT]->(a:Assessment)
OPTIONAL MATCH (u)-[:HAS_MEMORY]->(m:Memory)
RETURN
  u.display_name            AS user,
  emo.label                 AS emotion_label,
  emo.valence               AS valence,
  thought.distortion        AS distortion,
  thought.challenged        AS thought_challenged,
  beh.category              AS behavior_category,
  beh.adaptive              AS behavior_is_adaptive,
  a.instrument              AS assessment_instrument,
  a.score                   AS phq9_score,
  a.severity_label          AS severity,
  m.importance              AS memory_importance,
  m.active                  AS memory_active,
  CASE
    WHEN emo IS NULL    THEN 'FAIL: no emotion linked'
    WHEN thought IS NULL THEN 'FAIL: no thought in chain'
    WHEN beh IS NULL    THEN 'FAIL: no behavior in chain'
    WHEN a IS NULL      THEN 'FAIL: no assessment linked'
    WHEN m IS NULL      THEN 'FAIL: no memory linked'
    ELSE                     'PASS: full CBT chain intact'
  END AS chain_status;


// =============================================================================
// CHECK 7: Sensitivity tagging (migration 002)
// Verifies that all Memory and Experience nodes have sensitivity_level set.
// Expected: untagged_memory = 0, untagged_experience = 0
// =============================================================================

MATCH (m:Memory)
WITH
  count(m)                                                  AS total_memory,
  sum(CASE WHEN m.sensitivity_level IS NULL THEN 1 ELSE 0 END) AS untagged_memory,
  sum(CASE WHEN m.sensitivity_level = 'normal'     THEN 1 ELSE 0 END) AS normal_memory,
  sum(CASE WHEN m.sensitivity_level = 'sensitive'  THEN 1 ELSE 0 END) AS sensitive_memory,
  sum(CASE WHEN m.sensitivity_level = 'restricted' THEN 1 ELSE 0 END) AS restricted_memory

OPTIONAL MATCH (e:Experience)
RETURN
  total_memory,
  untagged_memory,
  CASE WHEN untagged_memory = 0 THEN 'PASS' ELSE 'FAIL: run migration 002' END AS memory_tag_status,
  normal_memory,
  sensitive_memory,
  restricted_memory,
  count(e)                                                       AS total_experience,
  sum(CASE WHEN e.sensitivity_level IS NULL THEN 1 ELSE 0 END)  AS untagged_experience,
  CASE
    WHEN sum(CASE WHEN e.sensitivity_level IS NULL THEN 1 ELSE 0 END) = 0
    THEN 'PASS'
    ELSE 'FAIL: run migration 002'
  END AS experience_tag_status;


// =============================================================================
// CHECK 8: Migration log
// Confirms which migrations have been applied.
// Expected: 2 rows (001 and 002) both with status = 'applied'
// =============================================================================

MATCH (log:MigrationLog)
RETURN
  log.version      AS version,
  log.description  AS description,
  log.applied_at   AS applied_at,
  log.status       AS status
ORDER BY log.version;


// =============================================================================
// CHECK 9: Escalation signal readiness
// Verifies the composite index used by the escalation threshold query exists
// and is online. This is the query that fires the reminder suppression logic:
// valence < -0.6 AND intensity > 0.7
// Expected: 1 row, health = OK
// =============================================================================

SHOW INDEXES
YIELD name, state, labelsOrTypes, properties
WHERE name = 'emotion_escalation_idx'
RETURN
  name,
  labelsOrTypes[0]  AS node_type,
  properties        AS columns,
  state,
  CASE state WHEN 'ONLINE' THEN 'OK' ELSE 'FAIL' END AS health;


// =============================================================================
// CHECK 10: Full health summary
// Single-row pass/fail summary you can scan at a glance.
// All values should be 'PASS' before you start writing application code.
// =============================================================================

CALL {
  // Constraint count
  CALL db.constraints() YIELD name
  WITH count(name) AS constraint_count
  RETURN constraint_count
}
CALL {
  // Index online count
  SHOW INDEXES YIELD state
  WHERE state = 'ONLINE'
  RETURN count(*) AS online_index_count
}
CALL {
  // Failed index count
  SHOW INDEXES YIELD state
  WHERE state = 'FAILED'
  RETURN count(*) AS failed_index_count
}
CALL {
  // Migration log count
  MATCH (log:MigrationLog)
  RETURN count(log) AS migration_count
}
RETURN
  constraint_count                                         AS total_constraints,
  online_index_count                                       AS indexes_online,
  failed_index_count                                       AS indexes_failed,
  migration_count                                          AS migrations_applied,
  CASE WHEN constraint_count  >= 22    THEN 'PASS' ELSE 'WARN: expected 22+' END AS constraints_status,
  CASE WHEN failed_index_count = 0     THEN 'PASS' ELSE 'FAIL: check indexes' END AS indexes_status,
  CASE WHEN migration_count   >= 2     THEN 'PASS' ELSE 'WARN: run migrations' END AS migrations_status;
