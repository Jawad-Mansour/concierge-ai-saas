# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


ConversationStatus = Literal["open", "escalated", "closed"]
MessageRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    tenant_id: str
    visitor_session_id: str
    status: ConversationStatus = "open"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    tenant_id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None
