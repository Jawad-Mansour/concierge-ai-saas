# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class LeadCreate:
    tenant_id: str
    conversation_id: str
    visitor_session_id: str
    intent: str
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


@dataclass(frozen=True)
class LeadRecord:
    lead_id: str
    tenant_id: str
    conversation_id: str
    visitor_session_id: str
    intent: str
    status: str = "new"
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


class LeadRepository(Protocol):
    def find_open_by_contact(
        self,
        *,
        tenant_id: str,
        email: str | None,
        phone: str | None,
    ) -> LeadRecord | None:
        """Return an open lead for this tenant and contact, if one exists."""

    def create(self, lead: LeadCreate) -> LeadRecord:
        """Persist a tenant-scoped lead."""


class InMemoryLeadRepository:
    """Small repository implementation for service tests and local smoke slices."""

    def __init__(self) -> None:
        self.records: list[LeadRecord] = []

    def find_open_by_contact(
        self,
        *,
        tenant_id: str,
        email: str | None,
        phone: str | None,
    ) -> LeadRecord | None:
        for record in self.records:
            same_tenant = record.tenant_id == tenant_id
            same_email = email is not None and record.email == email
            same_phone = phone is not None and record.phone == phone
            if same_tenant and record.status == "new" and (same_email or same_phone):
                return record
        return None

    def create(self, lead: LeadCreate) -> LeadRecord:
        record = LeadRecord(
            lead_id=str(uuid4()),
            tenant_id=lead.tenant_id,
            conversation_id=lead.conversation_id,
            visitor_session_id=lead.visitor_session_id,
            intent=lead.intent,
            email=lead.email,
            phone=lead.phone,
            name=lead.name,
            company=lead.company,
            message=lead.message,
            source_url=lead.source_url,
            lead_score=lead.lead_score,
            classification_label=lead.classification_label,
            classification_confidence=lead.classification_confidence,
            trace_id=lead.trace_id,
        )
        self.records.append(record)
        return record
