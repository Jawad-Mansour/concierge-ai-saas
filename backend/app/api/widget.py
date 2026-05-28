# Owner: Charbel

"""Widget API — public token exchange endpoint."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import widget_auth_service

router = APIRouter(prefix="/widget", tags=["widget"])


class TokenRequest(BaseModel):
    widget_id: str
    origin: str


class TokenResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/token", response_model=TokenResponse)
def get_widget_token(
    req: TokenRequest,
    db: Session = Depends(get_db),
) -> dict:
    return widget_auth_service.exchange_token(
        widget_id=req.widget_id,
        origin=req.origin,
        db=db,
    )
