# Owner: Jana
"""Orchestrator: timer → backend.predict (under timeout) → threshold → response.

Fail-closed (Principle VI): every path through `backend.predict(...)` is wrapped
in a single try/except that translates timeouts and exceptions into the canonical
`(UNKNOWN, 0.0)` response with `classifier.degraded=true` on the span.
`0.0` is reserved exclusively for this path (data-model.md §Confidence values).
"""

from __future__ import annotations

import asyncio
import time

from opentelemetry import trace

from . import telemetry, version
from .inference import InferenceBackend
from .schemas import IntentClass, PredictResponse

_tracer = trace.get_tracer("modelserver.classifier")


async def classify(
    *,
    backend: InferenceBackend,
    message: str,
    tenant_id: str | None,
    unknown_threshold: float,
    timeout_s: float = 0.200,
) -> PredictResponse:
    # tenant_id is used for span attribution only; MUST NOT enter the inference
    # path (FR-006/SC-008). `backend.predict(...)` below receives only `message`.
    span = trace.get_current_span()
    model_hash = version.get_model_hash()
    started = time.perf_counter()
    degraded = False
    predicted_class: IntentClass
    confidence: float

    try:
        predicted_class, raw_confidence = await asyncio.wait_for(
            asyncio.to_thread(backend.predict, message),
            timeout=timeout_s,
        )
        # Apply the UNKNOWN-threshold rule. `tenant_id` MUST NOT influence this
        # decision — it is used for span attribution only (FR-006/SC-008).
        if predicted_class != "UNKNOWN" and raw_confidence < unknown_threshold:
            predicted_class = "UNKNOWN"
        confidence = float(raw_confidence)
    except TimeoutError:
        degraded = True
        predicted_class = "UNKNOWN"
        confidence = 0.0
        telemetry.record_counter(span, "classifier.timeout")
        telemetry.structured_log(
            "classifier_timeout",
            tenant_id=tenant_id,
            model_hash=model_hash,
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed catches every engine error
        degraded = True
        predicted_class = "UNKNOWN"
        confidence = 0.0
        telemetry.record_counter(span, "classifier.engine_error")
        telemetry.structured_log(
            "classifier_engine_error",
            tenant_id=tenant_id,
            model_hash=model_hash,
            error=type(exc).__name__,
        )

    latency_ms = (time.perf_counter() - started) * 1000.0
    telemetry.set_prediction_attrs(
        span,
        tenant_id=tenant_id,
        predicted_class=predicted_class,
        confidence=confidence,
        latency_ms=latency_ms,
        model_hash=model_hash,
        degraded=degraded,
    )
    return PredictResponse(
        predicted_class=predicted_class,
        confidence=confidence,
        model_hash=model_hash,
    )
