# Owner: Jana
"""Real OTel Metrics SDK implementation (Counter + Histogram, not the span-event stub
the service telemetry modules use). No helper here ever takes visitor/model text —
only IDs, enums, numbers.
"""
from __future__ import annotations

import logging
import os

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger("backend.metrics")

_calls: metrics.Counter | None = None
_latency: metrics.Histogram | None = None


def init(service_name: str = "backend") -> None:
    global _calls, _latency

    resource = Resource.create({"service.name": service_name})
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if endpoint:
        provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
        )
    else:
        # No reader — records to nothing; keeps CI/tests offline-safe.
        provider = MeterProvider(resource=resource)

    metrics.set_meter_provider(provider)
    meter = metrics.get_meter("backend")

    _calls = meter.create_counter(
        "concierge.backend.downstream.calls",
        unit="1",
    )
    _latency = meter.create_histogram(
        "concierge.backend.downstream.latency",
        unit="ms",
    )
    logger.info("metrics_initialized exported=%s", bool(endpoint))


def record_downstream(
    *,
    tenant_id: str | None,
    target: str,
    outcome: str,
    latency_ms: float,
) -> None:
    if _calls is None:
        return

    # tracing uses a tenant_id_missing flag, but metric attribute sets must be stable,
    # so None coerces to "unknown" instead.
    #
    # tenant_id as a label is unbounded cardinality; accepted at project scale and
    # required for the constitution's per-tenant cost attribution. If it ever bites,
    # drop tenant_id here and use traces for per-tenant.
    attrs = {
        "tenant_id": tenant_id or "unknown",
        "target": target,
        "outcome": outcome,
    }
    _calls.add(1, attrs)
    _latency.record(latency_ms, attrs)  # type: ignore[union-attr]
