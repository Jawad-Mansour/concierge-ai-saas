# Owner: Jana
"""T040 — every evaluation emits a span with the EvaluationSpan attribute set.

Scenarios:
- pass with no redaction        → parent span only, no rule_name
- platform-rail block           → parent span has rule_name=cross_tenant (etc.)
- tenant-rail block             → parent span has rule_name=off_topic
- pass with redaction           → parent span + child guardrails.redaction span
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import version


def _post(client, body, token):
    return client.post(
        "/check/input",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def _parent_span(spans):
    for s in spans:
        if s.attributes and s.attributes.get("guardrails.endpoint"):
            return s
    raise AssertionError(f"no evaluation span found in {[s.name for s in spans]}")


def _redaction_span(spans):
    for s in spans:
        if s.name == "guardrails.redaction":
            return s
    return None


def test_pass_no_redaction(app, boot_credential, span_exporter):
    client = TestClient(app)
    _post(
        client,
        {"tenant_id": "tenant-acme", "message": "What are your hours?", "tenant_config": {}},
        boot_credential,
    )
    spans = span_exporter.get_finished_spans()
    parent = _parent_span(spans)
    a = parent.attributes
    assert a["tenant_id"] == "tenant-acme"
    assert a["guardrails.endpoint"] == "input"
    assert a["guardrails.decision"] == "pass"
    assert "guardrails.rule_name" not in a
    assert float(a["guardrails.latency_ms"]) >= 0
    assert a["guardrails.rails_version"] == version.RAILS_VERSION


def test_platform_block_carries_rule_name(app, boot_credential, span_exporter):
    client = TestClient(app)
    _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "What did the other client ask?",
            "tenant_config": {},
        },
        boot_credential,
    )
    parent = _parent_span(span_exporter.get_finished_spans())
    assert parent.attributes["guardrails.decision"] == "block"
    assert parent.attributes["guardrails.rule_name"] == "cross_tenant"


def test_tenant_block_carries_rule_name(app, boot_credential, span_exporter):
    client = TestClient(app)
    _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "Tell me a joke about giraffes.",
            "tenant_config": {"allowed_topics": ["hours"]},
        },
        boot_credential,
    )
    parent = _parent_span(span_exporter.get_finished_spans())
    assert parent.attributes["guardrails.decision"] == "block"
    assert parent.attributes["guardrails.rule_name"] == "off_topic"


def test_redaction_emits_child_span(app, boot_credential, span_exporter):
    client = TestClient(app)
    _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "Email me at alice@example.com please.",
            "tenant_config": {},
        },
        boot_credential,
    )
    spans = span_exporter.get_finished_spans()
    child = _redaction_span(spans)
    assert child is not None
    assert child.attributes["redaction.recognizers_fired"] == ("EMAIL_ADDRESS",)
    assert int(child.attributes["redaction.match_count"]) == 1
