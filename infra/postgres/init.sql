-- Owner: Mohammad

-- ============================================================
-- Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Types
-- ============================================================

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('tenant_manager', 'tenant_admin', 'member');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- Mohammad's tables
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(63)  NOT NULL,
    allowed_origins TEXT[]       NOT NULL DEFAULT '{}',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT tenants_slug_check CHECK (slug ~ '^[a-z0-9-]{2,63}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_slug      ON tenants (slug);
CREATE INDEX       IF NOT EXISTS idx_tenants_is_active  ON tenants (is_active);

CREATE TABLE IF NOT EXISTS users (
    id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID         REFERENCES tenants(id) ON DELETE RESTRICT,
    email           VARCHAR(320) NOT NULL,
    hashed_password TEXT         NOT NULL,
    role            user_role    NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email       ON users (LOWER(email));
CREATE INDEX       IF NOT EXISTS idx_users_tenant_id    ON users (tenant_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id         UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    action           VARCHAR(64) NOT NULL,
    target_tenant_id UUID        REFERENCES tenants(id) ON DELETE SET NULL,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata         JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_actor_id         ON audit_log (actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_target_tenant_id ON audit_log (target_tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp        ON audit_log (timestamp DESC);

-- ============================================================
-- Ali's tables — stubs with tenant_id; Ali adds columns
-- ============================================================

CREATE TABLE IF NOT EXISTS leads (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Ali: add visitor_name, email, phone, source, conversation_id, etc.
);

CREATE INDEX IF NOT EXISTS idx_leads_tenant_id ON leads (tenant_id);

CREATE TABLE IF NOT EXISTS cms_content (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Ali: add title, body, content_type, published_at, etc.
);

CREATE INDEX IF NOT EXISTS idx_cms_content_tenant_id ON cms_content (tenant_id);

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Ali: add session_id, visitor_id, status, started_at, ended_at, etc.
);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_id ON conversations (tenant_id);

CREATE TABLE IF NOT EXISTS embeddings (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- vector column dimension to be confirmed with Ali (e.g. 1536 for ada-002)
    embedding   vector(1536),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Ali: add cms_content_id FK, chunk_text, model_name, etc.
);

CREATE INDEX IF NOT EXISTS idx_embeddings_tenant_id ON embeddings (tenant_id);

-- ============================================================
-- Charbel's tables — stub with tenant_id; Charbel adds columns
-- ============================================================

CREATE TABLE IF NOT EXISTS widget_configs (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Charbel: add greeting, theme_primary_color, theme_secondary_color,
    --          bot_name, widget_id UUID, etc.
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_widget_configs_tenant_id ON widget_configs (tenant_id);
