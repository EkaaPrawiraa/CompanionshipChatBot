// =============================================================================
// constraints.cypher
//
// Uniqueness constraints for all 11 node types.
// Compatible with Neo4j Community Edition (5.x).
//
// NOTE: Property existence constraints (IS NOT NULL) require Enterprise
// Edition and have been removed. Null-safety is enforced at the application
// layer instead -- see kg_writer.py and neo4j_repo.go for validation.
//
// A UNIQUENESS constraint on (label, property) also implicitly creates a
// b-tree index on that property, so you get fast id lookups for free.
//
// Execution order:
//   1. constraints.cypher   <- this file
//   2. indexes.cypher
//   3. seed.cypher          (dev only)
//
// All constraints use IF NOT EXISTS -- safe to re-run (idempotent).
// =============================================================================


// SECTION 1: USER
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
  FOR (u:User) REQUIRE u.id IS UNIQUE;

// SECTION 2: SESSION
CREATE CONSTRAINT session_id_unique IF NOT EXISTS
  FOR (s:Session) REQUIRE s.id IS UNIQUE;

// SECTION 3: EXPERIENCE
CREATE CONSTRAINT experience_id_unique IF NOT EXISTS
  FOR (e:Experience) REQUIRE e.id IS UNIQUE;

// SECTION 4: EMOTION
CREATE CONSTRAINT emotion_id_unique IF NOT EXISTS
  FOR (em:Emotion) REQUIRE em.id IS UNIQUE;

// SECTION 5: TRIGGER
CREATE CONSTRAINT trigger_id_unique IF NOT EXISTS
  FOR (t:Trigger) REQUIRE t.id IS UNIQUE;

// SECTION 6: THOUGHT
CREATE CONSTRAINT thought_id_unique IF NOT EXISTS
  FOR (th:Thought) REQUIRE th.id IS UNIQUE;

// SECTION 7: BEHAVIOR
CREATE CONSTRAINT behavior_id_unique IF NOT EXISTS
  FOR (b:Behavior) REQUIRE b.id IS UNIQUE;

// SECTION 8: PERSON
CREATE CONSTRAINT person_id_unique IF NOT EXISTS
  FOR (p:Person) REQUIRE p.id IS UNIQUE;

// SECTION 9: TOPIC
CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
  FOR (top:Topic) REQUIRE top.id IS UNIQUE;

// SECTION 10: ASSESSMENT
CREATE CONSTRAINT assessment_id_unique IF NOT EXISTS
  FOR (a:Assessment) REQUIRE a.id IS UNIQUE;

// SECTION 11: MEMORY
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
  FOR (m:Memory) REQUIRE m.id IS UNIQUE;
