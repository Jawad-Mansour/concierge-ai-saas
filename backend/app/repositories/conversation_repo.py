# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4


EscalationReason = Literal[
    "human_requested",
    "out_of_scope",
    "low_confidence",
    "safety_or_guardrail",
    "technical_failure",
]
EscalationPriority = Literal["low", "normal", "high"]
EscalationStatus = Literal["open", "resolved"]


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    tenant_id: str
    visitor_session_id: str


@dataclass(frozen=True)
class EscalationCreate:
    tenant_id: str
    conversation_id: str
    visitor_session_id: str
    reason: EscalationReason
    priority: EscalationPriority = "normal"
    summary: str | None = None
    last_user_message_id: str | None = None
    lead_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class EscalationRecord:
    escalation_id: str
    tenant_id: str
    conversation_id: str
    visitor_session_id: str
    reason: EscalationReason
    priority: EscalationPriority
    status: EscalationStatus = "open"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    summary: str | None = None
    last_user_message_id: str | None = None
    lead_id: str | None = None
    trace_id: str | None = None


class ConversationRepository(Protocol):
    def get_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        """Return a conversation only when it belongs to the requested tenant."""

    def find_open_escalation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
    ) -> EscalationRecord | None:
        """Return an open escalation for this tenant conversation, if present."""

    def create_escalation(self, escalation: EscalationCreate) -> EscalationRecord:
        """Persist an open escalation scoped to a tenant conversation."""


class InMemoryConversationRepository:
    """Small repository implementation for escalation tests and local smoke slices."""

    def __init__(
        self,
        conversations: list[ConversationRecord] | None = None,
    ) -> None:
        self.conversations = conversations or []
        self.escalations: list[EscalationRecord] = []

    def add_conversation(self, conversation: ConversationRecord) -> None:
        self.conversations.append(conversation)

    def get_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
    ) -> ConversationRecord | None:
        for conversation in self.conversations:
            if (
                conversation.tenant_id == tenant_id
                and conversation.conversation_id == conversation_id
            ):
                return conversation
        return None

    def find_open_escalation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
    ) -> EscalationRecord | None:
        for escalation in self.escalations:
            if (
                escalation.tenant_id == tenant_id
                and escalation.conversation_id == conversation_id
                and escalation.status == "open"
            ):
                return escalation
        return None

    def create_escalation(self, escalation: EscalationCreate) -> EscalationRecord:
        record = EscalationRecord(
            escalation_id=str(uuid4()),
            tenant_id=escalation.tenant_id,
            conversation_id=escalation.conversation_id,
            visitor_session_id=escalation.visitor_session_id,
            reason=escalation.reason,
            priority=escalation.priority,
            summary=escalation.summary,
            last_user_message_id=escalation.last_user_message_id,
            lead_id=escalation.lead_id,
            trace_id=escalation.trace_id,
        )
        self.escalations.append(record)
        return record
