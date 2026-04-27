-- migrations/004_therapists.up.sql

CREATE TABLE therapists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    license_number  VARCHAR(50),
    specializations VARCHAR[] DEFAULT ARRAY[]::VARCHAR[],
    bio             TEXT,
    languages       VARCHAR[] DEFAULT ARRAY['id']::VARCHAR[],
    available       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE therapist_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    therapist_id    UUID NOT NULL REFERENCES therapists(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    scheduled_at    TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    kg_summary_sent BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE when AI profiling summary shared
    consent_given   BOOLEAN NOT NULL DEFAULT FALSE,  -- User must explicitly consent
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User consent log (immutable — UU PDP audit requirement)
CREATE TABLE consent_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    consent_type    VARCHAR(50) NOT NULL,  -- data_processing | kg_summary_share | marketing
    granted         BOOLEAN NOT NULL,
    ip_address      INET,
    user_agent      TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- NOTE: consent_log rows are NEVER deleted. Immutable audit trail.
