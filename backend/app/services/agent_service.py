# Owner: Ali
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


AgentToolName = Literal["rag_search", "capture_lead", "escalate"]


class AgentError(ValueError):
    code = "agent_error"


class AgentValidationError(AgentError):
    code = "invalid_agent_payload"


class AgentLoopLimitError(AgentError):
    code = "agent_loop_limit"


class AgentToolError(AgentError):
    code = "agent_tool_error"


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    visitor_session_id: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2048)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=32)
    memory_context: str | None = Field(default=None, max_length=4000)
    trace_id: str | None = Field(default=None, max_length=160)

    @field_validator(
        "tenant_id",
        "conversation_id",
        "visitor_session_id",
        "message",
        "source_url",
        "contact_email",
        "contact_phone",
        "memory_context",
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
class ToolPlan:
    tool_name: AgentToolName | None
    reason: str
    final_response: str | None = None


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: AgentToolName
    payload: dict
    result: object


@dataclass(frozen=True)
class AgentResult:
    final_response: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    stopped_reason: Literal["final", "loop_limit", "tool_unavailable"] = "final"


class AgentPlanner(Protocol):
    def plan(self, *, request: AgentRequest, tool_calls: list[ToolCallRecord]) -> ToolPlan:
        """Choose the next tool or return a final response."""


class ToolRegistry:
    def __init__(
        self,
        *,
        rag_tool=None,
        lead_tool=None,
        escalation_tool=None,
    ) -> None:
        self.rag_tool = rag_tool
        self.lead_tool = lead_tool
        self.escalation_tool = escalation_tool

    def call(self, *, tool_name: AgentToolName, payload: dict):
        if tool_name == "rag_search" and self.rag_tool is not None:
            return self.rag_tool.search(payload)
        if tool_name == "capture_lead" and self.lead_tool is not None:
            return self.lead_tool.capture_lead(payload)
        if tool_name == "escalate" and self.escalation_tool is not None:
            return self.escalation_tool.escalate(payload)
        raise AgentToolError(f"tool unavailable: {tool_name}")


class HeuristicAgentPlanner:
    """Deterministic stand-in for the future tool-calling LLM planner."""

    def plan(self, *, request: AgentRequest, tool_calls: list[ToolCallRecord]) -> ToolPlan:
        called = {call.tool_name for call in tool_calls}
        message = request.message.lower()
        if not tool_calls:
            if any(term in message for term in ("human", "person", "representative")):
                return ToolPlan("escalate", "visitor requested a human")
            if request.contact_email or request.contact_phone:
                return ToolPlan("capture_lead", "visitor provided contact info")
            return ToolPlan("rag_search", "answer from tenant knowledge")
        if "rag_search" in called and "capture_lead" not in called and (
            request.contact_email or request.contact_phone
        ):
            return ToolPlan("capture_lead", "follow up after answering question")
        return ToolPlan(
            None,
            "enough context gathered",
            final_response="I handled the request with the available tenant tools.",
        )


class AgentService:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        planner: AgentPlanner | None = None,
        max_iterations: int = 3,
    ) -> None:
        if max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        self.tool_registry = tool_registry
        self.planner = planner or HeuristicAgentPlanner()
        self.max_iterations = max_iterations

    def run(self, payload: AgentRequest | dict) -> AgentResult:
        request = self._validate(payload)
        tool_calls: list[ToolCallRecord] = []
        for _iteration in range(self.max_iterations):
            plan = self.planner.plan(request=request, tool_calls=tool_calls)
            if plan.tool_name is None:
                return AgentResult(
                    final_response=plan.final_response or "I handled the request.",
                    tool_calls=tool_calls,
                    stopped_reason="final",
                )
            tool_payload = self._tool_payload(plan.tool_name, request)
            try:
                result = self.tool_registry.call(
                    tool_name=plan.tool_name,
                    payload=tool_payload,
                )
            except AgentToolError:
                return AgentResult(
                    final_response="I need a human or another service to finish this request.",
                    tool_calls=tool_calls,
                    stopped_reason="tool_unavailable",
                )
            tool_calls.append(
                ToolCallRecord(
                    tool_name=plan.tool_name,
                    payload=tool_payload,
                    result=result,
                )
            )
        return AgentResult(
            final_response="I reached the tool limit for this turn.",
            tool_calls=tool_calls,
            stopped_reason="loop_limit",
        )

    def _validate(self, payload: AgentRequest | dict) -> AgentRequest:
        try:
            return (
                payload
                if isinstance(payload, AgentRequest)
                else AgentRequest.model_validate(payload)
            )
        except ValueError as exc:
            raise AgentValidationError(str(exc)) from exc

    def _tool_payload(self, tool_name: AgentToolName, request: AgentRequest) -> dict:
        base = {
            "tenant_id": request.tenant_id,
            "conversation_id": request.conversation_id,
            "trace_id": request.trace_id,
        }
        if tool_name == "rag_search":
            return {
                **base,
                "query": request.message,
                "top_k": 5,
                "filters": {"published_only": True},
            }
        if tool_name == "capture_lead":
            return {
                **base,
                "visitor_session_id": request.visitor_session_id,
                "intent": request.message,
                "email": request.contact_email,
                "phone": request.contact_phone,
                "source_url": request.source_url,
                "classification": {"label": "agent", "confidence": 1.0},
            }
        if tool_name == "escalate":
            return {
                **base,
                "visitor_session_id": request.visitor_session_id,
                "reason": "human_requested",
                "summary": request.message,
                "priority": "normal",
            }
        raise AgentToolError(f"unknown tool: {tool_name}")
