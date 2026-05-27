-- Owner: Charbel
-- Migration 001: widget_configs table
-- Required by POST /auth/widget-token (Mohammad's auth slice)

CREATE TABLE IF NOT EXISTS widget_configs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    widget_id     UUID NOT NULL UNIQUE,
    allowed_origins TEXT[] NOT NULL DEFAULT '{}',
    theme         JSONB NOT NULL DEFAULT '{}',
    greeting      TEXT NOT NULL DEFAULT 'Hello! How can I help you today?',
    enabled_tools TEXT[] NOT NULL DEFAULT '{rag_search,capture_lead,escalate}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_widget_configs_tenant_id
    ON widget_configs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_widget_configs_widget_id
    ON widget_configs(widget_id);

-- RLS
ALTER TABLE widget_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE widget_configs FORCE ROW LEVEL SECURITY;

CREATE POLICY widget_configs_tenant_isolation
    ON widget_configs
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
