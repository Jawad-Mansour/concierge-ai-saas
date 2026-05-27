# Owner: Mohammad

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.services.auth_service import verify_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@dataclass
class UserClaims:
    user_id: str | None
    tenant_id: str | None
    role: str


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> UserClaims:
    """FastAPI dependency: validates the Bearer token and returns verified claims.

    tenant_id always comes from the signed JWT claim — never from the request body.
    Callers that need tenant DB isolation must use get_tenant_db (tenant_context.py).
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = verify_token(token)
    return UserClaims(
        user_id=claims.get("sub"),
        tenant_id=claims.get("tenant_id"),
        role=claims.get("role", ""),
    )
