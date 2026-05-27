# Owner: Jana
"""T044 — same message under two `tenant_id` values → byte-identical responses (SC-008)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import StubBackend


def test_tenant_agnostic_responses(make_app, boot_credential):
    backend = StubBackend({"can you tell me your hours?": ("FAQ", 0.88)})
    app = make_app(backend)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {boot_credential}"}

    r1 = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "can you tell me your hours?"},
        headers=headers,
    )
    r2 = client.post(
        "/predict",
        json={"tenant_id": "tenant-globex", "message": "can you tell me your hours?"},
        headers=headers,
    )

    assert r1.status_code == r2.status_code == 200
    # Byte-identical `(predicted_class, confidence, model_hash)`. tenant_id never
    # appears in the response body.
    assert r1.json() == r2.json()
