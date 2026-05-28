# Owner: Jana
"""OpenTelemetry tracing initialisation.

Gates export on OTEL_EXPORTER_OTLP_ENDPOINT; when the env var is absent the
global TracerProvider is a no-op SDK provider so CI/tests stay network-free.
"""
from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("backend.tracing")


def init(service_name: str = "backend") -> None:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    logger.info("tracing_initialized exported=%s", bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")))


def instrument_app(app: object) -> None:
    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]


def set_tenant(tenant_id: str) -> None:
    """Attach tenant_id to the current active span, if any."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("tenant_id", tenant_id)
