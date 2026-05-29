# Owner: Ali
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import SessionLocal
from app.services.embedding_service import EmbeddingService, IngestionValidationError
from app.services.rag_runtime import (
    build_embedding_service,
    build_pgvector_embedding_service,
    list_runtime_chunks,
    use_pgvector_backend,
)


router = APIRouter(prefix="/cms", tags=["cms"])


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


def tenant_id_from_request(request: Request, fallback_tenant_id: str) -> str:
    for source in (getattr(request, "state", None), request.app.state):
        if source is None:
            continue
        tenant_id = getattr(source, "tenant_id", None)
        if tenant_id:
            return str(tenant_id)
        claims = getattr(source, "claims", None)
        tenant_id = getattr(claims, "tenant_id", None)
        if tenant_id:
            return str(tenant_id)
    return fallback_tenant_id


def get_embedding_service():
    if not use_pgvector_backend():
        yield build_embedding_service()
        return
    db = SessionLocal()
    try:
        yield build_pgvector_embedding_service(db)
        db.commit()
    finally:
        db.close()


@router.post("/ingest")
def ingest_content(
    request: Request,
    body: CmsIngestBody,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    try:
        payload = body.model_dump()
        payload["tenant_id"] = tenant_id_from_request(request, body.tenant_id)
        return asdict(embedding_service.ingest_content(payload))
    except IngestionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chunks")
def list_chunks(
    request: Request,
    # Mocked tenant input until tenant-admin auth derives this from session context.
    tenant_id: str = Query(min_length=1),
):
    resolved_tenant_id = tenant_id_from_request(request, tenant_id)
    return [asdict(chunk) for chunk in list_runtime_chunks(tenant_id=resolved_tenant_id)]
