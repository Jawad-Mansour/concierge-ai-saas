# Owner: Jana
"""T041 — canary per recognizer; the canary string never appears in any span attribute."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CANARIES = {
    "EMAIL_ADDRESS": "__CANARY_EMAIL_99731@example.test",
    "PHONE_NUMBER": "+1-555-010-99731",
    "CREDIT_CARD": "4111-1111-1111-99731",
    "US_SSN": "123-45-99731",
    "GENERIC_BEARER_TOKEN": "eyJCANARYBEARER99731.aaaaaaaaaaaaa.bbbbbbbbbbbbb",
    "HOSTED_LLM_API_KEY_ANTHROPIC": "sk-ant-api03-CANARYANTHROPIC99731AAAAAAAAAAAAAAAAA",
    "HOSTED_LLM_API_KEY_OPENAI": "sk-CANARYOPENAI99731AAAAAAAAAAAAAAAAA",
}


@pytest.mark.parametrize("recognizer,canary", CANARIES.items(), ids=list(CANARIES))
def test_canary_absent_from_all_spans(recognizer, canary, app, boot_credential, span_exporter):
    client = TestClient(app)
    client.post(
        "/check/input",
        json={
            "tenant_id": "tenant-acme",
            "message": f"please process value {canary} in this message",
            "tenant_config": {},
        },
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    for span in span_exporter.get_finished_spans():
        if not span.attributes:
            continue
        for value in span.attributes.values():
            assert canary not in str(value), (
                f"canary {canary!r} ({recognizer}) leaked into span attr: {value!r}"
            )
