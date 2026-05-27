# Owner: Mohammad

"""Baseline migration: tenants, users, audit_log tables + RLS policies.

Revision ID: 001
Revises:
Create Date: 2026-05-26

Run with: DATABASE_URL=... alembic -c backend/alembic.ini upgrade head
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── ENUM type ────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE user_role AS ENUM ('tenant_manager', 'tenant_admin', 'member')"
    )

    # ── tenants ──────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column(
            "allowed_origins",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            r"slug ~ '^[a-z0-9-]{2,63}$'", name="tenants_slug_check"
        ),
    )
    op.create_index("idx_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("idx_tenants_is_active", "tenants", ["is_active"])

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "tenant_manager", "tenant_admin", "member",
                name="user_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_users_email ON users (LOWER(email))"
    )
    op.create_index("idx_users_tenant_id", "users", ["tenant_id"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "target_tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_index("idx_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index(
        "idx_audit_log_target_tenant_id", "audit_log", ["target_tenant_id"]
    )
    op.create_index(
        "idx_audit_log_timestamp",
        "audit_log",
        [sa.text("timestamp DESC")],
    )

    # ── RLS: users ────────────────────────────────────────────────────────────
    # Three policies on users:
    #  tenant_isolation (SELECT): only rows where tenant_id matches app.tenant_id
    #  email_login_lookup (SELECT): bypass for login flow; app.login_lookup='true' activates
    #  erase_isolation (DELETE): allow TM erasure via app.erase_target without app.tenant_id
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON users
            FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("""
        CREATE POLICY email_login_lookup ON users
            FOR SELECT
            USING (current_setting('app.login_lookup', true) = 'true')
    """)
    op.execute("""
        CREATE POLICY erase_isolation ON users
            FOR DELETE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                OR tenant_id::TEXT = current_setting('app.erase_target', true)
            )
    """)
    op.execute("""
        CREATE POLICY tenant_write ON users
            FOR INSERT
            WITH CHECK (true)
    """)

    # ── Teammate stub tables ──────────────────────────────────────────────────
    # Minimal stub tables so RLS policies can be applied now; teammates fill
    # columns in their own migrations.
    for table, extra_cols in [
        ("leads", ""),
        ("cms_content", ""),
        ("conversations", ""),
        ("embeddings", ""),
        ("widget_configs", ""),
    ]:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE{extra_cols}
            )
        """)

    # ── RLS: teammate tables ──────────────────────────────────────────────────
    # Two policies per table: tenant_isolation (SELECT), erase_isolation (DELETE).
    # Separate policies keep TM erasure structurally distinct from tenant reads.
    for table in ("leads", "cms_content", "conversations", "embeddings", "widget_configs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                FOR SELECT
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """)
        op.execute(f"""
            CREATE POLICY erase_isolation ON {table}
                FOR DELETE
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                    OR tenant_id::TEXT = current_setting('app.erase_target', true)
                )
        """)


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("tenants")
    op.execute("DROP TYPE IF EXISTS user_role")
