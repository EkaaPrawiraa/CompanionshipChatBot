-- migrations/002_sessions.up.sql

CREATE TABLE chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    neo4j_session_id VARCHAR(64),           -- links to Session node in KG
    channel         VARCHAR(10) NOT NULL DEFAULT 'voice',  -- voice | text
    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- active | ended | abandoned
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    turn_count      INTEGER NOT NULL DEFAULT 0,
    sentiment_avg   FLOAT,                 -- populated at session end
    safety_escalated BOOLEAN NOT NULL DEFAULT FALSE,
    kg_processed    BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE after async consolidation
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sessions_user_recent ON chat_sessions (user_id, started_at DESC)
    WHERE status != 'abandoned';
    
CREATE INDEX sessions_pending_kg ON chat_sessions (id)
    WHERE kg_processed = FALSE AND status = 'ended';

-- Individual message records (source of truth for audit)
CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(10) NOT NULL,   -- user | assistant | system
    content         TEXT NOT NULL,
    audio_url       TEXT,                   -- S3 / storage URL for voice turns
    emotion_label   VARCHAR(30),            -- detected emotion for this turn
    safety_flag     VARCHAR(20),            -- safe | escalate | crisis
    turn_index      INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX messages_session ON messages (session_id, turn_index);
