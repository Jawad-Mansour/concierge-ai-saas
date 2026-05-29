# Owner: Charbel

"""Add widget_id_lookup RLS policy on widget_configs.

widget_id is a public pre-auth identifier. The pre-auth SELECT by widget_id
must bypass the tenant_isolation policy (which requires app.tenant_id to be
set). This policy mirrors the email_login_lookup pattern on users:
the app sets app.widget_lookup='true' before the SELECT and resets it after.

Revision ID: 003
Revises: 002
Create Date: 2026-05-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE POLICY widget_id_lookup ON widget_configs
            FOR SELECT
            USING (current_setting('app.widget_lookup', true) = 'true')
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS widget_id_lookup ON widget_configs")
