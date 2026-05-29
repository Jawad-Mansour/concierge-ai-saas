# Owner: Ali
from __future__ import annotations

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

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


class PgCmsRepository:
    """Postgres CMS repository for production tenant-scoped RAG ingestion."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_content(self, content: CmsContent) -> CmsContent:
        self.db.execute(
            text("""
                INSERT INTO cms_content (
                    tenant_id, content_id, title, body, url,
                    content_type, locale, published, updated_at
                )
                VALUES (
                    :tenant_id, :content_id, :title, :body, :url,
                    :content_type, :locale, :published, :updated_at
                )
                ON CONFLICT (tenant_id, content_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    url = EXCLUDED.url,
                    content_type = EXCLUDED.content_type,
                    locale = EXCLUDED.locale,
                    published = EXCLUDED.published,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                "tenant_id": content.tenant_id,
                "content_id": content.content_id,
                "title": content.title,
                "body": content.body,
                "url": content.url,
                "content_type": content.content_type,
                "locale": content.locale,
                "published": content.published,
                "updated_at": content.effective_updated_at,
            },
        )
        return content

    def list_published_content(self, *, tenant_id: str) -> list[CmsContent]:
        rows = self.db.execute(
            text("""
                SELECT content_id, tenant_id, title, body, url, content_type, locale,
                       published, updated_at
                FROM cms_content
                WHERE tenant_id = :tenant_id AND published = true
            """),
            {"tenant_id": tenant_id},
        ).fetchall()
        return [
            CmsContent(
                content_id=row[0],
                tenant_id=str(row[1]),
                title=row[2],
                body=row[3],
                url=row[4],
                content_type=row[5],
                locale=row[6],
                published=bool(row[7]),
                updated_at=row[8],
            )
            for row in rows
        ]

    def replace_chunks(self, *, tenant_id: str, content_id: str, chunks: list[CmsChunk]) -> None:
        self.db.execute(
            text("DELETE FROM embeddings WHERE tenant_id = :tenant_id AND cms_content_id = :content_id"),
            {"tenant_id": tenant_id, "content_id": content_id},
        )

    def list_chunks(self, *, tenant_id: str) -> list[CmsChunk]:
        rows = self.db.execute(
            text("""
                SELECT chunk_id, tenant_id, cms_content_id, title, text, url,
                       content_type, page_id, locale, published
                FROM embeddings
                WHERE tenant_id = :tenant_id
                ORDER BY cms_content_id, chunk_id
            """),
            {"tenant_id": tenant_id},
        ).fetchall()
        return [
            CmsChunk(
                chunk_id=row[0],
                tenant_id=str(row[1]),
                cms_content_id=row[2],
                title=row[3],
                text=row[4],
                chunk_index=index,
                url=row[5],
                content_type=row[6],
                locale=row[8],
                published=bool(row[9]),
            )
            for index, row in enumerate(rows)
        ]
