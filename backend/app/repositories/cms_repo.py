# Owner: Ali
from __future__ import annotations

from typing import Protocol

from app.models.cms_content import CmsContent
from app.models.embeddings import CmsChunk


class CmsRepository(Protocol):
    def upsert_content(self, content: CmsContent) -> CmsContent:
        """Persist tenant-scoped CMS content."""

    def list_published_content(self, *, tenant_id: str) -> list[CmsContent]:
        """Return only published content for one tenant."""

    def replace_chunks(self, *, tenant_id: str, content_id: str, chunks: list[CmsChunk]) -> None:
        """Replace all chunks for one tenant content item."""

    def list_chunks(self, *, tenant_id: str) -> list[CmsChunk]:
        """Return chunks for one tenant."""


class InMemoryCmsRepository:
    """Temporary repository until Mohammad's DB/RLS layer is ready."""

    def __init__(self) -> None:
        self.contents: dict[tuple[str, str], CmsContent] = {}
        self.chunks: dict[tuple[str, str], list[CmsChunk]] = {}

    def upsert_content(self, content: CmsContent) -> CmsContent:
        self.contents[(content.tenant_id, content.content_id)] = content
        return content

    def list_published_content(self, *, tenant_id: str) -> list[CmsContent]:
        return [
            content
            for (stored_tenant_id, _content_id), content in self.contents.items()
            if stored_tenant_id == tenant_id and content.published
        ]

    def replace_chunks(self, *, tenant_id: str, content_id: str, chunks: list[CmsChunk]) -> None:
        # Mocked Mohammad-owned RLS behavior:
        # the real DB repository must enforce tenant_id in every write and via Postgres RLS.
        self.chunks[(tenant_id, content_id)] = [
            chunk for chunk in chunks if chunk.tenant_id == tenant_id
        ]

    def list_chunks(self, *, tenant_id: str) -> list[CmsChunk]:
        tenant_chunks: list[CmsChunk] = []
        for (stored_tenant_id, _content_id), chunks in self.chunks.items():
            if stored_tenant_id == tenant_id:
                tenant_chunks.extend(chunks)
        return tenant_chunks
