# Owner: Jana
"""T023 — auth probe per FR-004. The 401 body must be byte-identical across
missing and malformed credentials."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import StubBackend


def test_valid_credential_succeeds(make_app, boot_credential):
    app = make_app(StubBackend({"hi": ("FAQ", 0.9)}))
    client = TestClient(app)
    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "hi"},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {"predicted_class", "confidence", "model_hash"} <= body.keys()


def test_missing_authorization_returns_opaque_401(make_app):
    app = make_app(StubBackend({}))
    client = TestClient(app)
    resp = client.post("/predict", json={"tenant_id": "tenant-acme", "message": "hi"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthenticated"}


def test_malformed_credential_returns_opaque_401(make_app):
    app = make_app(StubBackend({}))
    client = TestClient(app)
    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "hi"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthenticated"}


def test_401_bodies_are_byte_identical(make_app):
    app = make_app(StubBackend({}))
    client = TestClient(app)
    payload = {"tenant_id": "tenant-acme", "message": "hi"}

    r_missing = client.post("/predict", json=payload)
    r_malformed = client.post(
        "/predict", json=payload, headers={"Authorization": "Bearer wrong-token"}
    )
    r_wrong_scheme = client.post(
        "/predict", json=payload, headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )

    assert r_missing.status_code == r_malformed.status_code == r_wrong_scheme.status_code == 401
    assert r_missing.content == r_malformed.content == r_wrong_scheme.content
