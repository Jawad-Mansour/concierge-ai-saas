# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.escalation_service import EscalationResult
from app.services.lead_service import LeadCaptureResult
from app.services.rag_service import RagResult


RouteDecision = Literal["drop", "rag", "capture_lead", "escalate", "agent"]


class RouterError(ValueError):
    code = "router_error"


class RouterValidationError(RouterError):
    code = "invalid_router_payload"


class TenantContextError(RouterError):
    code = "missing_tenant_context"


class ClassifierClient(Protocol):
    def classify(self, message: str) -> tuple[str, float]:
        """Return an intent label and confidence for one inbound visitor message."""


class RagTool(Protocol):
    def search(self, payload: dict) -> RagResult:
        """Run tenant-scoped RAG retrieval."""


class LeadTool(Protocol):
    def capture_lead(self, payload: dict) -> LeadCaptureResult:
        """Capture a tenant-scoped lead."""


class EscalationTool(Protocol):
    def escalate(self, payload: dict) -> EscalationResult:
        """Escalate a tenant-scoped conversation."""


class RouterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2048)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator(
        "tenant_id",
        "conversation_id",
        "visitor_session_id",
        "message",
        "source_url",
        "contact_email",
        "contact_phone",
        "trace_id",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    degraded: bool = False


@dataclass(frozen=True)
class RouterResult:
    decision: RouteDecision
    classification: Classification
    response: str | None = None
    rag_result: RagResult | None = None
    lead_result: LeadCaptureResult | None = None
    escalation_result: EscalationResult | None = None


class KeywordClassifier:
    """Small deterministic fallback until the modelserver classifier is wired."""

    SPAM_TERMS = ("free money", "crypto pump", "buy followers")
    HUMAN_TERMS = ("human", "person", "agent", "representative", "call me")
    LEAD_TERMS = ("pricing", "quote", "demo", "contact", "sales", "buy")

    def classify(self, message: str) -> tuple[str, float]:
        normalized = message.lower()
        if any(term in normalized for term in self.SPAM_TERMS):
            return "spam", 0.95
        if any(term in normalized for term in self.HUMAN_TERMS):
            return "human_handoff", 0.9
        if any(term in normalized for term in self.LEAD_TERMS):
            return "sales", 0.82
        if "?" in normalized:
            return "faq", 0.78
        return "unknown", 0.35


class RouterService:
    def __init__(
        self,
        *,
        classifier: ClassifierClient | None = None,
        rag_tool: RagTool | None = None,
        lead_tool: LeadTool | None = None,
        escalation_tool: EscalationTool | None = None,
        direct_confidence_threshold: float = 0.7,
    ) -> None:
        self.classifier = classifier or KeywordClassifier()
        self.rag_tool = rag_tool
        self.lead_tool = lead_tool
        self.escalation_tool = escalation_tool
        self.direct_confidence_threshold = direct_confidence_threshold

    def route(
        self,
        payload: RouterRequest | dict,
        *,
        classification: Classification | object | None = None,
    ) -> RouterResult:
        request = self._validate(payload)
        classification = self._classification(request, classification)

        if (
            classification.label == "spam"
            and classification.confidence >= self.direct_confidence_threshold
        ):
            return RouterResult(decision="drop", classification=classification)

        if classification.confidence < self.direct_confidence_threshold:
            return RouterResult(decision="agent", classification=classification)

        if classification.label in {"faq", "support"}:
            return self._route_rag(request, classification)
        if classification.label in {"sales", "lead"}:
            return self._route_lead(request, classification)
        if classification.label in {"human_handoff", "escalate"}:
            return self._route_escalation(request, classification)

        return RouterResult(decision="agent", classification=classification)

    def _route_rag(
        self,
        request: RouterRequest,
        classification: Classification,
    ) -> RouterResult:
        if self.rag_tool is None:
            return RouterResult(decision="agent", classification=classification)
        result = self.rag_tool.search(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "query": request.message,
                "top_k": 5,
                "filters": {"published_only": True},
                "trace_id": request.trace_id,
            }
        )
        if result.status != "ok":
            return RouterResult(decision="agent", classification=classification, rag_result=result)
        return RouterResult(decision="rag", classification=classification, rag_result=result)

    def _route_lead(
        self,
        request: RouterRequest,
        classification: Classification,
    ) -> RouterResult:
        if self.lead_tool is None:
            return RouterResult(decision="agent", classification=classification)
        if not request.contact_email and not request.contact_phone:
            return RouterResult(
                decision="capture_lead",
                classification=classification,
                response="Could you share an email or phone number so we can follow up?",
            )
        result = self.lead_tool.capture_lead(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "visitor_session_id": request.visitor_session_id,
                "intent": request.message,
                "email": request.contact_email,
                "phone": request.contact_phone,
                "source_url": request.source_url,
                "classification": {
                    "label": classification.label,
                    "confidence": classification.confidence,
                },
                "trace_id": request.trace_id,
            }
        )
        return RouterResult(
            decision="capture_lead",
            classification=classification,
            lead_result=result,
            response="Thanks, I captured your details for follow-up.",
        )

    def _route_escalation(
        self,
        request: RouterRequest,
        classification: Classification,
    ) -> RouterResult:
        if self.escalation_tool is None:
            return RouterResult(decision="agent", classification=classification)
        result = self.escalation_tool.escalate(
            {
                "tenant_id": request.tenant_id,
                "conversation_id": request.conversation_id,
                "visitor_session_id": request.visitor_session_id,
                "reason": "human_requested",
                "summary": request.message,
                "priority": "normal",
                "trace_id": request.trace_id,
            }
        )
        return RouterResult(
            decision="escalate",
            classification=classification,
            escalation_result=result,
            response=result.visitor_message,
        )

    def _validate(self, payload: RouterRequest | dict) -> RouterRequest:
        try:
            request = (
                payload
                if isinstance(payload, RouterRequest)
                else RouterRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise RouterValidationError(str(exc)) from exc
        if not request.tenant_id:
            raise TenantContextError("tenant context is required")
        return request

    def _classification(
        self,
        request: RouterRequest,
        classification: Classification | object | None,
    ) -> Classification:
        if classification is None:
            label, confidence = self.classifier.classify(request.message)
            return Classification(label=self._normalize_label(label), confidence=confidence)

        raw_label = getattr(
            classification,
            "predicted_class",
            getattr(classification, "label", None),
        )
        confidence = float(getattr(classification, "confidence", 0.0))
        degraded = bool(getattr(classification, "degraded", False))
        if degraded:
            return Classification(label="unknown", confidence=0.0, degraded=True)
        return Classification(
            label=self._normalize_label(str(raw_label)),
            confidence=confidence,
            degraded=False,
        )

    def _normalize_label(self, label: str) -> str:
        normalized = label.strip().lower()
        return {
            "spam": "spam",
            "faq": "faq",
            "account_ops": "agent",
            "hard_question": "agent",
            "unknown": "unknown",
            "support": "support",
            "sales": "sales",
            "lead": "lead",
            "human_handoff": "human_handoff",
            "escalate": "escalate",
        }.get(normalized, "unknown")
