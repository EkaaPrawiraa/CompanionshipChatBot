-- =============================================================================
-- 007_audit.up.sql
--
-- Append-only audit and retention tables for UU PDP / GDPR compliance.
-- Every table here is INSERT-only. Update / delete are reserved for the
-- nightly retention sweep, which deletes rows older than the policy
-- window and leaves a compaction record behind.
--
-- Why split this from the operational tables
-- ------------------------------------------
-- The application tables (users, chat_sessions, messages, recommendation_*)
-- are tuned for the read patterns of the live product. The audit tables
-- are tuned for compliance: write-mostly, immutable, per-actor, and
-- bounded by a configurable retention window. Mixing the two on the
-- same indices makes neither side fast.
--
-- Tables in this migration
-- ------------------------
--   audit_log
--       Single append-only feed for every privacy-relevant action.
--       Used to answer "who looked at / changed / deleted my data?"
--       within the 30-day request SLA defined in the UU PDP.
--
--   kg_mutation_log
--       Append-only feed of structural changes to the knowledge graph
--       (writer creates, modifier patches, soft / hard deletes). The
--       chat path stays cheap because the writer fires-and-forgets
--       a row here; the therapist console reads back from this table
--       to render a per-user timeline without paging Neo4j.
--
--   data_access_log
--       Records every read of a user's personal data by an internal
--       actor (therapist, support agent, model evaluator). Required
--       for the UU PDP "right to know who has accessed my records"
--       provision.
--
--   retention_policy
--       Configuration table. One row per data class with the maximum
--       age in days. The nightly job reads this table; never hard-code
--       retention windows in application code.
--
--   retention_sweep_log
--       What the nightly retention job actually deleted, per data
--       class, per run. Append-only; lets a regulator reconstruct the
--       deletion history without trusting application code.
--
-- Depends on: 001_users.up.sql, 002_sessions.up.sql, 004_therapists.up.sql
-- =============================================================================


-- -----------------------------------------------------------------------------
-- audit_log : single feed for every privacy-relevant action
-- -----------------------------------------------------------------------------

CREATE TABLE audit_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Subject of the action. user_id is nullable because some events
    -- (admin login, retention sweep) are not tied to a specific user.
    user_id         UUID         REFERENCES users(id) ON DELETE SET NULL,

    -- Who performed the action.
    --   actor_type IN ('user', 'therapist', 'admin', 'system')
    --   actor_id is the corresponding row id in users / therapists, or
    --   NULL for the 'system' actor (cron jobs, retention sweep).
    actor_type      VARCHAR(20)  NOT NULL,
    actor_id        UUID,

    -- What happened. action is a short verb namespace.event such as
    --   'auth.login', 'auth.logout', 'consent.grant', 'consent.revoke',
    --   'data.export', 'data.delete', 'kg.purge_message', 'kg.purge_user',
    --   'therapist.summary_share', 'session.start', 'session.end'.
    action          VARCHAR(60)  NOT NULL,

    -- Optional pointer to the operational row the action targeted.
    --   target_table = 'chat_sessions' / 'messages' / 'consent_log' / etc.
    --   target_id    = primary key of that row.
    target_table    VARCHAR(60),
    target_id       UUID,

    -- Free-form structured detail. Use sparingly; do NOT put PII here.
    -- Common keys: { "channel": "voice", "duration_ms": 180000, ... }
    metadata        JSONB        NOT NULL DEFAULT '{}'::JSONB,

    -- Where the action came from.
    ip_address      INET,
    user_agent      TEXT,

    occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- audit_log rows are immutable. Application code MUST NOT issue UPDATE
-- or DELETE on this table. The nightly retention sweep is the only
-- writer that may delete (and only via the dedicated function once we
-- add it in a future migration).

CREATE INDEX audit_user_recent
    ON audit_log (user_id, occurred_at DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX audit_actor_recent
    ON audit_log (actor_type, actor_id, occurred_at DESC);

CREATE INDEX audit_action_recent
    ON audit_log (action, occurred_at DESC);


-- -----------------------------------------------------------------------------
-- kg_mutation_log : structural changes to the knowledge graph
-- -----------------------------------------------------------------------------
--
-- The writers / modifier / deleter all fire-and-forget a row into this
-- table after their Neo4j transaction commits. The chat path never
-- waits on it. The therapist console reads this table to build a
-- per-user timeline without traversing Neo4j.

CREATE TABLE kg_mutation_log (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id           UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 'create' | 'update' | 'soft_delete' | 'hard_delete' | 'archive'
    operation         VARCHAR(20)  NOT NULL,

    -- Neo4j primary label of the target node, e.g. 'Memory', 'Thought'.
    node_label        VARCHAR(40)  NOT NULL,

    -- Neo4j node id (UUID stringified), our cross-store join key.
    neo4j_node_id     VARCHAR(64)  NOT NULL,

    -- Optional pointer back to the message that triggered the mutation.
    -- Lets the deleter answer "what facts did this message produce?".
    source_message_id UUID         REFERENCES messages(id) ON DELETE SET NULL,
    source_session_id UUID         REFERENCES chat_sessions(id) ON DELETE SET NULL,

    -- Patch detail (modifier writes the changed property names; deleter
    -- writes the reason). Keep schema-light; downstream code projects.
    detail            JSONB        NOT NULL DEFAULT '{}'::JSONB,

    occurred_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX kg_mut_user_recent
    ON kg_mutation_log (user_id, occurred_at DESC);

CREATE INDEX kg_mut_node
    ON kg_mutation_log (neo4j_node_id, occurred_at DESC);

CREATE INDEX kg_mut_message
    ON kg_mutation_log (source_message_id)
    WHERE source_message_id IS NOT NULL;


-- -----------------------------------------------------------------------------
-- data_access_log : internal-actor reads of user data
-- -----------------------------------------------------------------------------

CREATE TABLE data_access_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id         UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Who read the data.
    --   accessor_type IN ('therapist', 'admin', 'support', 'system_eval')
    accessor_type   VARCHAR(20)  NOT NULL,
    accessor_id     UUID,

    -- What was read.
    --   resource_type IN ('messages', 'memory_summary', 'kg_export',
    --                     'assessment', 'therapist_summary')
    resource_type   VARCHAR(40)  NOT NULL,
    resource_id     UUID,

    -- Why. Free text from the accessor's UI ("Pre-session review",
    -- "Crisis follow-up", etc). We display this back to the user when
    -- they exercise their UU PDP "right to know" request.
    reason          TEXT,

    accessed_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX dal_user_recent
    ON data_access_log (user_id, accessed_at DESC);

CREATE INDEX dal_accessor_recent
    ON data_access_log (accessor_type, accessor_id, accessed_at DESC);


-- -----------------------------------------------------------------------------
-- retention_policy : configurable per-data-class retention windows
-- -----------------------------------------------------------------------------
--
-- The nightly job iterates this table and deletes rows whose
-- ``occurred_at`` (or equivalent) is older than ``retention_days``.
-- One row per data class. data_class IS the lookup key, so it gets
-- the PRIMARY KEY.

CREATE TABLE retention_policy (
    data_class      VARCHAR(60)  PRIMARY KEY,
    retention_days  INTEGER      NOT NULL CHECK (retention_days > 0),
    description     TEXT,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Default policies. Keep these conservative; the regulator and the
-- product team can adjust later via UPDATE statements (which will
-- bump updated_at automatically once we add the trigger).
INSERT INTO retention_policy (data_class, retention_days, description) VALUES
    ('messages',           730, 'Raw chat turns (voice + text). 2 years.'),
    ('chat_sessions',      730, 'Session envelope. 2 years.'),
    ('audit_log',         2555, 'Privacy / consent audit. 7 years.'),
    ('kg_mutation_log',   1095, 'KG mutation history. 3 years.'),
    ('data_access_log',   2555, 'Internal-actor read trail. 7 years.'),
    ('refresh_tokens',      90, 'Auth refresh tokens. 90 days post-expiry.'),
    ('token_blacklist',     30, 'Blacklisted JWTs. 30 days post-expiry.'),
    ('recommendation_deliveries',
                           365, 'Recommendation history. 1 year.');

-- Note: consent_log is NOT in this list on purpose. consent_log is
-- immutable for the entire account lifetime; see migration 004.


-- -----------------------------------------------------------------------------
-- retention_sweep_log : audit trail for the nightly retention job
-- -----------------------------------------------------------------------------

CREATE TABLE retention_sweep_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    data_class      VARCHAR(60)  NOT NULL,
    cutoff_at       TIMESTAMPTZ  NOT NULL,   -- everything older than this got dropped
    rows_deleted    BIGINT       NOT NULL,
    duration_ms     INTEGER      NOT NULL,
    sweep_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sweep_finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX rsl_class_recent
    ON retention_sweep_log (data_class, sweep_finished_at DESC);
