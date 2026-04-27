-- =============================================================================
-- pgvector_init.sql
--
-- Bootstrap script for the local docker-compose Postgres instance.
-- Mirrors backend/migrations/006_vector.up.sql so a fresh container
-- comes up with the pgvector extension and the four mirror tables
-- (memory, experience, thought, trigger) ready for the kg_vector
-- adapter.
--
-- This file is idempotent (CREATE ... IF NOT EXISTS everywhere) and
-- safe to re-run. In production the canonical source of truth is the
-- migration file; this init exists so local dev does not need a
-- separate migration runner.
--
-- Cross-store contract: see DevNotes v1.3 Section 1.4 and
-- docs/architecture/kg_schema.md Section 9.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- -----------------------------------------------------------------------------
-- Memory mirror table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS memory_user_active_idx
    ON memory_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Experience mirror table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS experience_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS experience_embedding_hnsw
    ON experience_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS experience_user_active_idx
    ON experience_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Thought mirror table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS thought_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS thought_embedding_hnsw
    ON thought_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS thought_user_active_idx
    ON thought_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Trigger mirror table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trigger_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS trigger_embedding_hnsw
    ON trigger_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS trigger_user_active_idx
    ON trigger_embeddings (user_id, active);
