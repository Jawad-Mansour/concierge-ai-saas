# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.agent_service import AgentService
from app.services.memory_service import MemoryService
from app.services.rag_answer_service import RagAnswerGenerator
from app.services.router_service import Classification, RouterService


class ChatError(ValueError):
    code = "chat_error"


class ChatValidationError(ChatError):
    code = "invalid_chat_payload"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2048)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator(
        "tenant_id",
        "conversation_id",
        "visitor_session_id",
        "message",
        "source_url",
        "contact_email",
        "contact_phone",
        "trace_id",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None


@dataclass(frozen=True)
class ChatResponse:
    conversation_id: str
    decision: str
    message: str
    trace_id: str | None = None


class ChatService:
    def __init__(
        self,
        *,
        memory_service: MemoryService,
        router_service: RouterService,
        agent_service: AgentService | None = None,
        rag_answer_generator: RagAnswerGenerator | None = None,
    ) -> None:
        self.memory_service = memory_service
        self.router_service = router_service
        self.agent_service = agent_service
        self.rag_answer_generator = rag_answer_generator

    def handle_message(
        self,
        payload: ChatRequest | dict,
        *,
        classification: Classification | object | None = None,
    ) -> ChatResponse:
        request = self._validate(payload)
        self.memory_service.append_message(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "role": "user",
                "content": request.message,
                "trace_id": request.trace_id,
            }
        )
        memory_context = self.memory_service.prompt_context(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
        )
        router_result = self.router_service.route(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "visitor_session_id": request.visitor_session_id,
                "message": request.message,
                "source_url": request.source_url,
                "contact_email": request.contact_email,
                "contact_phone": request.contact_phone,
                "trace_id": request.trace_id,
            },
            classification=classification,
        )
        response_text = self._response_text(
            request=request,
            decision=router_result.decision,
            router_response=router_result.response,
            rag_context=(
                router_result.rag_result.answer_context
                if router_result.rag_result is not None
                else []
            ),
            memory_context=memory_context,
        )
        self.memory_service.append_message(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "role": "assistant",
                "content": response_text,
                "trace_id": request.trace_id,
            }
        )
        return ChatResponse(
            conversation_id=request.conversation_id,
            decision=router_result.decision,
            message=response_text,
            trace_id=request.trace_id,
        )

    def _response_text(
        self,
        *,
        request: ChatRequest,
        decision: str,
        router_response: str | None,
        rag_context: list[str],
        memory_context: str,
    ) -> str:
        if router_response:
            return router_response
        if decision == "drop":
            return "I cannot help with that request."
        if decision == "rag" and rag_context:
            if self.rag_answer_generator is not None:
                return self.rag_answer_generator.generate(
                    question=request.message,
                    contexts=rag_context,
                    tenant_id=request.tenant_id,
                )
            return rag_context[0]
        if decision == "agent":
            if self.agent_service is None:
                return "I need a little more help to answer that. I can flag this for follow-up."
            result = self.agent_service.run(
                {
                    "tenant_id": request.tenant_id,
                    "conversation_id": request.conversation_id,
                    "visitor_session_id": request.visitor_session_id,
                    "message": request.message,
                    "source_url": request.source_url,
                    "contact_email": request.contact_email,
                    "contact_phone": request.contact_phone,
                    "memory_context": memory_context,
                    "trace_id": request.trace_id,
                }
            )
            return result.final_response
        return "I handled your request."

    def _validate(self, payload: ChatRequest | dict) -> ChatRequest:
        try:
            return (
                payload if isinstance(payload, ChatRequest) else ChatRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise ChatValidationError(str(exc)) from exc
