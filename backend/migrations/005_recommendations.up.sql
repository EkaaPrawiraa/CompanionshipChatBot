-- migrations/005_recommendations.up.sql

CREATE TABLE recommendation_content (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        VARCHAR(30) NOT NULL,  -- breathing | journaling | exercise | grounding | reframe
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    content_url     TEXT,
    duration_mins   SMALLINT,
    language        CHAR(2) NOT NULL DEFAULT 'id',
    tags            VARCHAR[] DEFAULT ARRAY[]::VARCHAR[],
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE recommendation_deliveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_id      UUID NOT NULL REFERENCES recommendation_content(id),
    session_id      UUID REFERENCES chat_sessions(id),
    trigger_reason  VARCHAR(100),          -- "low_mood_3_days" | "phq9_moderate" | etc
    delivered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted        BOOLEAN,               -- NULL = no response, TRUE = accepted, FALSE = dismissed
    completed_at    TIMESTAMPTZ
);

CREATE INDEX rec_user_recent ON recommendation_deliveries (user_id, delivered_at DESC);
