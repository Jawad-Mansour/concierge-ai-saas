# Owner: Charbel

"""Add guardrails_configs table.

Per-tenant guardrails configuration: allowed topics, refusal persona,
escalation triggers. Read at request time by the chat path and forwarded
to the guardrails sidecar as TenantConfig. No caching — every request
gets the current row.

Revision ID: 004
Revises: 003
Create Date: 2026-05-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guardrails_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "allowed_topics",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("refusal_persona", postgresql.JSONB(), nullable=True),
        sa.Column(
            "escalation_triggers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_guardrails_configs_tenant_id",
        "guardrails_configs",
        ["tenant_id"],
        unique=True,
    )

    op.execute("ALTER TABLE guardrails_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guardrails_configs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON guardrails_configs
            FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("""
        CREATE POLICY tenant_write ON guardrails_configs
            FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("""
        CREATE POLICY tenant_update ON guardrails_configs
            FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("""
        CREATE POLICY erase_isolation ON guardrails_configs
            FOR DELETE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
                OR tenant_id::TEXT = current_setting('app.erase_target', true)
            )
    """)


def downgrade() -> None:
    op.drop_table("guardrails_configs")
