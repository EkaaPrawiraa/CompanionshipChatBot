-- =============================================================================
-- 006_vector.up.sql
--
-- pgvector mirror tables that back the semantic-similarity layer of the
-- knowledge graph. One table per embeddable Neo4j label:
--
--     memory_embeddings      <- :Memory.summary
--     experience_embeddings  <- :Experience.description
--     thought_embeddings     <- :Thought.content
--     trigger_embeddings     <- :Trigger.description
--
-- Cross-store contract (DevNotes v1.3, Section 1.4)
-- -------------------------------------------------
-- Every row carries ``neo4j_node_id`` as the join key back to Neo4j.
-- That column is UNIQUE so the writers can use
-- ``ON CONFLICT (neo4j_node_id) DO UPDATE`` to make upserts idempotent.
-- The Neo4j node owns lifecycle state; we mirror ``active`` here only
-- so the ANN search can filter archived rows in a single query.
--
-- Index strategy
-- --------------
-- HNSW with cosine ops. (m=16, ef_construction=64) is the recommended
-- balance for 1k-100k vectors per user; tune up to (m=32, ef=128) if
-- recall slips on the production corpus.
-- A composite (user_id, active) btree backs the filter we apply
-- before the ANN probe so we never scan archived rows.
--
-- Depends on: 001_users.up.sql
-- Requires:   pgvector extension (>= 0.5.0 for HNSW)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;


-- -----------------------------------------------------------------------------
-- Memory
-- -----------------------------------------------------------------------------

CREATE TABLE memory_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX memory_user_active_idx
    ON memory_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Experience
-- -----------------------------------------------------------------------------

CREATE TABLE experience_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX experience_embedding_hnsw
    ON experience_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX experience_user_active_idx
    ON experience_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Thought
-- -----------------------------------------------------------------------------

CREATE TABLE thought_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX thought_embedding_hnsw
    ON thought_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX thought_user_active_idx
    ON thought_embeddings (user_id, active);


-- -----------------------------------------------------------------------------
-- Trigger
-- -----------------------------------------------------------------------------

CREATE TABLE trigger_embeddings (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    neo4j_node_id VARCHAR(64)  NOT NULL UNIQUE,
    content       TEXT         NOT NULL,
    embedding     vector(1536) NOT NULL,
    importance    FLOAT        NOT NULL DEFAULT 0.5,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX trigger_embedding_hnsw
    ON trigger_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX trigger_user_active_idx
    ON trigger_embeddings (user_id, active);
