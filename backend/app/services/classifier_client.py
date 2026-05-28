# Owner: Jana
"""HTTP client for the classifier service.

Lives on the backend side. The router calls `classify(...)` on every visitor
message and uses the prediction to keep most traffic off the agent path.

Fail-closed contract (plan.md §V, spec Assumptions): on any HTTP error or
network exception, return the local `(UNKNOWN, 0.0)` mapping so the router's
semantics match the classifier's reserved-zero convention. The classifier
itself never returns `confidence == 0.0` except on degraded paths, so this
mapping preserves the data-model.md §Confidence values invariant.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from app.utils import metrics

logger = logging.getLogger("backend.classifier_client")

IntentClass = Literal["SPAM", "FAQ", "ACCOUNT_OPS", "HARD_QUESTION", "UNKNOWN"]


@dataclass(frozen=True)
class ClassifierResponse:
    predicted_class: IntentClass
    confidence: float
    model_hash: str
    degraded: bool  # True when the local fail-closed branch was taken


class ClassifierClient:
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

    async def classify(self, *, tenant_id: str, message: str) -> ClassifierResponse:
        start = time.perf_counter()
        outcome = "ok"
        try:
            try:
                resp = await self._client.post(
                    f"{self._base_url}/predict",
                    json={"tenant_id": tenant_id, "message": message},
                    headers=self._auth,
                    timeout=self._timeout,
                )
            except Exception as exc:  # noqa: BLE001 — fail-closed on every error
                outcome = "error"
                logger.warning("classifier_client_network_error: %s", type(exc).__name__)
                return ClassifierResponse(
                    predicted_class="UNKNOWN",
                    confidence=0.0,
                    model_hash="",
                    degraded=True,
                )

            if resp.status_code != 200:
                outcome = "error"
                logger.warning("classifier_client_http_error status=%s", resp.status_code)
                return ClassifierResponse(
                    predicted_class="UNKNOWN",
                    confidence=0.0,
                    model_hash="",
                    degraded=True,
                )

            body = resp.json()
            result = ClassifierResponse(
                predicted_class=body["predicted_class"],
                confidence=float(body["confidence"]),
                model_hash=body["model_hash"],
                degraded=body["confidence"] == 0.0,
            )
            if result.degraded:
                outcome = "degraded"
            return result
        finally:
            metrics.record_downstream(
                tenant_id=tenant_id,
                target="classifier",
                outcome=outcome,
                latency_ms=(time.perf_counter() - start) * 1000,
            )

    async def aclose(self) -> None:
        await self._client.aclose()
