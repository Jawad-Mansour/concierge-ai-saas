# Owner: Jana
"""HTTP client for the guardrails sidecar.

On any HTTP error / network exception, map to a local fail-closed block
(`rule_name="engine_error"`, `action="fallback_response"`) so the chat path
stays consistent with the sidecar's own fail-closed semantics.

Raises `UnknownGuardrailAction` on receiving an `action` value outside the
closed vocabulary (data-model.md §Action — Principle VI: no silent ignore).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger("backend.guardrail_service")

Decision = Literal["pass", "block"]
KNOWN_ACTIONS: set[str] = {"safe_refusal", "tenant_refusal", "escalate", "fallback_response"}


class UnknownGuardrailAction(Exception):
    """Raised when the sidecar returns an action not in the closed vocabulary."""


@dataclass(frozen=True)
class GuardrailDecision:
    decision: Decision
    rule_name: str | None
    action: str | None
    refusal_text: str | None
    payload: str | None
    redaction_recognizers: list[str]
    redaction_match_count: int


def _fail_closed() -> GuardrailDecision:
    return GuardrailDecision(
        decision="block",
        rule_name="engine_error",
        action="fallback_response",
        refusal_text=None,
        payload=None,
        redaction_recognizers=[],
        redaction_match_count=0,
    )


class GuardrailClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_credential: str,
        timeout_s: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = {"Authorization": f"Bearer {service_credential}"}
        self._timeout = httpx.Timeout(timeout_s)
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    async def _call(self, endpoint: str, payload: dict) -> GuardrailDecision:
        try:
            resp = await self._client.post(
                f"{self._base_url}{endpoint}",
                json=payload,
                headers=self._auth,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed on every error
            logger.warning("guardrail_client_network_error: %s", type(exc).__name__)
            return _fail_closed()

        if resp.status_code != 200:
            logger.warning("guardrail_client_http_error status=%s", resp.status_code)
            return _fail_closed()

        body = resp.json()
        decision = body.get("decision")
        if decision == "block":
            action = body.get("action")
            if action not in KNOWN_ACTIONS:
                raise UnknownGuardrailAction(f"unknown action from guardrails: {action!r}")
            return GuardrailDecision(
                decision="block",
                rule_name=body.get("rule_name"),
                action=action,
                refusal_text=body.get("refusal_text"),
                payload=None,
                redaction_recognizers=[],
                redaction_match_count=0,
            )

        # pass
        redaction = body.get("redaction") or {}
        return GuardrailDecision(
            decision="pass",
            rule_name=None,
            action=None,
            refusal_text=None,
            payload=body.get("payload"),
            redaction_recognizers=list(redaction.get("recognizers_fired") or []),
            redaction_match_count=int(redaction.get("match_count") or 0),
        )

    async def check_input(self, *, tenant_id: str, message: str, tenant_config: dict | None = None) -> GuardrailDecision:
        return await self._call(
            "/check/input",
            {"tenant_id": tenant_id, "message": message, "tenant_config": tenant_config or {}},
        )

    async def check_output(self, *, tenant_id: str, llm_response: str, tenant_config: dict | None = None) -> GuardrailDecision:
        return await self._call(
            "/check/output",
            {"tenant_id": tenant_id, "llm_response": llm_response, "tenant_config": tenant_config or {}},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
