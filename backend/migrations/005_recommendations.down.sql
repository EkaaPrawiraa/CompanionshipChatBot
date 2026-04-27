-- =============================================================================
-- 005_recommendations.down.sql
--
-- Reverses 005_recommendations.up.sql. Drops the deliveries table
-- before the content table because deliveries.content_id references it.
-- =============================================================================

DROP TABLE IF EXISTS recommendation_deliveries;
DROP TABLE IF EXISTS recommendation_content;
