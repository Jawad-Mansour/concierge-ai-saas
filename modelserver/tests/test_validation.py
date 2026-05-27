# Owner: Jana
"""T030 — schema validation per FR-005. Malformed requests return 422 with no
partial prediction body."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import StubBackend


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": "tenant-acme", "message": ""},
        {"tenant_id": "tenant-acme", "message": "   "},
        {"message": "hi"},  # missing tenant_id
        {"tenant_id": "tenant-acme"},  # missing message
    ],
    ids=["empty_message", "whitespace_message", "missing_tenant_id", "missing_message"],
)
def test_malformed_requests_return_422(payload, make_app, boot_credential):
    app = make_app(StubBackend({}))
    client = TestClient(app)
    resp = client.post(
        "/predict",
        json=payload,
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    assert "predicted_class" not in body
    assert "confidence" not in body
