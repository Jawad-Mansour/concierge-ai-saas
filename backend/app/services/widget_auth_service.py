# Owner: Charbel

"""Widget auth service — origin validation and token issuance."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories import widget_repo
from app.services import auth_service


def exchange_token(widget_id: str, origin: str, db: Session) -> dict:
    """Validate widget_id exists and origin is allowed.

    Returns {"token": str, "expires_in": 900}.
    Raises HTTPException(404) if widget not found.
    Raises HTTPException(403) if origin not in allowed_origins.
    """
    row = widget_repo.get_by_widget_id(widget_id, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Widget not found")
    if origin not in row["allowed_origins"]:
        raise HTTPException(status_code=403, detail="Origin not allowed")
    token = auth_service.issue_widget_token(str(row["tenant_id"]))
    return {"token": token, "expires_in": 900}
