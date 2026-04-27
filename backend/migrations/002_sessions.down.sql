-- =============================================================================
-- 002_sessions.down.sql
--
-- Reverses 002_sessions.up.sql. messages references chat_sessions(id),
-- so messages drops first.
-- =============================================================================

DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS chat_sessions;
