# Owner: Jana
"""T023 — per-recognizer unit tests for the redaction wire-up.

Asserts:
- payload contains `<RECOGNIZER>` placeholder in place of the value;
- redaction.recognizers_fired carries exactly the firing recognizer name;
- match_count equals the number of occurrences (multi-occurrence test).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CASES = [
    ("EMAIL_ADDRESS", "Contact me at hello+test@example.com please."),
    ("PHONE_NUMBER", "Call +1-555-010-1234 when ready."),
    ("CREDIT_CARD", "Charge 4111-1111-1111-1111 today."),
    ("US_SSN", "SSN 123-45-6789 for verification."),
    ("GENERIC_BEARER_TOKEN", "Token eyJabcdefghij.klmnopqrstuv.wxyzabcdefghijklm."),
    ("HOSTED_LLM_API_KEY_ANTHROPIC", "Anthropic key sk-ant-api03-AAAAAAAAAAAAAAAAAAAA."),
    ("HOSTED_LLM_API_KEY_OPENAI", "OpenAI key sk-BBBBBBBBBBBBBBBBBBBBBBBBBBBB."),
]


@pytest.mark.parametrize("recognizer,message", CASES, ids=[r for r, _ in CASES])
def test_single_recognizer(recognizer, message, app, boot_credential):
    client = TestClient(app)
    resp = client.post(
        "/check/input",
        json={"tenant_id": "tenant-acme", "message": message, "tenant_config": {}},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == "pass"
    assert body["redaction"] is not None
    assert recognizer in body["redaction"]["recognizers_fired"]
    assert body["redaction"]["match_count"] >= 1
    assert f"<{recognizer}>" in body["payload"]


def test_multi_occurrence_counts_each(app, boot_credential):
    client = TestClient(app)
    message = "Emails: alice@example.com and bob@example.com."
    resp = client.post(
        "/check/input",
        json={"tenant_id": "tenant-acme", "message": message, "tenant_config": {}},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["redaction"]["match_count"] == 2
    # Deduplicated — EMAIL_ADDRESS appears once even though two matches.
    assert body["redaction"]["recognizers_fired"] == ["EMAIL_ADDRESS"]


def test_anthropic_key_does_not_match_openai_pattern(app, boot_credential):
    """Research.md Decision 2 open risk — `sk-ant-…` must NOT be tagged as OpenAI."""
    client = TestClient(app)
    message = "Leaked anthropic key: sk-ant-api03-AAAAAAAAAAAAAAAAAAAA."
    resp = client.post(
        "/check/input",
        json={"tenant_id": "tenant-acme", "message": message, "tenant_config": {}},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    body = resp.json()
    fired = body["redaction"]["recognizers_fired"]
    assert "HOSTED_LLM_API_KEY_ANTHROPIC" in fired
    assert "HOSTED_LLM_API_KEY_OPENAI" not in fired
