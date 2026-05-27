# Owner: Jana
"""T029 — fail-closed on timeout AND on every exception path. The reserved
`confidence == 0.0` sentinel (data-model.md §Confidence values) holds for both."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


class SlowBackend:
    def predict(self, message: str):
        time.sleep(0.5)
        return ("FAQ", 0.99)


class RaisingBackend:
    def predict(self, message: str):
        raise RuntimeError("simulated engine failure")


def test_timeout_returns_unknown_zero(make_app, boot_credential, span_exporter):
    app = make_app(SlowBackend(), timeout_s=0.05)
    client = TestClient(app)
    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "anything"},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["predicted_class"] == "UNKNOWN"
    assert body["confidence"] == 0.0

    matching = [
        s
        for s in span_exporter.get_finished_spans()
        if s.attributes and s.attributes.get("classifier.degraded") is True
    ]
    assert matching, "no span carried classifier.degraded=true on timeout"


def test_engine_exception_returns_unknown_zero(make_app, boot_credential, span_exporter):
    app = make_app(RaisingBackend())
    client = TestClient(app)
    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "anything"},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["predicted_class"] == "UNKNOWN"
    assert body["confidence"] == 0.0
