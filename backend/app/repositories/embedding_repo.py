# Owner: Ali
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol


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
