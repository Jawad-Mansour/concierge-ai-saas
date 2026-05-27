# Owner: Ali
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.embedding_repo import EmbeddingChunk, InMemoryEmbeddingRepository
from app.services.chat_service import ChatService, ChatValidationError
from app.services.memory_service import InMemoryMemoryStore, MemoryService
from app.services.rag_service import RagService
from app.services.router_service import RouterService


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Mocked Mohammad/Charbel-owned auth input:
    # tenant_id must come from verified widget/auth context once widget auth is wired.
    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    # Mocked Charbel-owned widget input:
    # source_url/contact fields should arrive from the authenticated widget payload.
    source_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    trace_id: str | None = None


def build_chat_service() -> ChatService:
    # Mocked Ali/Mohammad-owned persistence input:
    # replace this in-memory RAG corpus with tenant-scoped CMS/pgvector retrieval.
    rag_service = RagService(
        InMemoryEmbeddingRepository(
            [
                EmbeddingChunk(
                    chunk_id="demo-pricing",
                    tenant_id="demo-tenant",
                    cms_content_id="demo-cms-pricing",
                    title="Demo Pricing",
                    text="The demo tenant team plan costs 49 dollars per month.",
                    url="https://demo.example/pricing",
                )
            ]
        )
    )
    memory_service = MemoryService(InMemoryMemoryStore())
    return ChatService(
        memory_service=memory_service,
        router_service=RouterService(rag_tool=rag_service),
    )


@router.post("")
def chat(
    body: ChatRequestBody,
    chat_service: ChatService = Depends(build_chat_service),
):
    try:
        return asdict(chat_service.handle_message(body.model_dump()))
    except ChatValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
