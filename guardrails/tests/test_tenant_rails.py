# Owner: Jana
"""T027 — tenant rails: allowed_topics + escalation_triggers + per-tenant independence."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _post(client, body, token):
    return client.post(
        "/check/input",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_on_topic_passes(app, boot_credential):
    client = TestClient(app)
    resp = _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "What are your hours today?",
            "tenant_config": {"allowed_topics": ["hours", "contact", "products"]},
        },
        boot_credential,
    )
    body = resp.json()
    assert body["decision"] == "pass"


def test_off_topic_blocks_with_tenant_refusal(app, boot_credential):
    client = TestClient(app)
    resp = _post(
        client,
        {
            "tenant_id": "tenant-acme",
            "message": "Tell me a joke about giraffes.",
            "tenant_config": {
                "allowed_topics": ["hours", "contact", "products"],
                "refusal_persona": {
                    "voice": "formal",
                    "template": "I can help with {topic}. {reason}",
                },
            },
        },
        boot_credential,
    )
    body = resp.json()
    assert body["decision"] == "block"
    assert body["rule_name"] == "off_topic"
    assert body["action"] == "tenant_refusal"
    assert body["refusal_text"] is not None
    # placeholders filled
    assert "hours" in body["refusal_text"]


def test_escalation_trigger_overrides_off_topic(app, boot_credential):
    """Escalation triggers override off_topic per data-model.md ordering."""
    client = TestClient(app)
    resp = _post(
        client,
        {
            "tenant_id": "tenant-acme",
            # message is off-topic AND contains the escalation keyword
            "message": "This is urgent, I need to speak to a manager about giraffes.",
            "tenant_config": {
                "allowed_topics": ["hours", "contact", "products"],
                "escalation_triggers": [{"kind": "keyword", "value": "urgent"}],
            },
        },
        boot_credential,
    )
    body = resp.json()
    assert body["decision"] == "block"
    assert body["rule_name"] == "escalation_trigger"
    assert body["action"] == "escalate"
    assert body["refusal_text"] is None


def test_two_tenants_independent_decisions(app, boot_credential):
    client = TestClient(app)
    message = "Tell me a joke about giraffes."

    permissive = _post(
        client,
        {"tenant_id": "tenant-permissive", "message": message, "tenant_config": {}},
        boot_credential,
    ).json()
    restrictive = _post(
        client,
        {
            "tenant_id": "tenant-restrictive",
            "message": message,
            "tenant_config": {"allowed_topics": ["hours"]},
        },
        boot_credential,
    ).json()

    assert permissive["decision"] == "pass"
    assert restrictive["decision"] == "block"
    assert restrictive["rule_name"] == "off_topic"
