-- Owner: Mohammad

-- ============================================================
-- Row-Level Security policies for all tenant-scoped tables.
--
-- Loaded by infra/postgres/Dockerfile as 02_rls_policies.sql
-- AFTER init.sql creates the tables.
--
-- Mirrored in infra/postgres/migrations/001_baseline.py so
-- `alembic upgrade head` produces an identical schema on a fresh DB.
--
-- Policy pattern (same for every table):
--   USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
--
-- current_setting(..., true) returns NULL when app.tenant_id is unset, OR
-- returns '' (empty string) when explicitly reset by tenant_context.py finally block.
-- NULLIF converts the empty string to NULL before the UUID cast — without it,
-- casting '' to UUID raises a Postgres error. UUID cast of NULL produces NULL,
-- which fails the equality check, returning no rows. This is intentional:
--   - Normal requests: app.tenant_id is set by tenant_context.py — rows filtered.
--   - Tenant Manager requests: app.tenant_id is NOT set — zero rows returned on
--     any accidental SELECT (read prohibition enforced structurally).
-- ============================================================

-- ── users ────────────────────────────────────────────────────────────────────

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

-- SELECT / UPDATE: tenant-scoped (normal requests set app.tenant_id via tenant_context.py)
CREATE POLICY tenant_isolation ON users
    FOR SELECT
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

-- SELECT bypass for login: email lookup before tenant context is known.
-- Set app.login_lookup='true' only inside user_repo.get_by_email(); reset immediately after.
CREATE POLICY email_login_lookup ON users
    FOR SELECT
    USING (current_setting('app.login_lookup', true) = 'true');

-- DELETE: normal tenant requests OR Tenant Manager erasure (app.erase_target = target UUID).
-- Separate from SELECT so TM can delete without being able to read content.
CREATE POLICY erase_isolation ON users
    FOR DELETE
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
        OR tenant_id::TEXT = current_setting('app.erase_target', true)
    );

-- INSERT / UPDATE: tenant-scoped (WITH CHECK enforces tenant_id matches context)
CREATE POLICY tenant_write ON users
    FOR INSERT
    WITH CHECK (true);  -- INSERT tenant_id validated by user_repo; RLS row-filter not needed

-- ── leads, cms_content, conversations, embeddings, widget_configs ────────────
-- Each table gets: tenant_isolation (SELECT/UPDATE), erase_isolation (DELETE).
-- Separate policies keep TM erasure (DELETE) structurally distinct from reads (SELECT).

DO $$ DECLARE
    t TEXT;
    rls_using TEXT := 'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID';
    erase_using TEXT := 'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID OR tenant_id::TEXT = current_setting(''app.erase_target'', true)';
BEGIN
    FOREACH t IN ARRAY ARRAY['leads','cms_content','conversations','embeddings','widget_configs']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I FOR SELECT USING (%s)', t, rls_using);
        EXECUTE format('CREATE POLICY erase_isolation ON %I FOR DELETE USING (%s)', t, erase_using);
    END LOOP;
END $$;

-- ── tenants — NO RLS ─────────────────────────────────────────────────────────
-- The tenants table is intentionally NOT under RLS. The Tenant Manager must be
-- able to SELECT tenants by ID for provisioning and erasure operations. The
-- tenant_admin sees only their own tenant via the repository filter, not RLS.

-- ── audit_log — NO RLS ───────────────────────────────────────────────────────
-- audit_log contains only action metadata (no visitor content, no PII). The
-- Tenant Manager reads it to review their own action history. No RLS needed.
