# Owner: Ali
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.cms_repo import InMemoryCmsRepository
from app.repositories.embedding_repo import InMemoryEmbeddingRepository
from app.services.embedding_service import EmbeddingService, IngestionValidationError


router = APIRouter(prefix="/cms", tags=["cms"])

# Mocked Mohammad-owned persistence/RLS dependency:
# replace these in-memory stores with tenant-scoped DB + pgvector repositories.
_cms_repo = InMemoryCmsRepository()
_embedding_repo = InMemoryEmbeddingRepository()


class CmsIngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    url: str | None = None
    content_type: str = "page"
    locale: str = "en"
    published: bool = True


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        cms_repository=_cms_repo,
        embedding_repository=_embedding_repo,
    )


@router.post("/ingest")
def ingest_content(
    body: CmsIngestBody,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    try:
        return asdict(embedding_service.ingest_content(body.model_dump()))
    except IngestionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chunks")
def list_chunks(
    # Mocked tenant input until tenant-admin auth derives this from session context.
    tenant_id: str = Query(min_length=1),
):
    return [asdict(chunk) for chunk in _cms_repo.list_chunks(tenant_id=tenant_id)]
