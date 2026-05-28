# Owner: Mohammad

from typing import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.middleware.auth_middleware import UserClaims, get_current_user
from app.services.tracing_service import set_tenant #ANA JANA ZEDTO

def get_tenant_db(
    claims: UserClaims = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Generator[Session, None, None]:
    """FastAPI dependency: sets app.tenant_id for the duration of the request.

    The set_config call uses transaction scope (third arg = true) as a second
    safety net. The finally block is the primary guard against connection-pool
    leakage — a connection reused by another tenant would carry the wrong value
    if this reset were missing.

    tenant_id always comes from the verified JWT claim. Values in the request
    body are ignored by callers that use this dependency.
    """
    tenant_id = claims.tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="tenant_id missing from token",
        )
    set_tenant(tenant_id) #HAYDA ANA JANA ZEDTO
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    try:
        yield db
    finally:
        db.execute(
            text("SELECT set_config('app.tenant_id', '', true)")
        )
