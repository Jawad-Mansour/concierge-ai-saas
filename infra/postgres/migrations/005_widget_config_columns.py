# Owner: Charbel

"""Add missing columns and INSERT/UPDATE RLS policies to widget_configs.

init.sql shipped widget_configs as a stub (id, tenant_id, created_at only).
Migrations 001–003 added RLS and columns but are skipped on fresh installs
(entrypoint stamps to 003). This migration fills the gap idempotently:

  - ADD COLUMN IF NOT EXISTS for all six data columns (safe if 002 already ran)
  - Unique index on widget_id (IF NOT EXISTS)
  - Bootstrap a default row for every existing tenant (ON CONFLICT DO NOTHING)
  - ENABLE/FORCE RLS (idempotent)
  - CREATE POLICY via DO/EXCEPTION for the three policies 001+003 may have
    already created (tenant_isolation, erase_isolation, widget_id_lookup)
  - CREATE POLICY for tenant_write and tenant_update — genuinely new in any
    migration chain; without them FORCE RLS blocks all INSERTs and UPDATEs

Revision ID: 005
Revises: 004
Create Date: 2026-05-29
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add columns (IF NOT EXISTS = safe if 002 already ran) ────────────────
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS widget_id UUID NOT NULL DEFAULT uuid_generate_v4()
    """)
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS allowed_origins TEXT[] NOT NULL DEFAULT ARRAY[]::text[]
    """)
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS theme JSONB NOT NULL DEFAULT '{}'::jsonb
    """)
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS greeting TEXT NOT NULL DEFAULT 'Hi! How can I help?'
    """)
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS enabled_tools TEXT[] NOT NULL
            DEFAULT ARRAY['rag_search','capture_lead','escalate']::text[]
    """)
    op.execute("""
        ALTER TABLE widget_configs
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """)

    # ── Unique index on the public-facing widget_id ───────────────────────────
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_widget_configs_widget_id
        ON widget_configs (widget_id)
    """)

    # ── Bootstrap a default row for every tenant that doesn't have one ────────
    # Ensures GET /admin/widget-config returns 200+defaults on first use.
    op.execute("""
        INSERT INTO widget_configs (tenant_id)
        SELECT id FROM tenants
        ON CONFLICT (tenant_id) DO NOTHING
    """)

    # ── RLS ───────────────────────────────────────────────────────────────────
    # ENABLE/FORCE are idempotent; CREATE POLICY is not, so use DO/EXCEPTION
    # blocks for the three policies that 001_baseline + 003 may have already
    # created. tenant_write and tenant_update are new in every migration chain.
    op.execute("ALTER TABLE widget_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE widget_configs FORCE ROW LEVEL SECURITY")

    op.execute("""
        DO $$ BEGIN
            CREATE POLICY tenant_isolation ON widget_configs
                FOR SELECT
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY widget_id_lookup ON widget_configs
                FOR SELECT
                USING (current_setting('app.widget_lookup', true) = 'true');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY erase_isolation ON widget_configs
                FOR DELETE
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                    OR tenant_id::TEXT = current_setting('app.erase_target', true)
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    # These two are genuinely absent from all prior migrations.
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY tenant_write ON widget_configs
                FOR INSERT
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY tenant_update ON widget_configs
                FOR UPDATE
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_update ON widget_configs")
    op.execute("DROP POLICY IF EXISTS tenant_write ON widget_configs")
    op.execute("DROP POLICY IF EXISTS erase_isolation ON widget_configs")
    op.execute("DROP POLICY IF EXISTS widget_id_lookup ON widget_configs")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON widget_configs")
    op.execute("ALTER TABLE widget_configs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_widget_configs_widget_id")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS enabled_tools")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS greeting")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS theme")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS allowed_origins")
    op.execute("ALTER TABLE widget_configs DROP COLUMN IF EXISTS widget_id")
