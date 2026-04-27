-- =============================================================================
-- 006_vector.down.sql
--
-- Reverses 006_vector.up.sql. Drops every pgvector mirror table and its
-- HNSW / btree indexes (indexes drop with the parent table). The
-- ``vector`` extension itself is left installed: it is harmless when
-- unused and other environments may share the same database.
--
-- Safety note: rolling this back drops every dense embedding row.
-- Re-running ``006_vector.up.sql`` plus the retry sweep
-- (``kg_vector.sweep_until_drained``) reconstructs the tables from
-- whatever Neo4j still considers ``embedding_synced = false``.
-- =============================================================================

DROP TABLE IF EXISTS trigger_embeddings;
DROP TABLE IF EXISTS thought_embeddings;
DROP TABLE IF EXISTS experience_embeddings;
DROP TABLE IF EXISTS memory_embeddings;

-- Intentionally NOT dropping the vector extension. Comment out if
-- you really need a clean teardown:
--   DROP EXTENSION IF EXISTS vector;
