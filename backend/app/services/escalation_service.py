# Owner: Ali
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.repositories.conversation_repo import (
    ConversationRepository,
    EscalationCreate,
    EscalationPriority,
    EscalationReason,
)


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+"),
]


class EscalationError(ValueError):
    code = "escalation_error"


class TenantContextError(EscalationError):
    code = "missing_tenant_context"


class EscalationValidationError(EscalationError):
    code = "invalid_escalation_payload"


class ConversationNotFoundError(EscalationError):
    code = "conversation_not_found"


class EscalationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1, max_length=160)
    reason: EscalationReason
    summary: str | None = Field(default=None, max_length=1000)
    priority: EscalationPriority = "normal"
    last_user_message_id: str | None = Field(default=None, max_length=160)
    lead_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator(
        "tenant_id",
        "conversation_id",
        "visitor_session_id",
        "summary",
        "last_user_message_id",
        "lead_id",
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
class EscalationResult:
    escalation_id: str
    tenant_id: str
    conversation_id: str
    status: Literal["open"]
    priority: EscalationPriority
    created_at: str
    visitor_message: str
    deduplicated: bool


class EscalationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    def escalate(self, payload: EscalationRequest | dict) -> EscalationResult:
        request = self._validate(payload)
        conversation = self.repository.get_conversation(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
        )
        if conversation is None:
            raise ConversationNotFoundError("conversation not found for tenant")
        if conversation.visitor_session_id != request.visitor_session_id:
            raise EscalationValidationError("visitor session does not match conversation")

        existing = self.repository.find_open_escalation(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
        )
        if existing:
            return self._to_result(existing, deduplicated=True)

        escalation = self.repository.create_escalation(
            EscalationCreate(
                tenant_id=request.tenant_id,
                conversation_id=request.conversation_id,
                visitor_session_id=request.visitor_session_id,
                reason=request.reason,
                priority=request.priority,
                summary=self._redact(request.summary),
                last_user_message_id=request.last_user_message_id,
                lead_id=request.lead_id,
                trace_id=request.trace_id,
            )
        )
        return self._to_result(escalation, deduplicated=False)

    def _validate(self, payload: EscalationRequest | dict) -> EscalationRequest:
        try:
            request = (
                payload
                if isinstance(payload, EscalationRequest)
                else EscalationRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise EscalationValidationError(str(exc)) from exc
        if not request.tenant_id:
            raise TenantContextError("tenant context is required")
        return request

    def _to_result(self, escalation, *, deduplicated: bool) -> EscalationResult:
        return EscalationResult(
            escalation_id=escalation.escalation_id,
            tenant_id=escalation.tenant_id,
            conversation_id=escalation.conversation_id,
            status="open",
            priority=escalation.priority,
            created_at=escalation.created_at.isoformat(),
            visitor_message="I will flag this conversation for a human follow-up.",
            deduplicated=deduplicated,
        )

    def _redact(self, summary: str | None) -> str | None:
        if summary is None:
            return None
        redacted = summary
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
