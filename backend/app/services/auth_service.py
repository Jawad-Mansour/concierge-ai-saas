# Owner: Mohammad

"""Auth service: Vault key bootstrap, JWT issue/verify, role-gate dependency."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import hvac
import jwt
from fastapi import HTTPException, status

from app.models.user import Role

# ── Vault bootstrap ──────────────────────────────────────────────────────────

_AUTH_JWT_KEY: str | None = None
_WIDGET_JWT_KEY: str | None = None

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "")

JWT_ALGORITHM = "HS256"
JWT_LIFETIME_SECONDS = int(os.environ.get("JWT_LIFETIME_SECONDS", "3600"))
INVITE_TOKEN_LIFETIME_SECONDS = int(
    os.environ.get("INVITE_TOKEN_LIFETIME_SECONDS", "900")
)
WIDGET_JWT_LIFETIME_SECONDS = int(
    os.environ.get("WIDGET_JWT_LIFETIME_SECONDS", "900")
)


def load_signing_keys() -> None:
    """Read both signing keys from Vault at service startup. Cached in module globals.

    Raises RuntimeError if Vault is unreachable or the keys are absent — the
    service must not start without its signing material.

    Idempotent: returns immediately if keys are already loaded (allows conftest.py
    to pre-inject test keys before lifespan runs, preventing Vault connection in CI).
    """
    global _AUTH_JWT_KEY, _WIDGET_JWT_KEY
    if _AUTH_JWT_KEY is not None and _WIDGET_JWT_KEY is not None:
        return

    client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
    if not client.is_authenticated():
        raise RuntimeError(f"Vault authentication failed (addr={VAULT_ADDR})")

    try:
        auth_secret = client.secrets.kv.v2.read_secret_version(
            path="concierge/auth_jwt", mount_point="secret"
        )
        _AUTH_JWT_KEY = auth_secret["data"]["data"]["signing_key"]
    except Exception as exc:
        raise RuntimeError(f"Failed to read auth_jwt.signing_key from Vault: {exc}") from exc

    try:
        widget_secret = client.secrets.kv.v2.read_secret_version(
            path="concierge/widget_jwt", mount_point="secret"
        )
        _WIDGET_JWT_KEY = widget_secret["data"]["data"]["signing_key"]
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read widget_jwt.signing_key from Vault: {exc}"
        ) from exc


def _auth_key() -> str:
    if _AUTH_JWT_KEY is None:
        raise RuntimeError("Signing keys not loaded — call load_signing_keys() at startup")
    return _AUTH_JWT_KEY


def get_auth_key() -> str:
    """Public accessor for the auth JWT signing key (for tests and tooling)."""
    return _auth_key()


def _widget_key() -> str:
    if _WIDGET_JWT_KEY is None:
        raise RuntimeError("Signing keys not loaded — call load_signing_keys() at startup")
    return _WIDGET_JWT_KEY


# ── JWT issue / verify ───────────────────────────────────────────────────────

def issue_token(
    user_id: str | None,
    tenant_id: str | None,
    role: Role,
    lifetime_seconds: int = JWT_LIFETIME_SECONDS,
) -> str:
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role.value,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=lifetime_seconds),
    }
    return jwt.encode(payload, _auth_key(), algorithm=JWT_ALGORITHM)


def issue_widget_token(tenant_id: str) -> str:
    """Short-lived widget visitor token; signed with the SEPARATE widget key."""
    payload: dict[str, Any] = {
        "sub": None,
        "tenant_id": tenant_id,
        "role": Role.member.value,
        "exp": datetime.now(timezone.utc)
        + timedelta(seconds=WIDGET_JWT_LIFETIME_SECONDS),
    }
    return jwt.encode(payload, _widget_key(), algorithm=JWT_ALGORITHM)


def issue_invite_token(tenant_id: str) -> str:
    """15-min invite token for first-admin registration."""
    payload: dict[str, Any] = {
        "purpose": "first_admin_invite",
        "tenant_id": tenant_id,
        "role": Role.tenant_admin.value,
        "exp": datetime.now(timezone.utc)
        + timedelta(seconds=INVITE_TOKEN_LIFETIME_SECONDS),
    }
    return jwt.encode(payload, _auth_key(), algorithm=JWT_ALGORITHM)


def verify_token(token: str, is_widget: bool = False) -> dict[str, Any]:
    """Verify signature and expiry; return claims dict.

    Raises HTTPException(401) on any verification failure so callers can use
    this directly as a FastAPI dependency building block.
    """
    key = _widget_key() if is_widget else _auth_key()
    # Widget tokens are issued with sub=None; PyJWT 2.x strict mode rejects
    # non-string sub, so we disable that check for widget token verification.
    options = {"verify_sub": False} if is_widget else {}
    try:
        claims = jwt.decode(token, key, algorithms=[JWT_ALGORITHM], options=options)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )
    return claims


