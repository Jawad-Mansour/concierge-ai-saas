# Owner: Jana
"""T033 — request validation. Malformed requests return 422, no partial evaluation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "payload,endpoint",
    [
        ({"message": "hi"}, "/check/input"),               # missing tenant_id
        ({"tenant_id": "tenant-acme"}, "/check/input"),    # missing message
        ({"tenant_id": "tenant-acme", "message": ""}, "/check/input"),
        ({"tenant_id": "tenant-acme", "message": "   "}, "/check/input"),
        ({"tenant_id": "tenant-acme"}, "/check/output"),   # missing llm_response
        ({"tenant_id": "tenant-acme", "llm_response": ""}, "/check/output"),
    ],
)
def test_malformed_returns_422(payload, endpoint, app, boot_credential):
    client = TestClient(app)
    resp = client.post(
        endpoint, json=payload, headers={"Authorization": f"Bearer {boot_credential}"}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    assert "decision" not in body
