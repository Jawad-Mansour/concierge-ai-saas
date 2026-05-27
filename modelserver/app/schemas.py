# Owner: Jana
"""Pydantic v2 wire schemas for the classifier service.

Authoritative against `specs/001-classifier-service/contracts/shared-schemas.yaml`
and `data-model.md` — PRs that change one without the other are rejected in review.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

IntentClass = Literal["SPAM", "FAQ", "ACCOUNT_OPS", "HARD_QUESTION", "UNKNOWN"]


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Opaque tenant identifier. Used only for tracing/rate-limit attribution; "
            "MUST NOT influence the prediction (FR-006/SC-008)."
        ),
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=16384,
    )

    @field_validator("message")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        # Defense-in-depth: min_length=1 catches "" but Pydantic does not strip
        # whitespace before length-checking. FR-005 / edge case "empty or
        # whitespace-only message text" must produce a 422, not a prediction.
        if not v.strip():
            raise ValueError("message must not be empty or whitespace-only")
        return v


class PredictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicted_class: IntentClass
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Reserved: confidence == 0.0 is the timeout-degraded fallback. "
            "confidence > 0.0 with predicted_class == UNKNOWN means the model "
            "evaluated normally but fell below the UNKNOWN-escalation threshold."
        ),
    )
    model_hash: str = Field(
        ...,
        pattern=r"^[0-9a-f]{12}$",
        description="12-character lowercase-hex truncation of the loaded artifact's SHA-256.",
    )


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: Literal["unauthenticated"] = "unauthenticated"
