# Owner: Ali
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.repositories.lead_repo import LeadCreate, LeadRepository


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,24}$")


class LeadCaptureError(ValueError):
    code = "lead_capture_error"


class TenantContextError(LeadCaptureError):
    code = "missing_tenant_context"


class LeadValidationError(LeadCaptureError):
    code = "invalid_lead_payload"


class LeadRateLimitError(LeadCaptureError):
    code = "lead_rate_limited"


class LeadClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip().lower()


class LeadCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1, max_length=160)
    intent: str = Field(min_length=1, max_length=500)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2048)
    lead_score: float | None = Field(default=None, ge=0, le=1)
    classification: LeadClassification | None = None
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator(
        "tenant_id",
        "conversation_id",
        "visitor_session_id",
        "intent",
        "email",
        "phone",
        "name",
        "company",
        "message",
        "source_url",
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

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if not EMAIL_RE.match(normalized):
            raise ValueError("email must be a valid address")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"\s+", " ", value)
        if not PHONE_RE.match(normalized):
            raise ValueError("phone must be a valid phone number")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("source_url must be an HTTP(S) URL")
        return value

    @model_validator(mode="after")
    def require_contact_and_block_spam(self) -> LeadCaptureRequest:
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        if self.classification and self.classification.label == "spam":
            raise ValueError("spam leads must not be captured")
        return self


@dataclass(frozen=True)
class LeadCaptureResult:
    lead_id: str
    tenant_id: str
    conversation_id: str
    status: Literal["new"]
    created_at: str
    deduplicated: bool


class LeadWriteRateLimiter:
    def __init__(self, *, max_writes: int = 3, window_seconds: int = 300) -> None:
        self.max_writes = max_writes
        self.window_seconds = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, *, tenant_id: str, visitor_session_id: str) -> None:
        key = (tenant_id, visitor_session_id)
        now = monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.max_writes:
            raise LeadRateLimitError("lead write rate limit exceeded")
        events.append(now)


class LeadService:
    def __init__(
        self,
        repository: LeadRepository,
        *,
        rate_limiter: LeadWriteRateLimiter | None = None,
    ) -> None:
        self.repository = repository
        self.rate_limiter = rate_limiter or LeadWriteRateLimiter()

    def capture_lead(self, payload: LeadCaptureRequest | dict) -> LeadCaptureResult:
        request = self._validate(payload)
        self.rate_limiter.check(
            tenant_id=request.tenant_id,
            visitor_session_id=request.visitor_session_id,
        )

        existing = self.repository.find_open_by_contact(
            tenant_id=request.tenant_id,
            email=request.email,
            phone=request.phone,
        )
        if existing:
            return LeadCaptureResult(
                lead_id=existing.lead_id,
                tenant_id=existing.tenant_id,
                conversation_id=existing.conversation_id,
                status="new",
                created_at=existing.created_at.isoformat(),
                deduplicated=True,
            )

        record = self.repository.create(
            LeadCreate(
                tenant_id=request.tenant_id,
                conversation_id=request.conversation_id,
                visitor_session_id=request.visitor_session_id,
                intent=request.intent,
                email=request.email,
                phone=request.phone,
                name=request.name,
                company=request.company,
                message=request.message,
                source_url=request.source_url,
                lead_score=request.lead_score,
                classification_label=(
                    request.classification.label if request.classification else None
                ),
                classification_confidence=(
                    request.classification.confidence if request.classification else None
                ),
                trace_id=request.trace_id,
            )
        )
        return LeadCaptureResult(
            lead_id=record.lead_id,
            tenant_id=record.tenant_id,
            conversation_id=record.conversation_id,
            status="new",
            created_at=record.created_at.isoformat(),
            deduplicated=False,
        )

    def _validate(self, payload: LeadCaptureRequest | dict) -> LeadCaptureRequest:
        try:
            request = (
                payload
                if isinstance(payload, LeadCaptureRequest)
                else LeadCaptureRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise LeadValidationError(str(exc)) from exc
        if not request.tenant_id:
            raise TenantContextError("tenant context is required")
        return request
