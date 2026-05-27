# Owner: Mohammad

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default="uuid_generate_v4()"
    )
    actor_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_tenant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_audit_log_actor_id", "actor_id"),
        Index("idx_audit_log_target_tenant_id", "target_tenant_id"),
        Index("idx_audit_log_timestamp", "timestamp"),
    )
