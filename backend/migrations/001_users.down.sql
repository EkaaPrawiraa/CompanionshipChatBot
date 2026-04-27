-- =============================================================================
-- 001_users.down.sql
--
-- Reverses 001_users.up.sql. token_blacklist and refresh_tokens go
-- first; users last.
--
-- Safety note: dropping users cascades to every child table that
-- declared ON DELETE CASCADE on users(id). Make sure higher-numbered
-- down migrations have already run.
-- =============================================================================

DROP TABLE IF EXISTS token_blacklist;
DROP TABLE IF EXISTS refresh_tokens;
DROP TABLE IF EXISTS users;
