# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CmsContent:
    content_id: str
    tenant_id: str
    title: str
    body: str
    url: str | None = None
    content_type: str = "page"
    locale: str = "en"
    published: bool = True
    updated_at: datetime | None = None

    @property
    def effective_updated_at(self) -> datetime:
        return self.updated_at or datetime.now(UTC)
