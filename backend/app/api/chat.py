# Owner: Ali
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.middleware.auth_middleware import UserClaims, oauth2_scheme
from app.services.auth_service import verify_token
from app.repositories import guardrails_repo
from app.repositories.embedding_repo import EmbeddingChunk, InMemoryEmbeddingRepository
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
    from sqlalchemy import create_engine, text
    import os

    chunks: list[EmbeddingChunk] = []
    try:
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT slug, id::text FROM tenants")).fetchall()
        seeds = {
            "acme-coffee": [
                ("Our Coffee", "Acme Coffee serves single-origin espresso, pour-over coffee, and whole bean varieties from Ethiopia and Colombia."),
                ("Brewing Methods", "We offer espresso, pour-over, French press, and cold brew. Our beans are medium-roast and lightly oily."),
            ],
            "brew-bar": [
                ("Our Tea", "Brew Bar serves artisan teas, matcha lattes, and seasonal pastries."),
                ("Menu", "Featured drinks include jasmine green tea, oolong, chai latte, and earl grey."),
            ],
        }
        for slug, tenant_id in rows:
            for i, (title, text_content) in enumerate(seeds.get(slug, [])):
                chunks.append(EmbeddingChunk(
                    chunk_id=f"{slug}-chunk-{i}",
                    tenant_id=tenant_id,
                    cms_content_id=f"{slug}-cms-{i}",
                    title=title,
                    text=text_content,
                    url=f"https://{slug}.example/menu",
                ))
    except Exception as e:
        # Fall back to original demo chunk if DB lookup fails (shouldn't happen at runtime)
        import logging
        logging.warning(f"RAG seed lookup failed, using fallback: {e}")
        chunks = [EmbeddingChunk(
            chunk_id="demo-pricing",
            tenant_id="demo-tenant",
            cms_content_id="demo-cms-pricing",
            title="Demo Pricing",
            text="Acme Coffee serves single-origin espresso, pour-over coffee, and whole bean varieties.",
            url="https://demo.example/pricing",
        )]

    rag_service = RagService(InMemoryEmbeddingRepository(chunks))
    lead_service = LeadService(repository=InMemoryLeadRepository())
    memory_service = MemoryService(build_memory_store())
    return ChatService(
        memory_service=memory_service,
        router_service=RouterService(rag_tool=rag_service, lead_tool=lead_service),
        agent_service=build_agent_service(rag_service=rag_service, lead_service=lead_service),
    )


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


def get_chat_user(
    token: str | None = Depends(oauth2_scheme),
) -> UserClaims:
    """Accept both widget JWTs (widget_jwt key) and admin JWTs (auth_jwt key)."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    # Try widget key first — most chat traffic is from widget visitors
    try:
        claims = verify_token(token, is_widget=True)
        return UserClaims(
            user_id=claims.get("sub"),
            tenant_id=claims.get("tenant_id"),
            role=claims.get("role", "member"),
        )
    except HTTPException:
        pass
    # Fall back to auth key — admin users or direct API calls
    claims = verify_token(token, is_widget=False)
    return UserClaims(
        user_id=claims.get("sub"),
        tenant_id=claims.get("tenant_id"),
        role=claims.get("role", ""),
    )


@router.post("")
async def chat(
    request: Request,
    body: ChatRequestBody,
    claims: UserClaims = Depends(get_chat_user),
    chat_service: ChatService = Depends(build_chat_service),
    db: Session = Depends(get_db),
):
    tenant_id = claims.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant_id missing from token")

    try:
        classifier_client = getattr(request.app.state, "classifier_client", None)
        guardrail_client = getattr(request.app.state, "guardrail_client", None)
        classification = None
        if classifier_client is not None:
            classification = await classifier_client.classify(
                tenant_id=tenant_id,
                message=body.message,
            )

        if screen_input is not None and guardrail_client is not None:
            decision, reply = await screen_input(
                guardrail_client,
                tenant_id=tenant_id,
                message=body.message,
                tenant_config=guardrails_repo.get_for_tenant(db, tenant_id) or {},
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
            {**body.model_dump(), "tenant_id": tenant_id},
            classification=classification,
        )

        if screen_output is not None and guardrail_client is not None:
            decision, reply = await screen_output(
                guardrail_client,
                tenant_id=tenant_id,
                llm_response=response.message,
                tenant_config=guardrails_repo.get_for_tenant(db, tenant_id) or {},
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
