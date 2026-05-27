# Owner: Jana
"""T027 — message text never appears in logs or span attributes (Principle IX hygiene)."""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from .conftest import StubBackend

CANARY = "CANARY_REDACT_CHECK_99731"


def test_message_never_appears_in_logs_or_spans(
    make_app, boot_credential, span_exporter, caplog
):
    app = make_app(StubBackend({CANARY: ("HARD_QUESTION", 0.6)}))
    client = TestClient(app)

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/predict",
            json={"tenant_id": "tenant-acme", "message": CANARY},
            headers={"Authorization": f"Bearer {boot_credential}"},
        )
    assert resp.status_code == 200

    for record in caplog.records:
        assert CANARY not in record.getMessage(), "canary leaked into log record"

    for span in span_exporter.get_finished_spans():
        if not span.attributes:
            continue
        for value in span.attributes.values():
            assert CANARY not in str(value), f"canary leaked into span attr: {value!r}"
