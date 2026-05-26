# Owner: Ali
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.repositories.embedding_repo import EmbeddingRepository, RetrievedChunk


ALLOWED_FILTERS = {"content_type", "page_id", "locale", "published_only"}
MAX_QUERY_CHARS = 2000
MAX_SNIPPET_CHARS = 700


class RagError(ValueError):
    code = "rag_error"


class TenantContextError(RagError):
    code = "missing_tenant_context"


class RagValidationError(RagError):
    code = "invalid_rag_payload"


class CrossTenantRetrievalError(RagError):
    code = "cross_tenant_retrieval"


class RagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=5, ge=1, le=10)
    filters: dict[str, str | bool] | None = None
    rewrite_query: bool = False
    min_score: float = Field(default=0.05, ge=0, le=1)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator("tenant_id", "conversation_id", "query", "trace_id", mode="before")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def validate_filters(self) -> RagRequest:
        if not self.filters:
            return self
        unknown = set(self.filters) - ALLOWED_FILTERS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported filters: {names}")
        for key, value in self.filters.items():
            if key == "published_only" and not isinstance(value, bool):
                raise ValueError("published_only must be a boolean")
            if key != "published_only" and not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
        return self


@dataclass(frozen=True)
class RagCitation:
    chunk_id: str
    cms_content_id: str
    title: str
    url: str | None
    score: float


@dataclass(frozen=True)
class RagMeta:
    tenant_id: str
    query_hash: str
    top_k: int
    returned_count: int
    strategy: str
    latency_ms: int


@dataclass(frozen=True)
class RagResult:
    answer_context: list[str]
    citations: list[RagCitation]
    retrieval_meta: RagMeta
    status: Literal["ok", "no_results", "low_confidence"]


class RagService:
    def __init__(
        self,
        repository: EmbeddingRepository,
        *,
        strategy: str = "lexical_baseline",
    ) -> None:
        self.repository = repository
        self.strategy = strategy

    def search(self, payload: RagRequest | dict) -> RagResult:
        request = self._validate(payload)
        started_at = perf_counter()
        chunks = self.repository.search(
            tenant_id=request.tenant_id,
            query=request.query,
            top_k=request.top_k,
            filters=request.filters,
        )
        self._assert_tenant_scope(request.tenant_id, chunks)

        status: Literal["ok", "no_results", "low_confidence"]
        if not chunks:
            status = "no_results"
        elif chunks[0].score < request.min_score:
            status = "low_confidence"
        else:
            status = "ok"

        usable_chunks = chunks if status == "ok" else []
        latency_ms = int((perf_counter() - started_at) * 1000)
        return RagResult(
            answer_context=[self._snippet(chunk) for chunk in usable_chunks],
            citations=[self._citation(chunk) for chunk in usable_chunks],
            retrieval_meta=RagMeta(
                tenant_id=request.tenant_id,
                query_hash=self._query_hash(request.query),
                top_k=request.top_k,
                returned_count=len(usable_chunks),
                strategy=self.strategy,
                latency_ms=latency_ms,
            ),
            status=status,
        )

    def _validate(self, payload: RagRequest | dict) -> RagRequest:
        try:
            request = (
                payload if isinstance(payload, RagRequest) else RagRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise RagValidationError(str(exc)) from exc
        if not request.tenant_id:
            raise TenantContextError("tenant context is required")
        return request

    def _assert_tenant_scope(
        self,
        tenant_id: str,
        chunks: list[RetrievedChunk],
    ) -> None:
        for chunk in chunks:
            if chunk.tenant_id != tenant_id:
                raise CrossTenantRetrievalError("retrieval returned another tenant's chunk")

    def _snippet(self, chunk: RetrievedChunk) -> str:
        text = " ".join(chunk.text.split())
        if len(text) <= MAX_SNIPPET_CHARS:
            return text
        return f"{text[:MAX_SNIPPET_CHARS].rstrip()}..."

    def _citation(self, chunk: RetrievedChunk) -> RagCitation:
        return RagCitation(
            chunk_id=chunk.chunk_id,
            cms_content_id=chunk.cms_content_id,
            title=chunk.title,
            url=chunk.url,
            score=round(chunk.score, 4),
        )

    def _query_hash(self, query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
