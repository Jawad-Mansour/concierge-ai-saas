# Owner: Mohammad

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.middleware.auth_middleware import UserClaims, get_current_user
from app.models.user import Role
from app.repositories import user_repo
from app.services.auth_service import (
    JWT_LIFETIME_SECONDS,
    WIDGET_JWT_LIFETIME_SECONDS,
    issue_token,
    issue_widget_token,
    verify_token,
)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    invite_token: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = JWT_LIFETIME_SECONDS


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    # tenant_id and role come from the invite token — NEVER from body
    try:
        claims = verify_token(body.invite_token)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invite_token is invalid or expired",
        )
    if claims.get("purpose") != "first_admin_invite":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invite_token is not an invite token",
        )

    existing = user_repo.get_by_email(db, str(body.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    tenant_id = claims["tenant_id"]
    role = Role(claims["role"])

    user = user_repo.create(
        db,
        email=str(body.email),
        plain_password=body.password,
        role=role,
        tenant_id=tenant_id,
    )
    db.commit()
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
    }


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = user_repo.get_by_email(db, str(body.email))
    if user is None or not user_repo.verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive"
        )
    # Check tenant is active (if user is scoped to a tenant)
    if user.tenant_id:
        from app.repositories.tenant_repo import get_by_id
        tenant = get_by_id(db, user.tenant_id)
        if tenant and not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is suspended"
            )

    access_token = issue_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role
    )
    return TokenResponse(access_token=access_token)


@router.post("/widget-token", response_model=TokenResponse)
def widget_token(widget_id: str, origin: str, db: Session = Depends(get_db)):
    """Exchange a public widget_id for a short-lived, tenant-scoped visitor JWT.

    The token is what the backend trusts for all subsequent /chat requests.
    CORS and CSP are defense-in-depth around this token, never the boundary itself.

    Server-side origin check: reject a mismatch with 403 — a CORS error only happens
    in a browser; a non-browser caller ignores CORS entirely.
    """
    from sqlalchemy import text

    # Look up tenant via widget_configs table (Charbel populates widget_id column)
    row = db.execute(
        text(
            "SELECT wc.tenant_id, t.allowed_origins "
            "FROM widget_configs wc "
            "JOIN tenants t ON t.id = wc.tenant_id "
            "WHERE wc.widget_id = :wid AND t.is_active = true"
        ),
        {"wid": widget_id},
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")

    tenant_id, allowed_origins = row[0], row[1]

    # Server-side origin check — reject unknown origins with a real 403
    if allowed_origins and origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed for this widget",
        )

    token = issue_widget_token(tenant_id)
    return TokenResponse(access_token=token, expires_in=WIDGET_JWT_LIFETIME_SECONDS)


@router.post("/refresh", response_model=TokenResponse)
def refresh(claims: UserClaims = Depends(get_current_user)):
    # Reissue with same sub/tenant/role but fresh expiry
    role = Role(claims.role)
    access_token = issue_token(
        user_id=claims.user_id, tenant_id=claims.tenant_id, role=role
    )
    return TokenResponse(access_token=access_token)
