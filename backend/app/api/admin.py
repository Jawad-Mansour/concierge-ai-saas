# Owner: Charbel

"""Admin widget config endpoints — tenant_admin role required."""

import json
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.middleware.auth_middleware import UserClaims, get_current_user
from app.middleware.tenant_context import get_tenant_db
from app.repositories import guardrails_repo

router = APIRouter(prefix="/admin", tags=["admin"])

_WIDGET_COLS = "widget_id::text AS widget_id, allowed_origins, theme, greeting, enabled_tools"


def _require_tenant_admin(claims: UserClaims) -> None:
    if claims.role != "tenant_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_admin role required",
        )


class WidgetConfigResponse(BaseModel):
    widget_id: str
    allowed_origins: list[str]
    theme: dict
    greeting: str
    enabled_tools: list[str]


class WidgetConfigUpdate(BaseModel):
    allowed_origins: list[str]
    theme: dict
    greeting: str
    enabled_tools: list[str]


@router.get("/widget-config", response_model=WidgetConfigResponse)
def get_widget_config(
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)
    row = db.execute(
        text(f"SELECT {_WIDGET_COLS} FROM widget_configs WHERE tenant_id = CAST(:tid AS uuid)"),  # noqa: E501
        {"tid": claims.tenant_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No widget config for this tenant")
    return dict(row._mapping)


@router.put("/widget-config", response_model=WidgetConfigResponse)
def upsert_widget_config(
    body: WidgetConfigUpdate,
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)

    existing = db.execute(
        text("SELECT widget_id FROM widget_configs WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": claims.tenant_id},
    ).fetchone()

    params: dict = {
        "allowed_origins": body.allowed_origins,
        "theme": json.dumps(body.theme),
        "greeting": body.greeting,
        "enabled_tools": body.enabled_tools,
    }

    if existing:
        params["wid"] = str(existing[0])
        row = db.execute(
            text(f"""
                UPDATE widget_configs
                SET allowed_origins = :allowed_origins,
                    theme           = CAST(:theme AS jsonb),
                    greeting        = :greeting,
                    enabled_tools   = :enabled_tools,
                    updated_at      = NOW()
                WHERE widget_id = CAST(:wid AS uuid)
                RETURNING {_WIDGET_COLS}
            """),
            params,
        ).fetchone()
    else:
        params["tid"] = claims.tenant_id
        row = db.execute(
            text(f"""
                INSERT INTO widget_configs
                    (tenant_id, allowed_origins, theme, greeting, enabled_tools)
                VALUES
                    (CAST(:tid AS uuid), :allowed_origins,
                     CAST(:theme AS jsonb), :greeting, :enabled_tools)
                RETURNING {_WIDGET_COLS}
            """),
            params,
        ).fetchone()

    db.commit()
    return dict(row._mapping)  # type: ignore[union-attr]


# ── Guardrails test ───────────────────────────────────────────────────────────

class GuardrailsTestRequest(BaseModel):
    message: str = Field(..., min_length=1)


@router.post("/guardrails-config/test")
async def test_guardrails_config(
    body: GuardrailsTestRequest,
    request: Request,
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)

    guardrail_client = getattr(request.app.state, "guardrail_client", None)
    if guardrail_client is None:
        raise HTTPException(status_code=503, detail="Guardrails sidecar unavailable")

    tenant_config = guardrails_repo.get_for_tenant(db, claims.tenant_id) or {}
    decision = await guardrail_client.check_input(
        tenant_id=claims.tenant_id,
        message=body.message,
        tenant_config=tenant_config,
    )
    return asdict(decision)


@router.get("/widget-config/embed-snippet")
def get_embed_snippet(
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)
    row = db.execute(
        text("SELECT widget_id FROM widget_configs WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": claims.tenant_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No widget config for this tenant")
    snippet = (
        f'<script src="http://localhost:8000/widget.js" '
        f'data-widget-id="{row[0]}"></script>'
    )
    return {"snippet": snippet}


# ── Guardrails config ─────────────────────────────────────────────────────────

class RefusalPersona(BaseModel):
    voice: str
    template: str


class EscalationTrigger(BaseModel):
    kind: Literal["keyword", "intent"]
    value: str


class GuardrailsConfigResponse(BaseModel):
    allowed_topics: list[str] | None = None
    refusal_persona: RefusalPersona | None = None
    escalation_triggers: list[EscalationTrigger] | None = None


class GuardrailsConfigUpdate(BaseModel):
    allowed_topics: list[str] | None = None
    refusal_persona: RefusalPersona | None = None
    escalation_triggers: list[EscalationTrigger] | None = None


_GR_COLS = "allowed_topics, refusal_persona, escalation_triggers"


@router.get("/guardrails-config", response_model=GuardrailsConfigResponse)
def get_guardrails_config(
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)
    row = db.execute(
        text(f"SELECT {_GR_COLS} FROM guardrails_configs WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": claims.tenant_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No guardrails config for this tenant")
    return dict(row._mapping)


@router.put("/guardrails-config", response_model=GuardrailsConfigResponse)
def upsert_guardrails_config(
    body: GuardrailsConfigUpdate,
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> dict:
    _require_tenant_admin(claims)

    existing = db.execute(
        text("SELECT id FROM guardrails_configs WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": claims.tenant_id},
    ).fetchone()

    params: dict = {
        "tid": claims.tenant_id,
        "allowed_topics": body.allowed_topics or [],
        "refusal_persona": (
            json.dumps(body.refusal_persona.model_dump()) if body.refusal_persona else None
        ),
        "escalation_triggers": json.dumps(
            [t.model_dump() for t in body.escalation_triggers] if body.escalation_triggers else []
        ),
    }

    if existing:
        row = db.execute(
            text(f"""
                UPDATE guardrails_configs
                SET allowed_topics       = :allowed_topics,
                    refusal_persona      = CAST(:refusal_persona AS jsonb),
                    escalation_triggers  = CAST(:escalation_triggers AS jsonb),
                    updated_at           = NOW()
                WHERE tenant_id = CAST(:tid AS uuid)
                RETURNING {_GR_COLS}
            """),
            params,
        ).fetchone()
    else:
        row = db.execute(
            text(f"""
                INSERT INTO guardrails_configs
                    (tenant_id, allowed_topics, refusal_persona, escalation_triggers)
                VALUES
                    (CAST(:tid AS uuid), :allowed_topics,
                     CAST(:refusal_persona AS jsonb), CAST(:escalation_triggers AS jsonb))
                RETURNING {_GR_COLS}
            """),
            params,
        ).fetchone()

    db.commit()
    return dict(row._mapping)  # type: ignore[union-attr]
