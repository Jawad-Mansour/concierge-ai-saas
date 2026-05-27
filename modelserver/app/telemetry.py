# Owner: Jana
"""OTel + structured-log helpers.

Per Principle IX-relevant hygiene (research.md cross-cutting confirmations):
no helper in this module accepts the visitor's `message` text — the rule is
held in code, not just convention.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .schemas import IntentClass

logger = logging.getLogger("modelserver.telemetry")


def init(service_name: str = "modelserver") -> None:
    """Set up the global TracerProvider + OTLP exporter."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def set_prediction_attrs(
    span: trace.Span,
    *,
    tenant_id: str | None,
    predicted_class: IntentClass,
    confidence: float,
    latency_ms: float,
    model_hash: str,
    degraded: bool,
) -> None:
    if tenant_id is not None:
        span.set_attribute("tenant_id", tenant_id)
    else:
        span.set_attribute("tenant_id_missing", True)
    span.set_attribute("classifier.predicted_class", predicted_class)
    span.set_attribute("classifier.confidence", float(confidence))
    span.set_attribute("classifier.latency_ms", float(latency_ms))
    span.set_attribute("classifier.model_hash", model_hash)
    span.set_attribute("classifier.degraded", bool(degraded))


def structured_log(event: str, /, **fields: Any) -> None:
    """Emit a structured log line.

    Defensive: `message` keys are stripped before serialization. This is the
    code-level guarantee that the visitor's text never leaves the request scope.
    """
    fields.pop("message", None)
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def record_counter(span: trace.Span, name: str) -> None:
    span.add_event(name)
