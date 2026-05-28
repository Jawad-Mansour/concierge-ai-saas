# Owner: Jana
"""OTel + redaction-safe structured logging.

Defensive: no helper here accepts a raw message / llm_response / matched-value
argument. The privacy rule is enforced by the function signatures, not by
convention.
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

from .schemas import Decision, RecognizerName, RuleName

logger = logging.getLogger("guardrails.telemetry")


def init(service_name: str = "guardrails") -> None:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # BatchSpanProcessor — research.md Decision 3 open risk "GIL contention"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def set_evaluation_attrs(
    span: trace.Span,
    *,
    tenant_id: str | None,
    endpoint: str,
    decision: Decision,
    rule_name: RuleName | None,
    latency_ms: float,
    rails_version: str,
) -> None:
    if tenant_id is not None:
        span.set_attribute("tenant_id", tenant_id)
    else:
        span.set_attribute("tenant_id_missing", True)
    span.set_attribute("guardrails.endpoint", endpoint)
    span.set_attribute("guardrails.decision", decision)
    if rule_name is not None:
        span.set_attribute("guardrails.rule_name", rule_name)
    span.set_attribute("guardrails.latency_ms", float(latency_ms))
    span.set_attribute("guardrails.rails_version", rails_version)


def set_redaction_attrs(
    span: trace.Span,
    *,
    recognizers_fired: list[RecognizerName],
    match_count: int,
) -> None:
    span.set_attribute("redaction.recognizers_fired", list(recognizers_fired))
    span.set_attribute("redaction.match_count", int(match_count))


def structured_log(event: str, /, **fields: Any) -> None:
    """Emit a structured log line. Strips message/llm_response/matched_value keys
    defensively so a caller can't leak content even by mistake."""
    for forbidden in ("message", "llm_response", "matched_value", "exception_message"):
        fields.pop(forbidden, None)
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def record_counter(span: trace.Span, name: str) -> None:
    span.add_event(name)
