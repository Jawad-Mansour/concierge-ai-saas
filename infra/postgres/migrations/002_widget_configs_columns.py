# Owner: Charbel
"""Add widget_configs columns.

Revision ID: 002
Revises: 001
Create Date: 2026-05-28
"""

from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the stub unique index Mohammad created (wrong — should not
    # be unique on tenant_id, a tenant can have multiple widgets)
    op.execute(
        "DROP INDEX IF EXISTS idx_widget_configs_tenant_id"
    )

    # Add real columns to the stub table
    op.add_column("widget_configs",
        sa.Column("widget_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
            unique=True
        )
    )
    op.add_column("widget_configs",
        sa.Column("allowed_origins",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}"
        )
    )
    op.add_column("widget_configs",
        sa.Column("theme", postgresql.JSONB(),
            nullable=False,
            server_default="{}"
        )
    )
    op.add_column("widget_configs",
        sa.Column("greeting", sa.Text(),
            nullable=False,
            server_default="Hello! How can I help you today?"
        )
    )
    op.add_column("widget_configs",
        sa.Column("enabled_tools",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{rag_search,capture_lead,escalate}"
        )
    )
    op.add_column("widget_configs",
        sa.Column("updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()")
        )
    )

    # Proper indexes
    op.create_index(
        "idx_widget_configs_widget_id",
        "widget_configs", ["widget_id"], unique=True
    )
    op.create_index(
        "idx_widget_configs_tenant_id",
        "widget_configs", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_widget_configs_widget_id")
    op.drop_index("idx_widget_configs_tenant_id")
    op.drop_column("widget_configs", "widget_id")
    op.drop_column("widget_configs", "allowed_origins")
    op.drop_column("widget_configs", "theme")
    op.drop_column("widget_configs", "greeting")
    op.drop_column("widget_configs", "enabled_tools")
    op.drop_column("widget_configs", "updated_at")
