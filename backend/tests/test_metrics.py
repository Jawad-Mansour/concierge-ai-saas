# Owner: Jana
"""Unit tests for metrics.py using InMemoryMetricReader.

Verifies that record_downstream increments _calls and records _latency once
per simulated downstream call, without touching a real OTLP endpoint.
"""
from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import app.utils.metrics as metrics_mod


@pytest.fixture()
def reader():
    """Wire an InMemoryMetricReader directly — bypasses init() so tests run offline.

    The meter is pulled from the local provider rather than the global one:
    OTel's global MeterProvider can only be set once per process, so a per-test
    set_meter_provider() is silently ignored after the first test and the
    reader would never be wired to the meter record_downstream writes to.
    """
    r = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[r])
    meter = provider.get_meter("backend")
    metrics_mod._calls = meter.create_counter(
        "concierge.backend.downstream.calls", unit="1"
    )
    metrics_mod._latency = meter.create_histogram(
        "concierge.backend.downstream.latency", unit="ms"
    )
    yield r
    metrics_mod._calls = None
    metrics_mod._latency = None


def _counter_sum(r: InMemoryMetricReader, name: str) -> int:
    for rm in r.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return sum(dp.value for dp in m.data.data_points)
    return 0


def _histogram_count(r: InMemoryMetricReader, name: str) -> int:
    for rm in r.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return sum(dp.count for dp in m.data.data_points)
    return 0


def test_calls_increments_once(reader):
    metrics_mod.record_downstream(
        tenant_id="acme", target="classifier", outcome="ok", latency_ms=42.0
    )
    assert _counter_sum(reader, "concierge.backend.downstream.calls") == 1


def test_latency_recorded_once(reader):
    metrics_mod.record_downstream(
        tenant_id="acme", target="classifier", outcome="ok", latency_ms=42.0
    )
    assert _histogram_count(reader, "concierge.backend.downstream.latency") == 1


def test_multiple_calls_accumulate(reader):
    metrics_mod.record_downstream(tenant_id="t1", target="classifier", outcome="ok", latency_ms=10.0)
    metrics_mod.record_downstream(tenant_id="t2", target="guardrails", outcome="blocked", latency_ms=20.0)
    assert _counter_sum(reader, "concierge.backend.downstream.calls") == 2
    assert _histogram_count(reader, "concierge.backend.downstream.latency") == 2


def test_noop_before_init():
    orig = metrics_mod._calls
    metrics_mod._calls = None
    try:
        # must not raise
        metrics_mod.record_downstream(tenant_id="t", target="c", outcome="ok", latency_ms=5.0)
    finally:
        metrics_mod._calls = orig


def test_init_offline_safe(monkeypatch):
    """init() with no OTEL_EXPORTER_OTLP_ENDPOINT must not touch the network."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    metrics_mod.init("test-service")
    assert metrics_mod._calls is not None
    assert metrics_mod._latency is not None
