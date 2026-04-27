-- migrations/001_users.up.sql

CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) NOT NULL UNIQUE,
    phone               VARCHAR(20),
    display_name        VARCHAR(100) NOT NULL,
    password_hash       CHAR(60) NOT NULL,          -- bcrypt, never store plaintext
    preferred_language  CHAR(2) NOT NULL DEFAULT 'id',
    onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
    account_status      VARCHAR(20) NOT NULL DEFAULT 'active',  -- active | suspended | deleted
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at       TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ    -- soft delete for UU PDP compliance
);

CREATE INDEX users_email_idx ON users (email) WHERE deleted_at IS NULL;
CREATE INDEX users_status_idx ON users (account_status) WHERE deleted_at IS NULL;


-- JWT refresh token storage
CREATE TABLE refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      CHAR(64) NOT NULL UNIQUE,  -- SHA-256 of token, never plaintext
    device_id       VARCHAR(64),               -- Android device fingerprint
    user_agent      TEXT,
    ip_address      INET,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX rt_user_active ON refresh_tokens (user_id)
    WHERE revoked_at IS NULL AND expires_at > NOW();

-- Access token blacklist (for forced logout / account suspension)
CREATE TABLE token_blacklist (
    jti         VARCHAR(36) PRIMARY KEY,   -- JWT ID claim
    user_id     UUID NOT NULL,
    blacklisted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);
-- Cleaned by nightly job: DELETE FROM token_blacklist WHERE expires_at < NOW();
