# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CmsChunk:
    chunk_id: str
    tenant_id: str
    cms_content_id: str
    title: str
    text: str
    chunk_index: int
    url: str | None = None
    content_type: str = "page"
    locale: str = "en"
    published: bool = True
    embedding: list[float] | None = None
