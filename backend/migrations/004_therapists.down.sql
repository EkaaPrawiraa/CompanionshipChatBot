-- =============================================================================
-- 004_therapists.down.sql
--
-- Reverses 004_therapists.up.sql. Drops therapist_sessions and
-- consent_log before therapists because therapist_sessions references
-- therapists(id). consent_log has no FK to therapists but is part of
-- the same compliance domain so it lives in this migration.
--
-- Safety note: consent_log is the immutable UU PDP audit trail.
-- Production rollbacks MUST export this table first.
-- =============================================================================

DROP TABLE IF EXISTS consent_log;
DROP TABLE IF EXISTS therapist_sessions;
DROP TABLE IF EXISTS therapists;
