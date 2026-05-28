# Owner: Jana
"""Pydantic v2 wire schemas for the guardrails sidecar.

Authoritative against `specs/002-guardrails-sidecar/contracts/shared-schemas.yaml`
and `data-model.md` — PRs that change one without the other are rejected in review.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

Decision = Literal["pass", "block"]
RuleName = Literal[
    "prompt_injection",
    "jailbreak",
    "cross_tenant",
    "off_topic",
    "escalation_trigger",
    "engine_error",
    "config_error",
]
Action = Literal["safe_refusal", "tenant_refusal", "escalate", "fallback_response"]
RecognizerName = Literal[
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "GENERIC_BEARER_TOKEN",
    "HOSTED_LLM_API_KEY_ANTHROPIC",
    "HOSTED_LLM_API_KEY_OPENAI",
]

TenantId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]


class RefusalPersona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: str
    template: str


class EscalationTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["keyword", "intent"]
    value: str


class TenantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_topics: list[str] | None = None
    refusal_persona: RefusalPersona | None = None
    escalation_triggers: list[EscalationTrigger] | None = None


class RedactionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recognizers_fired: list[RecognizerName]
    match_count: int = Field(ge=0)


def _reject_whitespace(v: str) -> str:
    if not v.strip():
        raise ValueError("must not be empty or whitespace-only")
    return v


class EvaluationRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: TenantId
    message: str = Field(min_length=1, max_length=16384)
    tenant_config: TenantConfig = Field(default_factory=TenantConfig)

    @field_validator("message")
    @classmethod
    def _msg_nonempty(cls, v: str) -> str:
        return _reject_whitespace(v)


class EvaluationRequestOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: TenantId
    llm_response: str = Field(min_length=1, max_length=32768)
    tenant_config: TenantConfig = Field(default_factory=TenantConfig)

    @field_validator("llm_response")
    @classmethod
    def _resp_nonempty(cls, v: str) -> str:
        return _reject_whitespace(v)


class EvaluationResponsePass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["pass"] = "pass"
    payload: str
    redaction: RedactionMetadata | None


class EvaluationResponseBlock(BaseModel):
    """MUST NOT carry the original payload or any substring (Principle VI / IX)."""

    model_config = ConfigDict(extra="forbid")
    decision: Literal["block"] = "block"
    rule_name: RuleName
    action: Action
    refusal_text: str | None


EvaluationResponse = Annotated[
    Union[EvaluationResponsePass, EvaluationResponseBlock],
    Field(discriminator="decision"),
]


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: Literal["unauthenticated"] = "unauthenticated"
