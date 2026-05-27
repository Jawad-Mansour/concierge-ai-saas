# Owner: Mohammad

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLogEntry


def log_action(
    db: Session,
    *,
    actor_id: str,
    action: str,
    target_tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLogEntry:
    """Insert an immutable audit log entry. Never updates or deletes rows."""
    entry = AuditLogEntry(
        actor_id=actor_id,
        action=action,
        target_tenant_id=target_tenant_id,
        metadata=metadata,
    )
    db.add(entry)
    db.flush()
    return entry
