# Owner: Jana
"""Wires `guardrail_service.GuardrailClient` into the chat request path.

Maps the closed `action` vocabulary returned by the sidecar onto visitor-facing
behavior:
  - safe_refusal     → platform-default refusal text
  - tenant_refusal   → use the sidecar's composed `refusal_text`
  - escalate         → fire the human-handoff trigger; agent does NOT respond
  - fallback_response → fixed "sorry, something went wrong" message

Receiving an unknown action raises `UnknownGuardrailAction` from the client
(Principle VI — no silent ignore).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.guardrail_service import GuardrailClient, GuardrailDecision

PLATFORM_REFUSAL_TEXT = (
    "I can't help with that request. If you have another question, I'm happy to help."
)
FALLBACK_TEXT = "Sorry, something went wrong. Please try again."


@dataclass(frozen=True)
class VisitorReply:
    text: str | None
    escalate: bool


def render_for_visitor(decision: GuardrailDecision) -> VisitorReply:
    if decision.decision == "pass":
        return VisitorReply(text=decision.payload, escalate=False)

    if decision.action == "safe_refusal":
        return VisitorReply(text=PLATFORM_REFUSAL_TEXT, escalate=False)
    if decision.action == "tenant_refusal":
        return VisitorReply(text=decision.refusal_text or PLATFORM_REFUSAL_TEXT, escalate=False)
    if decision.action == "escalate":
        return VisitorReply(text=None, escalate=True)
    if decision.action == "fallback_response":
        return VisitorReply(text=FALLBACK_TEXT, escalate=False)

    raise RuntimeError(f"render_for_visitor: unknown action {decision.action!r}")


async def screen_input(
    client: GuardrailClient,
    *,
    tenant_id: str,
    message: str,
    tenant_config: dict | None = None,
) -> tuple[GuardrailDecision, VisitorReply]:
    decision = await client.check_input(
        tenant_id=tenant_id, message=message, tenant_config=tenant_config
    )
    return decision, render_for_visitor(decision)


async def screen_output(
    client: GuardrailClient,
    *,
    tenant_id: str,
    llm_response: str,
    tenant_config: dict | None = None,
) -> tuple[GuardrailDecision, VisitorReply]:
    decision = await client.check_output(
        tenant_id=tenant_id, llm_response=llm_response, tenant_config=tenant_config
    )
    return decision, render_for_visitor(decision)
