# Owner: Ali
from __future__ import annotations

import os

from app.models.embeddings import CmsChunk
from sqlalchemy.orm import Session

from app.repositories.cms_repo import InMemoryCmsRepository, PgCmsRepository
from app.repositories.embedding_repo import InMemoryVectorEmbeddingRepository, PgVectorEmbeddingRepository
from app.services.embedding_service import EmbeddingService
from app.services.embedding_provider import (
    EmbeddingConfigurationError,
    HashingEmbeddingProvider,
    VoyageEmbeddingProvider,
)
from app.services.rag_service import RagService


# Mocked Mohammad-owned persistence/RLS dependency:
# these shared in-memory stores make local CMS ingestion searchable by /chat.
# Production can replace the in-memory vector repository with PgVectorEmbeddingRepository.
_cms_repo = InMemoryCmsRepository()
_embedding_provider = None
_embedding_repo = None


def build_embedding_provider():
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider
    try:
        _embedding_provider = VoyageEmbeddingProvider()
    except EmbeddingConfigurationError:
        _embedding_provider = HashingEmbeddingProvider()
    return _embedding_provider


def use_pgvector_backend() -> bool:
    return os.getenv("RAG_BACKEND", "").strip().lower() == "pgvector"


def build_embedding_repository() -> InMemoryVectorEmbeddingRepository:
    global _embedding_repo
    if _embedding_repo is None:
        _embedding_repo = InMemoryVectorEmbeddingRepository(
            embedding_provider=build_embedding_provider(),
        )
    return _embedding_repo


def build_pgvector_embedding_service(db: Session) -> EmbeddingService:
    embedding_provider = VoyageEmbeddingProvider()
    return EmbeddingService(
        cms_repository=PgCmsRepository(db),
        embedding_repository=PgVectorEmbeddingRepository(
            db=db,
            embedding_provider=embedding_provider,
        ),
        embedding_provider=embedding_provider,
    )


def build_pgvector_rag_service(db: Session) -> RagService:
    embedding_provider = VoyageEmbeddingProvider()
    return RagService(
        PgVectorEmbeddingRepository(
            db=db,
            embedding_provider=embedding_provider,
        ),
        strategy="pgvector_semantic",
    )


def build_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        cms_repository=_cms_repo,
        embedding_repository=build_embedding_repository(),
        embedding_provider=build_embedding_provider(),
    )


def build_rag_service() -> RagService:
    return RagService(build_embedding_repository(), strategy="semantic_vector")


def list_runtime_chunks(*, tenant_id: str) -> list[CmsChunk]:
    return _cms_repo.list_chunks(tenant_id=tenant_id)


def reset_runtime_stores_for_tests() -> None:
    global _cms_repo, _embedding_provider, _embedding_repo
    _cms_repo = InMemoryCmsRepository()
    _embedding_provider = HashingEmbeddingProvider()
    _embedding_repo = InMemoryVectorEmbeddingRepository(
        embedding_provider=_embedding_provider,
    )
