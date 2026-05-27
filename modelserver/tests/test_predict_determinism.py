# Owner: Jana
"""T015 — same body twice → byte-identical JSON (US1 acceptance scenario)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import StubBackend


def test_predict_byte_identical(make_app, boot_credential):
    backend = StubBackend({"hello there": ("FAQ", 0.84)})
    app = make_app(backend)
    client = TestClient(app)

    payload = {"tenant_id": "tenant-acme", "message": "hello there"}
    headers = {"Authorization": f"Bearer {boot_credential}"}

    r1 = client.post("/predict", json=payload, headers=headers)
    r2 = client.post("/predict", json=payload, headers=headers)

    assert r1.status_code == r2.status_code == 200
    assert r1.content == r2.content
