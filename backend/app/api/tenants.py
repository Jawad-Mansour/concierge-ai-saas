# Owner: Mohammad

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.middleware.auth_middleware import UserClaims, get_current_user
from app.models.user import Role
from app.services import tenant_service

router = APIRouter()


def _require_tenant_manager(claims: UserClaims = Depends(get_current_user)) -> UserClaims:
    if claims.role != Role.tenant_manager.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_manager role required",
        )
    return claims


# ── Schemas ──────────────────────────────────────────────────────────────────

class ProvisionRequest(BaseModel):
    name: str
    slug: str
    allowed_origins: list[str] = []


class SuspendRequest(BaseModel):
    reason: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
def provision_tenant(
    body: ProvisionRequest,
    claims: UserClaims = Depends(_require_tenant_manager),
    db: Session = Depends(get_db),
):
    from sqlalchemy.exc import IntegrityError

    try:
        result = tenant_service.provision_tenant(
            db,
            name=body.name,
            slug=body.slug,
            allowed_origins=body.allowed_origins,
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Slug already taken"
        )
    return result


@router.post("/{tenant_id}/invite")
def invite_admin(
    tenant_id: str,
    claims: UserClaims = Depends(_require_tenant_manager),
    db: Session = Depends(get_db),
):
    result = tenant_service.invite_first_admin(db, tenant_id=tenant_id, actor_id=claims.user_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return result


@router.patch("/{tenant_id}/suspend")
def suspend_tenant(
    tenant_id: str,
    body: SuspendRequest = SuspendRequest(),
    claims: UserClaims = Depends(_require_tenant_manager),
    db: Session = Depends(get_db),
):
    result = tenant_service.suspend_tenant(
        db, tenant_id=tenant_id, actor_id=claims.user_id, reason=body.reason
    )
    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return result


@router.delete("/{tenant_id}")
def erase_tenant(
    tenant_id: str,
    claims: UserClaims = Depends(_require_tenant_manager),
    db: Session = Depends(get_db),
):
    result = tenant_service.erase_tenant(db, tenant_id=tenant_id, actor_id=claims.user_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return result


@router.get("/{tenant_id}/cost")
def get_cost(
    tenant_id: str,
    period: Literal["week", "month"] = Query(default="week"),
    claims: UserClaims = Depends(_require_tenant_manager),
    db: Session = Depends(get_db),
):
    return tenant_service.get_cost_this_week(db, tenant_id=tenant_id)
