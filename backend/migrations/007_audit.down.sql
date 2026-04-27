-- =============================================================================
-- 007_audit.down.sql
--
-- Reverses 007_audit.up.sql. Drops every audit, retention, and access
-- table in dependency order. Indexes drop with the parent table.
--
-- Safety note: rolling this back destroys compliance audit trails
-- (audit_log, data_access_log, kg_mutation_log, retention_sweep_log).
-- Production environments MUST export these tables before invoking
-- this migration. Local development and CI are the only intended
-- callers.
-- =============================================================================

DROP TABLE IF EXISTS retention_sweep_log;
DROP TABLE IF EXISTS retention_policy;
DROP TABLE IF EXISTS data_access_log;
DROP TABLE IF EXISTS kg_mutation_log;
DROP TABLE IF EXISTS audit_log;
