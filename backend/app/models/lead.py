# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


LeadStatus = Literal["new", "contacted", "qualified", "closed", "spam"]


@dataclass(frozen=True)
class Lead:
    lead_id: str
    tenant_id: str
    conversation_id: str
    visitor_session_id: str
    intent: str
    status: LeadStatus = "new"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    company: str | None = None
    message: str | None = None
    source_url: str | None = None
    lead_score: float | None = None
    classification_label: str | None = None
    classification_confidence: float | None = None
    trace_id: str | None = None
