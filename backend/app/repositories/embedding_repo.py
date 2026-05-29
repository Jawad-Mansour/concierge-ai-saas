# Owner: Ali
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.embedding_provider import EmbeddingProvider


TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class EmbeddingChunk:
    chunk_id: str
    tenant_id: str
    cms_content_id: str
    text: str
    title: str
    url: str | None = None
    content_type: str | None = None
    page_id: str | None = None
    locale: str | None = None
    published: bool = True
    embedding: list[float] | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    tenant_id: str
    cms_content_id: str
    text: str
    title: str
    score: float
    url: str | None = None


class EmbeddingRepository(Protocol):
    def search(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        filters: dict[str, str | bool] | None = None,
    ) -> list[RetrievedChunk]:
        """Return tenant-scoped chunks ordered by relevance."""


class InMemoryEmbeddingRepository:
    """Tenant-filtered lexical retrieval used before pgvector is wired in."""

    def __init__(self, chunks: list[EmbeddingChunk] | None = None) -> None:
        self.chunks = chunks or []

    def add_chunk(self, chunk: EmbeddingChunk) -> None:
        self.chunks.append(chunk)

    def search(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        filters: dict[str, str | bool] | None = None,
    ) -> list[RetrievedChunk]:
        query_tokens = _token_counts(query)
        scored: list[RetrievedChunk] = []
        for chunk in self.chunks:
            if chunk.tenant_id != tenant_id:
                continue
            if not _matches_filters(chunk, filters):
                continue
            score = _cosine_similarity(query_tokens, _token_counts(chunk.text))
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    tenant_id=chunk.tenant_id,
                    cms_content_id=chunk.cms_content_id,
                    text=chunk.text,
                    title=chunk.title,
                    url=chunk.url,
                    score=score,
                )
            )
        return sorted(scored, key=lambda chunk: chunk.score, reverse=True)[:top_k]


def _token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in TOKEN_RE.findall(text.lower()):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _cosine_similarity(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(token, 0) for token, value in left.items())
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


def _matches_filters(
    chunk: EmbeddingChunk,
    filters: dict[str, str | bool] | None,
) -> bool:
    if not filters:
        return True
    for key, value in filters.items():
        if key == "published_only":
            if value is True and not chunk.published:
                return False
            continue
        if getattr(chunk, key) != value:
            return False
    return True


class InMemoryVectorEmbeddingRepository:
    """Semantic in-memory retrieval using generated embeddings for local runtime."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        chunks: list[EmbeddingChunk] | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.chunks: list[EmbeddingChunk] = []
        for chunk in chunks or []:
            self.add_chunk(chunk)

    def add_chunk(self, chunk: EmbeddingChunk) -> None:
        embedding = chunk.embedding or self.embedding_provider.embed_text(chunk.text)
        self.chunks.append(
            EmbeddingChunk(
                chunk_id=chunk.chunk_id,
                tenant_id=chunk.tenant_id,
                cms_content_id=chunk.cms_content_id,
                text=chunk.text,
                title=chunk.title,
                url=chunk.url,
                content_type=chunk.content_type,
                page_id=chunk.page_id,
                locale=chunk.locale,
                published=chunk.published,
                embedding=embedding,
            )
        )

    def search(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        filters: dict[str, str | bool] | None = None,
    ) -> list[RetrievedChunk]:
        query_embedding = self.embedding_provider.embed_text(query)
        scored: list[RetrievedChunk] = []
        for chunk in self.chunks:
            if chunk.tenant_id != tenant_id:
                continue
            if not _matches_filters(chunk, filters):
                continue
            if chunk.embedding is None:
                continue
            score = _vector_cosine_similarity(query_embedding, chunk.embedding)
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    tenant_id=chunk.tenant_id,
                    cms_content_id=chunk.cms_content_id,
                    text=chunk.text,
                    title=chunk.title,
                    url=chunk.url,
                    score=score,
                )
            )
        return sorted(scored, key=lambda chunk: chunk.score, reverse=True)[:top_k]


class PgVectorEmbeddingRepository:
    """Postgres pgvector retrieval for production tenant-scoped semantic search."""

    def __init__(self, *, db: Session, embedding_provider: EmbeddingProvider) -> None:
        self.db = db
        self.embedding_provider = embedding_provider

    def add_chunk(self, chunk: EmbeddingChunk) -> None:
        embedding = chunk.embedding or self.embedding_provider.embed_text(chunk.text)
        self.db.execute(
            text("""
                INSERT INTO embeddings (
                    tenant_id, chunk_id, cms_content_id, title, text, url,
                    content_type, page_id, locale, published, embedding
                )
                VALUES (
                    :tenant_id, :chunk_id, :cms_content_id, :title, :text, :url,
                    :content_type, :page_id, :locale, :published, :embedding
                )
                ON CONFLICT (tenant_id, chunk_id) DO UPDATE SET
                    cms_content_id = EXCLUDED.cms_content_id,
                    title = EXCLUDED.title,
                    text = EXCLUDED.text,
                    url = EXCLUDED.url,
                    content_type = EXCLUDED.content_type,
                    page_id = EXCLUDED.page_id,
                    locale = EXCLUDED.locale,
                    published = EXCLUDED.published,
                    embedding = EXCLUDED.embedding
            """),
            {
                "tenant_id": chunk.tenant_id,
                "chunk_id": chunk.chunk_id,
                "cms_content_id": chunk.cms_content_id,
                "title": chunk.title,
                "text": chunk.text,
                "url": chunk.url,
                "content_type": chunk.content_type,
                "page_id": chunk.page_id,
                "locale": chunk.locale,
                "published": chunk.published,
                "embedding": _pgvector_literal(embedding),
            },
        )

    def search(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        filters: dict[str, str | bool] | None = None,
    ) -> list[RetrievedChunk]:
        query_embedding = self.embedding_provider.embed_text(query)
        where_clauses = ["tenant_id = :tenant_id"]
        params: dict[str, object] = {
            "tenant_id": tenant_id,
            "query_embedding": _pgvector_literal(query_embedding),
            "top_k": top_k,
        }
        if filters:
            if filters.get("published_only") is True:
                where_clauses.append("published = true")
            for key in ("content_type", "page_id", "locale"):
                if key in filters:
                    where_clauses.append(f"{key} = :{key}")
                    params[key] = filters[key]

        rows = self.db.execute(
            text(f"""
                SELECT
                    chunk_id,
                    tenant_id,
                    cms_content_id,
                    text,
                    title,
                    url,
                    1 - (embedding <=> CAST(:query_embedding AS vector)) AS score
                FROM embeddings
                WHERE {" AND ".join(where_clauses)}
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
            """),
            params,
        ).fetchall()
        return [
            RetrievedChunk(
                chunk_id=row[0],
                tenant_id=str(row[1]),
                cms_content_id=row[2],
                text=row[3],
                title=row[4],
                url=row[5],
                score=float(row[6]),
            )
            for row in rows
        ]


def _vector_cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"
