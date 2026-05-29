# Owner: Charbel

"""Guardrails config repository — reads guardrails_configs table.

Used by the chat path, which runs without get_tenant_db. Sets app.tenant_id
for the duration of the SELECT to satisfy the tenant_isolation RLS policy,
then resets it in the finally block (mirrors the widget_repo pattern).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_for_tenant(db: Session, tenant_id: str) -> dict | None:
    """Return guardrails config for a tenant as a dict, or None if not configured.

    The returned dict matches the TenantConfig schema:
      allowed_topics, refusal_persona, escalation_triggers.
    """
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    try:
        row = db.execute(
            text(
                "SELECT allowed_topics, refusal_persona, escalation_triggers"
                " FROM guardrails_configs"
                " WHERE tenant_id = CAST(:tid AS uuid)"
            ),
            {"tid": tenant_id},
        ).fetchone()
    finally:
        db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    if row is None:
        return None
    return dict(row._mapping)
