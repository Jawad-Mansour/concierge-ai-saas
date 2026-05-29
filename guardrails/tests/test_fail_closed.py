# Owner: Jana
"""T032 — fail-closed coverage. Any internal exception → block(engine_error / config_error)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import rails_engine, redaction


def _post(client, body, token):
    return client.post(
        "/check/input",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_engine_failure_returns_engine_error(monkeypatch, app, boot_credential):
    def boom(*_a, **_kw):
        raise RuntimeError("simulated rails engine failure")

    monkeypatch.setattr(rails_engine, "evaluate_platform_rails", boom)

    client = TestClient(app)
    resp = _post(
        client,
        {"tenant_id": "tenant-acme", "message": "hello", "tenant_config": {}},
        boot_credential,
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["decision"] == "block"
    assert body["rule_name"] == "engine_error"
    assert body["action"] == "fallback_response"
    assert body["refusal_text"] is None
    assert "payload" not in body


def test_tenant_config_parse_error_returns_config_error(monkeypatch, app, boot_credential):
    def parse_boom(*_a, **_kw):
        raise ValueError("simulated tenant_config parse failure")

    monkeypatch.setattr(rails_engine, "evaluate_tenant_rails", parse_boom)

    client = TestClient(app)
    resp = _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "hello",
            "tenant_config": {"allowed_topics": ["hours"]},
        },
        boot_credential,
    )
    body = resp.json()
    assert body["decision"] == "block"
    assert body["rule_name"] == "config_error"
    assert body["action"] == "fallback_response"


def test_redaction_engine_failure_returns_engine_error(monkeypatch, app, boot_credential):
    def boom(*_a, **_kw):
        raise RuntimeError("simulated redactor failure")

    monkeypatch.setattr(redaction, "redact", boom)

    client = TestClient(app)
    resp = _post(
        client,
        {"tenant_id": "tenant-acme", "message": "benign message", "tenant_config": {}},
        boot_credential,
    )
    body = resp.json()
    assert body["decision"] == "block"
    assert body["rule_name"] == "engine_error"
