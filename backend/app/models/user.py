# Owner: Mohammad

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(str, enum.Enum):
    tenant_manager = "tenant_manager"
    tenant_admin = "tenant_admin"
    member = "member"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default="uuid_generate_v4()"
    )
    # NULL only for tenant_manager — enforced at application layer
    tenant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", create_type=False), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    tenant = relationship("Tenant", back_populates="users")

    __table_args__ = (
        Index("idx_users_tenant_id", "tenant_id"),
        # Email uniqueness is enforced case-insensitively at the DB level via
        # idx_users_email on LOWER(email) in init.sql; duplicate index omitted here
        # to avoid SQLAlchemy attempting to recreate a functional index.
    )

    def validate_role_tenant_consistency(self) -> None:
        """Enforce role/tenant_id invariants before insert/update."""
        if self.role == Role.tenant_manager and self.tenant_id is not None:
            raise ValueError("tenant_manager must have tenant_id = NULL")
        if self.role in (Role.tenant_admin, Role.member) and self.tenant_id is None:
            raise ValueError(f"{self.role} must have a non-null tenant_id")
