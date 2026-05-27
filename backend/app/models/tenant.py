# Owner: Mohammad

import re
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default="uuid_generate_v4()"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    users = relationship("User", back_populates="tenant", passive_deletes=True)

    __table_args__ = (
        CheckConstraint(r"slug ~ '^[a-z0-9-]{2,63}$'", name="tenants_slug_check"),
        Index("idx_tenants_slug", "slug", unique=True),
        Index("idx_tenants_is_active", "is_active"),
    )

    _SLUG_RE = re.compile(r"^[a-z0-9-]{2,63}$")
    _ORIGIN_RE = re.compile(r"^https?://[^/]+$")

    def validate(self) -> None:
        if not self._SLUG_RE.match(self.slug):
            raise ValueError(f"Invalid slug: {self.slug!r}")
        for origin in self.allowed_origins:
            if not self._ORIGIN_RE.match(origin):
                raise ValueError(f"Invalid origin: {origin!r}")
