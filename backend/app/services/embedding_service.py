# Owner: Ali
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.cms_content import CmsContent
from app.models.embeddings import CmsChunk
from app.repositories.cms_repo import CmsRepository
from app.repositories.embedding_repo import EmbeddingChunk
from app.services.embedding_provider import EmbeddingProvider


WORD_RE = re.compile(r"\S+")


class IngestionError(ValueError):
    code = "ingestion_error"


class IngestionValidationError(IngestionError):
    code = "invalid_ingestion_payload"


class CmsIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    url: str | None = Field(default=None, max_length=2048)
    content_type: str = Field(default="page", min_length=1, max_length=80)
    locale: str = Field(default="en", min_length=2, max_length=16)
    published: bool = True

    @field_validator("tenant_id", "content_id", "title", "body", "url", "content_type", "locale", mode="before")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None


@dataclass(frozen=True)
class IngestionResult:
    tenant_id: str
    content_id: str
    chunk_count: int


class EmbeddingService:
    def __init__(
        self,
        *,
        cms_repository: CmsRepository,
        embedding_repository=None,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_size_words: int = 120,
        chunk_overlap_words: int = 20,
    ) -> None:
        if chunk_size_words <= 0:
            raise ValueError("chunk_size_words must be positive")
        if chunk_overlap_words < 0 or chunk_overlap_words >= chunk_size_words:
            raise ValueError("chunk_overlap_words must be smaller than chunk_size_words")
        self.cms_repository = cms_repository
        self.embedding_repository = embedding_repository
        self.embedding_provider = embedding_provider
        self.chunk_size_words = chunk_size_words
        self.chunk_overlap_words = chunk_overlap_words

    def ingest_content(self, payload: CmsIngestRequest | dict) -> IngestionResult:
        request = self._validate(payload)
        content = CmsContent(
            tenant_id=request.tenant_id,
            content_id=request.content_id,
            title=request.title,
            body=request.body,
            url=request.url,
            content_type=request.content_type,
            locale=request.locale,
            published=request.published,
        )
        self.cms_repository.upsert_content(content)
        chunks = self.chunk_content(content)
        self.cms_repository.replace_chunks(
            tenant_id=content.tenant_id,
            content_id=content.content_id,
            chunks=chunks,
        )
        if self.embedding_repository is not None:
            for chunk in chunks:
                embedding = chunk.embedding or (
                    self.embedding_provider.embed_text(chunk.text)
                    if self.embedding_provider is not None
                    else None
                )
                self.embedding_repository.add_chunk(
                    EmbeddingChunk(
                        chunk_id=chunk.chunk_id,
                        tenant_id=chunk.tenant_id,
                        cms_content_id=chunk.cms_content_id,
                        text=chunk.text,
                        title=chunk.title,
                        url=chunk.url,
                        content_type=chunk.content_type,
                        locale=chunk.locale,
                        published=chunk.published,
                        embedding=embedding,
                    )
                )
        return IngestionResult(
            tenant_id=content.tenant_id,
            content_id=content.content_id,
            chunk_count=len(chunks),
        )

    def chunk_content(self, content: CmsContent) -> list[CmsChunk]:
        words = WORD_RE.findall(content.body)
        chunks: list[CmsChunk] = []
        step = self.chunk_size_words - self.chunk_overlap_words
        for chunk_index, start in enumerate(range(0, len(words), step)):
            chunk_words = words[start : start + self.chunk_size_words]
            if not chunk_words:
                continue
            text = " ".join(chunk_words)
            chunks.append(
                CmsChunk(
                    chunk_id=self._chunk_id(content, chunk_index, text),
                    tenant_id=content.tenant_id,
                    cms_content_id=content.content_id,
                    title=content.title,
                    text=text,
                    chunk_index=chunk_index,
                    url=content.url,
                    content_type=content.content_type,
                    locale=content.locale,
                    published=content.published,
                    embedding=(
                        self.embedding_provider.embed_text(text)
                        if self.embedding_provider is not None
                        else None
                    ),
                )
            )
            if start + self.chunk_size_words >= len(words):
                break
        return chunks

    def _validate(self, payload: CmsIngestRequest | dict) -> CmsIngestRequest:
        try:
            return (
                payload
                if isinstance(payload, CmsIngestRequest)
                else CmsIngestRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise IngestionValidationError(str(exc)) from exc

    def _chunk_id(self, content: CmsContent, chunk_index: int, text: str) -> str:
        digest = hashlib.sha256(
            f"{content.tenant_id}:{content.content_id}:{chunk_index}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        return f"{content.content_id}:{chunk_index}:{digest}"
