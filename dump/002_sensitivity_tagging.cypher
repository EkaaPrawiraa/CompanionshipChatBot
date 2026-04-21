// =============================================================================
// migrations/002_sensitivity_tagging.cypher
//
// Migration 002 -- Sensitivity tagging (Guardrail Layer 4).
//
// Adds sensitivity_level and privacy_cleared_at properties to Memory and
// Experience nodes, plus the supporting index and a retrieval guard pattern.
//
// Background:
//   Guardrail architecture has four layers (DevNotes v1.1, Section 4):
//     Layer 1: System prompt identity boundaries
//     Layer 2: LangGraph post-generation safety checker
//     Layer 3: Go gateway input validation (PII stripping, distress detection)
//     Layer 4: Neo4j sensitivity tagging on Memory nodes ← this migration
//
//   Layer 4 ensures that even if Layers 1-3 are bypassed, high-sensitivity
//   memories are excluded from LLM context injection by default. The
//   restriction is enforced at query time in kg_writer.py and neo4j_repo.go.
//
// Sensitivity levels (enum):
//   'normal'    -- default, included in all retrieval queries
//   'sensitive' -- excluded from semantic retrieval; only injected when
//                  the current session explicitly references the topic
//   'restricted'-- excluded from all automatic retrieval; requires
//                  explicit therapist or user consent flag to surface
//
// Privacy:
//   privacy_cleared_at -- set when user requests memory wipe (UU PDP
//   compliance). Nodes are archived (active = false), not hard deleted.
//
// Applied to: Memory, Experience
// (Emotion and Thought nodes inherit restriction via graph traversal --
//  if the parent Memory/Experience is restricted, downstream nodes in
//  the CBT chain are not retrieved.)
// =============================================================================


// -----------------------------------------------------------------------------
// Guard: skip if already applied
// -----------------------------------------------------------------------------

MATCH (log:MigrationLog {version: '002'})
WITH log
WHERE log.status = 'applied'
RETURN 'Migration 002 already applied, skipping.' AS status;


// -----------------------------------------------------------------------------
// Step 1: Add sensitivity_level to all existing Memory nodes (backfill)
// Default = 'normal' -- no change to retrieval behavior for existing data.
// -----------------------------------------------------------------------------

MATCH (m:Memory)
WHERE m.sensitivity_level IS NULL
SET m.sensitivity_level = 'normal';


// -----------------------------------------------------------------------------
// Step 2: Add sensitivity_level to all existing Experience nodes (backfill)
// -----------------------------------------------------------------------------

MATCH (e:Experience)
WHERE e.sensitivity_level IS NULL
SET e.sensitivity_level = 'normal';


// -----------------------------------------------------------------------------
// Step 3: Add privacy_cleared_at to Memory nodes (null = not cleared)
// -----------------------------------------------------------------------------

MATCH (m:Memory)
WHERE m.privacy_cleared_at IS NULL
SET m.privacy_cleared_at = null;


// -----------------------------------------------------------------------------
// Step 4: Add privacy_cleared_at to Experience nodes
// -----------------------------------------------------------------------------

MATCH (e:Experience)
WHERE e.privacy_cleared_at IS NULL
SET e.privacy_cleared_at = null;


// -----------------------------------------------------------------------------
// Step 5: Constraint -- sensitivity_level must always be set on Memory
// Prevents application code from writing a Memory node without classifying it.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT memory_sensitivity_not_null IF NOT EXISTS
  FOR (m:Memory)
  REQUIRE m.sensitivity_level IS NOT NULL;


// -----------------------------------------------------------------------------
// Step 6: Constraint -- sensitivity_level must always be set on Experience
// -----------------------------------------------------------------------------

CREATE CONSTRAINT experience_sensitivity_not_null IF NOT EXISTS
  FOR (e:Experience)
  REQUIRE e.sensitivity_level IS NOT NULL;


// -----------------------------------------------------------------------------
// Step 7: Index -- fast filter for retrieval guard
// The hybrid retrieval query always adds: AND m.sensitivity_level = 'normal'
// as the default safe filter. This index makes that predicate fast.
// -----------------------------------------------------------------------------

CREATE INDEX memory_sensitivity_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.sensitivity_level);

CREATE INDEX experience_sensitivity_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.sensitivity_level);


// -----------------------------------------------------------------------------
// Step 8: Composite index -- active + sensitivity (most common retrieval path)
// WHERE m.active = true AND m.sensitivity_level = 'normal'
// ORDER BY m.importance DESC LIMIT 5
// -----------------------------------------------------------------------------

CREATE INDEX memory_active_sensitivity_idx IF NOT EXISTS
  FOR (m:Memory)
  ON (m.active, m.sensitivity_level);

CREATE INDEX experience_active_sensitivity_idx IF NOT EXISTS
  FOR (e:Experience)
  ON (e.active, e.sensitivity_level);


// -----------------------------------------------------------------------------
// Step 9: Mark migration as applied
// -----------------------------------------------------------------------------

MERGE (log:MigrationLog {version: '002'})
ON CREATE SET
  log.description = 'Sensitivity tagging on Memory and Experience nodes (Guardrail Layer 4)',
  log.applied_at  = datetime(),
  log.status      = 'applied'
ON MATCH SET
  log.applied_at  = datetime(),
  log.status      = 'applied';


// -----------------------------------------------------------------------------
// Verification
// Expected: Memory count with sensitivity_level set = total Memory count.
// -----------------------------------------------------------------------------

MATCH (m:Memory)
RETURN
  count(m)                                                  AS total_memory_nodes,
  count(m.sensitivity_level)                               AS nodes_with_sensitivity,
  sum(CASE WHEN m.sensitivity_level = 'normal'     THEN 1 ELSE 0 END) AS normal,
  sum(CASE WHEN m.sensitivity_level = 'sensitive'  THEN 1 ELSE 0 END) AS sensitive,
  sum(CASE WHEN m.sensitivity_level = 'restricted' THEN 1 ELSE 0 END) AS restricted;
