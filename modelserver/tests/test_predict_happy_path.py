# Owner: Jana
"""T014 — happy-path /predict shape per spec User Story 1 acceptance scenarios."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import StubBackend

FIXTURES = json.loads(Path(__file__).parent.joinpath("fixtures/predict_examples.json").read_text())


@pytest.mark.parametrize("example", FIXTURES, ids=lambda e: e["expected_class"])
def test_predict_happy_path(example, make_app, boot_credential):
    backend = StubBackend({example["message"]: (example["expected_class"], example["confidence"])})
    app = make_app(backend, unknown_threshold=0.25)
    client = TestClient(app)

    resp = client.post(
        "/predict",
        json={"tenant_id": "tenant-acme", "message": example["message"]},
        headers={"Authorization": f"Bearer {boot_credential}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predicted_class"] == example["expected_class"]
    assert 0.0 < body["confidence"] <= 1.0
    assert re.fullmatch(r"[0-9a-f]{12}", body["model_hash"])
