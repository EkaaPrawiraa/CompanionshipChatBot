-- =============================================================================
-- 003_assessments.down.sql
--
-- Reverses 003_assessments.up.sql. ema_entries and assessments both
-- reference users(id) and chat_sessions(id) but not each other, so
-- the drop order is independent.
-- =============================================================================

DROP TABLE IF EXISTS ema_entries;
DROP TABLE IF EXISTS assessments;
