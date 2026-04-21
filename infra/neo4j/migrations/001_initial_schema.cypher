// =============================================================================
// migrations/001_initial_schema.cypher
//
// Migration 001 -- Initial schema baseline.
//
// This migration marks the initial state of the schema after
// constraints.cypher and indexes.cypher have been applied.
// It does not add new constraints or indexes (those live in their own
// files). Instead it creates the MigrationLog node pattern so future
// migrations can check what has already been applied.
//
// Execution:
//   Run once during initial project setup, after constraints + indexes.
//   Safe to skip if you apply constraints and indexes directly.
//
// Pattern for future migrations:
//   - File naming:  NNN_description.cypher  (zero-padded, e.g. 002, 010)
//   - Each file:    checks MigrationLog before applying, inserts record after
//   - Never modify an applied migration file; always add a new one
// =============================================================================


// -----------------------------------------------------------------------------
// Guard: skip if already applied
// -----------------------------------------------------------------------------

MERGE (log:MigrationLog {version: '001'})
ON CREATE SET
  log.description = 'Initial schema baseline -- 11 nodes, 16 relationship types, Graphiti bi-temporal edges',
  log.applied_at  = datetime(),
  log.status      = 'applied'
ON MATCH SET
  log.status      = 'already_applied'
RETURN log.version AS version, log.status AS status, log.applied_at AS applied_at;
