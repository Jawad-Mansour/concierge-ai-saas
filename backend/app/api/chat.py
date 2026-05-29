# Owner: Ali
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import SessionLocal
from app.repositories.lead_repo import InMemoryLeadRepository
from app.services.agent_service import (
    AgentService,
    AnthropicAgentPlanner,
    HeuristicAgentPlanner,
    ToolRegistry,
)
from app.services.chat_service import ChatService, ChatValidationError
from app.services.lead_service import LeadService
from app.services.memory_service import InMemoryMemoryStore, MemoryService, RedisMemoryStore
from app.services.rag_answer_service import (
    AnthropicRagAnswerGenerator,
    ExtractiveRagAnswerGenerator,
)
from app.services.rag_runtime import build_pgvector_rag_service, build_rag_service, use_pgvector_backend
from app.services.rag_service import RagService
from app.services.router_service import RouterService

try:
    from app.middleware.guardrails import screen_input, screen_output
except ImportError:
    screen_input = None
    screen_output = None


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


def build_chat_service(*, db=None) -> ChatService:
    rag_service = build_pgvector_rag_service(db) if db is not None else build_rag_service()
    lead_service = LeadService(repository=InMemoryLeadRepository())
    memory_service = MemoryService(build_memory_store())
    return ChatService(
        memory_service=memory_service,
        router_service=RouterService(rag_tool=rag_service, lead_tool=lead_service),
        agent_service=build_agent_service(rag_service=rag_service, lead_service=lead_service),
        rag_answer_generator=build_rag_answer_generator(),
    )


def get_chat_service():
    if not use_pgvector_backend():
        yield build_chat_service()
        return
    db = SessionLocal()
    try:
        yield build_chat_service(db=db)
    finally:
        db.close()


def build_memory_store():
    try:
        return RedisMemoryStore()
    except RuntimeError:
        return InMemoryMemoryStore()


def build_agent_service(*, rag_service: RagService, lead_service: LeadService) -> AgentService:
    planner = (
        AnthropicAgentPlanner()
        if _has_anthropic_key()
        else HeuristicAgentPlanner()
    )
    return AgentService(
        tool_registry=ToolRegistry(
            rag_tool=rag_service,
            lead_tool=lead_service,
        ),
        planner=planner,
    )


def _has_anthropic_key() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return bool(key and key != "replace-me")


def build_rag_answer_generator():
    if _has_anthropic_key():
        return AnthropicRagAnswerGenerator()
    return ExtractiveRagAnswerGenerator()


@router.post("")
async def chat(
    request: Request,
    body: ChatRequestBody,
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        classifier_client = getattr(request.app.state, "classifier_client", None)
        guardrail_client = getattr(request.app.state, "guardrail_client", None)
        classification = None
        if classifier_client is not None:
            classification = await classifier_client.classify(
                tenant_id=body.tenant_id,
                message=body.message,
            )

        if screen_input is not None and guardrail_client is not None:
            decision, reply = await screen_input(
                guardrail_client,
                tenant_id=body.tenant_id,
                message=body.message,
                tenant_config=None,
            )
            if reply.escalate:
                return {
                    "conversation_id": body.conversation_id,
                    "decision": "escalate",
                    "message": reply.text or "I will flag this for human follow-up.",
                    "trace_id": body.trace_id,
                }
            if decision.decision == "block":
                return {
                    "conversation_id": body.conversation_id,
                    "decision": "blocked",
                    "message": reply.text,
                    "trace_id": body.trace_id,
                }

        response = chat_service.handle_message(
            body.model_dump(),
            classification=classification,
        )

        if screen_output is not None and guardrail_client is not None:
            decision, reply = await screen_output(
                guardrail_client,
                tenant_id=body.tenant_id,
                llm_response=response.message,
                tenant_config=None,
            )
            if decision.decision == "block":
                response = type(response)(
                    conversation_id=response.conversation_id,
                    decision="blocked",
                    message=reply.text,
                    trace_id=response.trace_id,
                )
            elif reply.text is not None:
                response = type(response)(
                    conversation_id=response.conversation_id,
                    decision=response.decision,
                    message=reply.text,
                    trace_id=response.trace_id,
                )
        return asdict(response)
    except ChatValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
