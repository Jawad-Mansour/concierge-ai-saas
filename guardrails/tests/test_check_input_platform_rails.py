# Owner: Jana
"""T015 — replay both probe-set JSONs against /check/input and assert the
(decision, rule_name) pairs match the expected values."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_PROBE_DIR = Path(__file__).resolve().parents[2] / "evals" / "security"
_INJECTION = json.loads((_PROBE_DIR / "injection_cases.json").read_text())
_CROSS_TENANT = json.loads((_PROBE_DIR / "cross_tenant_cases.json").read_text())


@pytest.mark.parametrize("probe", _INJECTION + _CROSS_TENANT, ids=lambda p: p["message"][:50])
def test_platform_rails(probe, app, boot_credential):
    client = TestClient(app)
    resp = client.post(
        "/check/input",
        json={"tenant_id": "tenant-acme", "message": probe["message"], "tenant_config": {}},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == probe["expected_decision"]
    if probe["expected_decision"] == "block":
        assert body["rule_name"] == probe["expected_rule_name"]
        assert body["action"] == "safe_refusal"
        # block bodies MUST NOT carry payload (data-model.md §EvaluationResponseBlock)
        assert "payload" not in body
        assert body["refusal_text"] is None
    else:
        assert body["payload"] == probe["message"]
        assert body["redaction"] is None
