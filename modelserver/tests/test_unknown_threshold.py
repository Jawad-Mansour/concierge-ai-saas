# Owner: Jana
"""T016 — orchestrator forces UNKNOWN when raw confidence < threshold,
preserving the raw probability as the response confidence (data-model.md
§Confidence values: 0.0 is reserved for the timeout-degraded path, NOT for
low-confidence)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import StubBackend


def test_low_confidence_forces_unknown(make_app, boot_credential):
    backend = StubBackend({"hey": ("SPAM", 0.05)})
    app = make_app(backend, unknown_threshold=0.25)
    client = TestClient(app)

    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "hey"},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predicted_class"] == "UNKNOWN"
    # raw confidence preserved — NOT collapsed to 0.0
    assert body["confidence"] == 0.05
