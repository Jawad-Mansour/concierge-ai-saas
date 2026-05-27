# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


MemoryRole = Literal["user", "assistant", "tool"]


class MemoryError(ValueError):
    code = "memory_error"


class MemoryValidationError(MemoryError):
    code = "invalid_memory_payload"


class TenantContextError(MemoryError):
    code = "missing_tenant_context"


class MemoryMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    role: MemoryRole
    content: str = Field(min_length=1, max_length=2000)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator("tenant_id", "conversation_id", "content", "trace_id", mode="before")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None


@dataclass(frozen=True)
class MemoryMessage:
    tenant_id: str
    conversation_id: str
    role: MemoryRole
    content: str
    created_at: float
    trace_id: str | None = None


@dataclass
class MemoryEntry:
    messages: list[MemoryMessage] = field(default_factory=list)
    expires_at: float = 0


class MemoryStore(Protocol):
    def append(
        self,
        *,
        key: str,
        message: MemoryMessage,
        ttl_seconds: int,
        max_messages: int,
    ) -> None:
        """Append one scoped message and refresh the key TTL."""

    def get(self, *, key: str) -> list[MemoryMessage]:
        """Return non-expired messages for this scoped key."""

    def clear(self, *, key: str) -> None:
        """Remove all memory for this scoped key."""


class InMemoryMemoryStore:
    """Redis-like memory store for tests and local development."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self.clock = clock
        self.entries: dict[str, MemoryEntry] = {}

    def append(
        self,
        *,
        key: str,
        message: MemoryMessage,
        ttl_seconds: int,
        max_messages: int,
    ) -> None:
        now = self.clock()
        entry = self.entries.get(key)
        if entry is None or entry.expires_at <= now:
            entry = MemoryEntry()
            self.entries[key] = entry
        entry.messages.append(message)
        entry.messages = entry.messages[-max_messages:]
        entry.expires_at = now + ttl_seconds

    def get(self, *, key: str) -> list[MemoryMessage]:
        entry = self.entries.get(key)
        if entry is None:
            return []
        if entry.expires_at <= self.clock():
            self.entries.pop(key, None)
            return []
        return list(entry.messages)

    def clear(self, *, key: str) -> None:
        self.entries.pop(key, None)


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        ttl_seconds: int = 1800,
        max_messages: int = 20,
        clock: Callable[[], float] = time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_messages <= 0:
            raise ValueError("max_messages must be positive")
        self.store = store
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self.clock = clock

    def append_message(self, payload: MemoryMessageInput | dict) -> MemoryMessage:
        request = self._validate(payload)
        message = MemoryMessage(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            role=request.role,
            content=request.content,
            trace_id=request.trace_id,
            created_at=self.clock(),
        )
        self.store.append(
            key=self._key(request.tenant_id, request.conversation_id),
            message=message,
            ttl_seconds=self.ttl_seconds,
            max_messages=self.max_messages,
        )
        return message

    def get_messages(self, *, tenant_id: str, conversation_id: str) -> list[MemoryMessage]:
        tenant_id = tenant_id.strip()
        conversation_id = conversation_id.strip()
        if not tenant_id or not conversation_id:
            raise TenantContextError("tenant and conversation context are required")
        return self.store.get(key=self._key(tenant_id, conversation_id))

    def clear_conversation(self, *, tenant_id: str, conversation_id: str) -> None:
        tenant_id = tenant_id.strip()
        conversation_id = conversation_id.strip()
        if not tenant_id or not conversation_id:
            raise TenantContextError("tenant and conversation context are required")
        self.store.clear(key=self._key(tenant_id, conversation_id))

    def prompt_context(self, *, tenant_id: str, conversation_id: str) -> str:
        messages = self.get_messages(tenant_id=tenant_id, conversation_id=conversation_id)
        return "\n".join(f"{message.role}: {message.content}" for message in messages)

    def _validate(self, payload: MemoryMessageInput | dict) -> MemoryMessageInput:
        try:
            request = (
                payload
                if isinstance(payload, MemoryMessageInput)
                else MemoryMessageInput.model_validate(payload)
            )
        except ValueError as exc:
            raise MemoryValidationError(str(exc)) from exc
        if not request.tenant_id:
            raise TenantContextError("tenant context is required")
        return request

    def _key(self, tenant_id: str, conversation_id: str) -> str:
        return f"tenant:{tenant_id}:conversation:{conversation_id}:memory"
