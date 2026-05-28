# Owner: Jana
"""T037 — auth probe per FR-008. 401 body byte-identical across all failure modes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def benign_payload_input():
    return {"tenant_id": "tenant-acme", "message": "hi", "tenant_config": {}}


@pytest.fixture
def benign_payload_output():
    return {"tenant_id": "tenant-acme", "llm_response": "hello!", "tenant_config": {}}


@pytest.mark.parametrize("endpoint,payload_key", [
    ("/check/input", "benign_payload_input"),
    ("/check/output", "benign_payload_output"),
])
def test_valid_credential_succeeds(endpoint, payload_key, request, app, boot_credential):
    client = TestClient(app)
    payload = request.getfixturevalue(payload_key)
    resp = client.post(
        endpoint, json=payload, headers={"Authorization": f"Bearer {boot_credential}"}
    )
    assert resp.status_code == 200
    assert "decision" in resp.json()


@pytest.mark.parametrize("endpoint,payload_key", [
    ("/check/input", "benign_payload_input"),
    ("/check/output", "benign_payload_output"),
])
def test_401_bodies_are_byte_identical(endpoint, payload_key, request, app):
    client = TestClient(app)
    payload = request.getfixturevalue(payload_key)

    r_missing = client.post(endpoint, json=payload)
    r_malformed = client.post(
        endpoint, json=payload, headers={"Authorization": "Bearer wrong-token"}
    )
    r_wrong_scheme = client.post(
        endpoint, json=payload, headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )

    for r in (r_missing, r_malformed, r_wrong_scheme):
        assert r.status_code == 401
        assert r.json() == {"detail": "unauthenticated"}
    assert r_missing.content == r_malformed.content == r_wrong_scheme.content
