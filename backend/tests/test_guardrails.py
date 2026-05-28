# Owner: Jana
"""T050 — end-to-end-shaped tests for the GuardrailClient + screen_input/output
middleware.

The sidecar is stubbed via httpx.MockTransport so the test is hermetic; the
real-sinks probe-string test (T022) covers Principle IX end-to-end against a
running container.
"""
from __future__ import annotations

import httpx
import pytest

from app.middleware.guardrails import (
    FALLBACK_TEXT,
    PLATFORM_REFUSAL_TEXT,
    screen_input,
    screen_output,
)
from app.services.guardrail_service import GuardrailClient, UnknownGuardrailAction


def _client_with(handler) -> GuardrailClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return GuardrailClient(
        base_url="http://guardrails:8002",
        service_credential="test-token",
        client=http,
    )


@pytest.mark.asyncio
async def test_pass_returns_payload_to_visitor():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"decision": "pass", "payload": "hello!", "redaction": None},
        )

    client = _client_with(handler)
    decision, reply = await screen_input(client, tenant_id="tenant-acme", message="hi")
    assert decision.decision == "pass"
    assert reply.text == "hello!"
    assert reply.escalate is False
    await client.aclose()


@pytest.mark.asyncio
async def test_platform_block_renders_platform_refusal():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "block",
                "rule_name": "prompt_injection",
                "action": "safe_refusal",
                "refusal_text": None,
            },
        )

    client = _client_with(handler)
    _, reply = await screen_input(client, tenant_id="tenant-acme", message="hi")
    assert reply.text == PLATFORM_REFUSAL_TEXT
    assert reply.escalate is False
    await client.aclose()


@pytest.mark.asyncio
async def test_tenant_refusal_delivers_composed_text():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "block",
                "rule_name": "off_topic",
                "action": "tenant_refusal",
                "refusal_text": "We focus on bakery questions only.",
            },
        )

    client = _client_with(handler)
    _, reply = await screen_input(client, tenant_id="tenant-acme", message="hi")
    assert reply.text == "We focus on bakery questions only."
    assert reply.escalate is False
    await client.aclose()


@pytest.mark.asyncio
async def test_escalate_triggers_handoff():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "block",
                "rule_name": "escalation_trigger",
                "action": "escalate",
                "refusal_text": None,
            },
        )

    client = _client_with(handler)
    _, reply = await screen_input(client, tenant_id="tenant-acme", message="urgent")
    assert reply.escalate is True
    assert reply.text is None
    await client.aclose()


@pytest.mark.asyncio
async def test_fail_closed_returns_fallback():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated")

    client = _client_with(handler)
    decision, reply = await screen_input(client, tenant_id="tenant-acme", message="hi")
    assert decision.decision == "block"
    assert decision.rule_name == "engine_error"
    assert reply.text == FALLBACK_TEXT
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_action_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "decision": "block",
                "rule_name": "off_topic",
                "action": "mystery_action",
                "refusal_text": None,
            },
        )

    client = _client_with(handler)
    with pytest.raises(UnknownGuardrailAction):
        await screen_input(client, tenant_id="tenant-acme", message="hi")
    await client.aclose()


@pytest.mark.asyncio
async def test_output_endpoint():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/check/output"
        return httpx.Response(
            200, json={"decision": "pass", "payload": "the answer", "redaction": None}
        )

    client = _client_with(handler)
    decision, reply = await screen_output(
        client, tenant_id="tenant-acme", llm_response="the answer"
    )
    assert decision.decision == "pass"
    assert reply.text == "the answer"
    await client.aclose()
