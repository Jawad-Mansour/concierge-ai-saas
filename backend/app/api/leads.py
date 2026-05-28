# Owner: Ali
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.lead_repo import InMemoryLeadRepository
from app.services.lead_service import LeadService, LeadValidationError


router = APIRouter(prefix="/leads", tags=["leads"])

# Mocked Mohammad-owned persistence/auth dependency:
# replace this module-level in-memory repo when DB sessions, tenant context, and RLS
# are available. Tenant id must eventually come from auth, not request input.
_lead_repo = InMemoryLeadRepository()


class LeadCaptureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    company: str | None = None
    message: str | None = None
    source_url: str | None = None
    trace_id: str | None = None


def get_lead_service() -> LeadService:
    return LeadService(_lead_repo)


@router.post("")
def capture_lead(
    body: LeadCaptureBody,
    lead_service: LeadService = Depends(get_lead_service),
):
    try:
        return asdict(lead_service.capture_lead(body.model_dump()))
    except LeadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_leads(
    # Mocked tenant input until Mohammad's tenant-admin auth dependency exists.
    tenant_id: str = Query(min_length=1),
):
    return [asdict(record) for record in _lead_repo.list_by_tenant(tenant_id=tenant_id)]
