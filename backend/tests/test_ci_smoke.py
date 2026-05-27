# Owner: Charbel
# Integration smoke tests — require the full docker compose stack.
# Skipped in the regular CI test job (no stack running there).
# Run by smoke-test.yml workflow against the live stack.
# Run locally with: pytest -m integration -v

import json
import urllib.request
import pytest

pytestmark = pytest.mark.integration


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


class TestHealthEndpoints:
    def test_backend_health(self):
        """Backend /health returns 200 with correct shape."""
        data = _get("http://localhost:8000/health")
        assert data["status"] == "ok"
        assert data["service"] == "backend"

    def test_modelserver_health(self):
        """Modelserver /health returns 200 with correct shape."""
        data = _get("http://localhost:8001/health")
        assert data["status"] == "ok"
        assert data["service"] == "modelserver"

    def test_guardrails_health(self):
        """Guardrails /health returns 200 with correct shape."""
        data = _get("http://localhost:8002/health")
        assert data["status"] == "ok"
        assert data["service"] == "guardrails"

    def test_admin_health(self):
        """Streamlit admin health endpoint returns ok."""
        with urllib.request.urlopen(
            "http://localhost:8501/_stcore/health", timeout=5
        ) as r:
            assert r.read() == b"ok"


class TestWidgetNginx:
    def test_widget_serves_html(self):
        """Widget nginx serves the placeholder HTML."""
        with urllib.request.urlopen("http://localhost:8081/", timeout=5) as r:
            assert r.status == 200

    def test_widget_healthz(self):
        """Widget nginx /healthz returns 200."""
        with urllib.request.urlopen("http://localhost:8081/healthz", timeout=5) as r:
            body = r.read()
        assert b"ok" in body.lower()

    def test_blocked_host_serves(self):
        """Blocked host nginx serves on 8090."""
        with urllib.request.urlopen(
            "http://localhost:8090/blocked.html", timeout=5
        ) as r:
            assert r.status == 200
