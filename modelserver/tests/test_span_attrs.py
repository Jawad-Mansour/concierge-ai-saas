# Owner: Jana
"""T026 — every prediction emits a span carrying the six EvaluationSpan attrs."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from .conftest import StubBackend


def test_span_carries_evaluation_attrs(make_app, boot_credential, span_exporter):
    app = make_app(StubBackend({"hi there": ("FAQ", 0.91)}))
    client = TestClient(app)

    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": "hi there"},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )
    assert resp.status_code == 200

    spans = span_exporter.get_finished_spans()
    # Find the classifier-decorated span (an OTel-instrumented FastAPI may emit a
    # server span too; we set our attrs on the active span inside `classify`).
    matching = [
        s
        for s in spans
        if s.attributes and s.attributes.get("classifier.predicted_class")
    ]
    assert matching, f"no span carried classifier.predicted_class — got: {[s.name for s in spans]}"
    attrs = matching[0].attributes
    assert attrs["tenant_id"] == "tenant-acme"
    assert attrs["classifier.predicted_class"] == "FAQ"
    assert 0.0 <= float(attrs["classifier.confidence"]) <= 1.0
    assert float(attrs["classifier.latency_ms"]) >= 0.0
    assert re.fullmatch(r"[0-9a-f]{12}", str(attrs["classifier.model_hash"]))
    assert attrs["classifier.degraded"] is False
