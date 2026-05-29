# Owner: Charbel
"""Widget auth integration tests — Phase 5 implementation.

Requires the full docker compose stack (postgres, backend).
Run with: uv run pytest tests/test_widget_auth.py -v -m integration
"""

import uuid
from datetime import datetime, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_FIXTURE_SLUG = "widget-auth-test-tenant"
_FIXTURE_WIDGET_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="session")
def widget_config(db_session: Session) -> dict:
    """Seed a test tenant and widget_config row. Session-scoped so all tests share it."""
    # tenants has no RLS — direct insert is fine
    row = db_session.execute(
        text("""
            INSERT INTO tenants (name, slug, allowed_origins, is_active)
            VALUES ('Widget Auth Test', :slug, '{}', true)
            ON CONFLICT (slug) DO UPDATE SET is_active = true
            RETURNING id
        """),
        {"slug": _FIXTURE_SLUG},
    ).fetchone()
    db_session.commit()
    tenant_id = str(row[0])

    # widget_configs has no INSERT policy so insert is allowed without tenant context
    db_session.execute(
        text("""
            INSERT INTO widget_configs
                (widget_id, tenant_id, allowed_origins, theme, greeting, enabled_tools)
            VALUES
                (CAST(:wid AS uuid), :tid, ARRAY['http://localhost:8080'],
                 '{}', 'Hello!', ARRAY['rag_search'])
            ON CONFLICT (widget_id) DO NOTHING
        """),
        {"wid": _FIXTURE_WIDGET_ID, "tid": tenant_id},
    )
    db_session.commit()

    return {"tenant_id": tenant_id, "widget_id": _FIXTURE_WIDGET_ID}


def test_token_valid_origin(test_client: TestClient, widget_config: dict) -> None:
    """POST /widget/token with a widget_id and an allowed origin returns 200 + signed JWT."""
    resp = test_client.post(
        "/widget/token",
        json={"widget_id": widget_config["widget_id"], "origin": "http://localhost:8080"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["token"], str) and len(body["token"]) > 0
    assert body["expires_in"] == 900


def test_token_invalid_origin(test_client: TestClient, widget_config: dict) -> None:
    """POST /widget/token with an origin not in allowed_origins returns 403."""
    resp = test_client.post(
        "/widget/token",
        json={"widget_id": widget_config["widget_id"], "origin": "https://evil.com"},
    )
    assert resp.status_code == 403, resp.text


def test_token_unknown_widget_id(test_client: TestClient) -> None:
    """POST /widget/token with a widget_id that doesn't exist returns 404."""
    resp = test_client.post(
        "/widget/token",
        json={"widget_id": str(uuid.uuid4()), "origin": "http://localhost:8080"},
    )
    assert resp.status_code == 404, resp.text


def test_token_exp_is_900s(test_client: TestClient, widget_config: dict) -> None:
    """Issued token must have exp set approximately 900s in the future."""
    resp = test_client.post(
        "/widget/token",
        json={"widget_id": widget_config["widget_id"], "origin": "http://localhost:8080"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    claims = pyjwt.decode(token, options={"verify_signature": False})
    now = datetime.now(timezone.utc).timestamp()
    assert 850 < claims["exp"] - now < 950, f"exp delta out of range: {claims['exp'] - now:.0f}s"
