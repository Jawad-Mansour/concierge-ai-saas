# Owner: Jana
"""T048 — classifier_client fail-closed mapping on every error path."""
from __future__ import annotations

import httpx
import pytest

from app.services.classifier_client import ClassifierClient


def _client_with(handler) -> ClassifierClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return ClassifierClient(
        base_url="http://modelserver:8001",
        service_credential="test-token",
        client=http_client,
    )


@pytest.mark.asyncio
async def test_happy_path_returns_real_prediction():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "predicted_class": "FAQ",
                "confidence": 0.91,
                "model_hash": "abcdef012345",
            },
        )

    client = _client_with(handler)
    resp = await client.classify(tenant_id="tenant-acme", message="hi")
    assert resp.predicted_class == "FAQ"
    assert resp.confidence == 0.91
    assert resp.degraded is False
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_maps_to_fail_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated")

    client = _client_with(handler)
    resp = await client.classify(tenant_id="tenant-acme", message="hi")
    assert resp.predicted_class == "UNKNOWN"
    assert resp.confidence == 0.0
    assert resp.degraded is True
    await client.aclose()


@pytest.mark.asyncio
async def test_401_maps_to_fail_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthenticated"})

    client = _client_with(handler)
    resp = await client.classify(tenant_id="tenant-acme", message="hi")
    assert resp.predicted_class == "UNKNOWN"
    assert resp.confidence == 0.0
    assert resp.degraded is True
    await client.aclose()


@pytest.mark.asyncio
async def test_500_maps_to_fail_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = _client_with(handler)
    resp = await client.classify(tenant_id="tenant-acme", message="hi")
    assert resp.predicted_class == "UNKNOWN"
    assert resp.confidence == 0.0
    assert resp.degraded is True
    await client.aclose()


@pytest.mark.asyncio
async def test_degraded_classifier_response_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "predicted_class": "UNKNOWN",
                "confidence": 0.0,
                "model_hash": "abcdef012345",
            },
        )

    client = _client_with(handler)
    resp = await client.classify(tenant_id="tenant-acme", message="hi")
    assert resp.predicted_class == "UNKNOWN"
    assert resp.confidence == 0.0
    # The classifier returned a degraded result; client.degraded mirrors that.
    assert resp.degraded is True
    await client.aclose()
