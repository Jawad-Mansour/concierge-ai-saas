# Owner: Jana
"""T022 — probe-string redaction against REAL sinks (Principle IX).

Each probe is a unique random value injected into a `/check/input` request.
After the response comes back, the test scans the real container's log
output, the OTel collector's persisted span export, and the returned
response body bytes; the assertion is that the probe string is **absent**
from all three. No mocked sinks — that's the whole point of Principle IX.

Skipped unless the GUARDRAILS_E2E env-var is set, since the test requires a
live `docker compose up guardrails otel-collector` stack — security-gates.yml
sets it. Local devs can opt in via `GUARDRAILS_E2E=1 pytest`.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import httpx
import pytest

GUARDRAILS_URL = os.environ.get("GUARDRAILS_URL", "http://localhost:8002")
GUARDRAILS_TOKEN = os.environ.get("GUARDRAILS_SERVICE_CREDENTIAL", "test-token")
OTEL_EXPORT_FILE = Path(os.environ.get("OTEL_EXPORT_FILE", "/tmp/guardrails-otel-spans.json"))

pytestmark = pytest.mark.skipif(
    "GUARDRAILS_E2E" not in os.environ,
    reason="requires live guardrails container + otel collector (set GUARDRAILS_E2E=1)",
)


def _generate_probe(recognizer: str) -> str:
    rnd = secrets.token_hex(16)
    digits = "".join(secrets.choice("0123456789") for _ in range(16))
    builders = {
        "EMAIL_ADDRESS": f"probe{rnd}@probe-{rnd}.test",
        "PHONE_NUMBER": f"+1-555-{digits[:3]}-{digits[3:7]}",
        "CREDIT_CARD": "4111-1111-1111-1111",
        "US_SSN": f"{digits[:3]}-{digits[3:5]}-{digits[5:9]}",
        "GENERIC_BEARER_TOKEN": f"eyJ{rnd}abc.{rnd}def.{rnd}ghi",
        "HOSTED_LLM_API_KEY_ANTHROPIC": f"sk-ant-api03-{rnd}{rnd}",
        "HOSTED_LLM_API_KEY_OPENAI": f"sk-{rnd}{rnd}",
    }
    return builders[recognizer]


def _fetch_container_logs() -> str:
    try:
        out = subprocess.check_output(
            ["docker", "compose", "logs", "--no-color", "--tail=500", "guardrails"],
            stderr=subprocess.STDOUT,
            timeout=10,
        )
        return out.decode("utf-8", errors="replace")
    except Exception as exc:
        pytest.skip(f"docker compose logs unavailable: {exc}")


def _fetch_otel_export() -> str:
    if OTEL_EXPORT_FILE.exists():
        return OTEL_EXPORT_FILE.read_text(encoding="utf-8", errors="replace")
    return ""


@pytest.mark.parametrize(
    "recognizer",
    [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "GENERIC_BEARER_TOKEN",
        "HOSTED_LLM_API_KEY_ANTHROPIC",
        "HOSTED_LLM_API_KEY_OPENAI",
    ],
)
def test_probe_absent_from_logs_and_traces_and_response(recognizer):
    probe = _generate_probe(recognizer)
    message = f"Embedded probe for {recognizer}: {probe} — please redact."

    resp = httpx.post(
        f"{GUARDRAILS_URL}/check/input",
        json={"tenant_id": "tenant-probe", "message": message, "tenant_config": {}},
        headers={"Authorization": f"Bearer {GUARDRAILS_TOKEN}"},
        timeout=10.0,
    )
    body_bytes = resp.content
    assert resp.status_code == 200, resp.text

    # Let the OTel BatchSpanProcessor flush.
    time.sleep(2.0)

    response_str = body_bytes.decode("utf-8", errors="replace")
    logs = _fetch_container_logs()
    spans = _fetch_otel_export()

    for sink_name, sink in (("response_body", response_str), ("logs", logs), ("spans", spans)):
        assert probe not in sink, (
            f"PROBE LEAK: probe {probe!r} for {recognizer} appeared in {sink_name}"
        )

    body = json.loads(body_bytes)
    assert body["decision"] == "pass"
    assert body["redaction"] is not None
    assert recognizer in body["redaction"]["recognizers_fired"]
