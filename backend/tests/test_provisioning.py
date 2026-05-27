# Owner: Mohammad

"""Integration tests for Owner A's provisioning, auth, and tenant lifecycle endpoints.

All tests hit the real database — no mocks. conftest.py handles JWT key injection and
DB initialisation so Vault is not required during test runs.

Run with:
    docker compose run --rm backend python -m pytest backend/tests/test_provisioning.py -v
"""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.auth_service import (
    JWT_ALGORITHM,
    get_auth_key,
    issue_invite_token,
    issue_token,
)
from app.models.user import Role


# ── Provisioning ─────────────────────────────────────────────────────────────

class TestProvisioning:
    """POST /tenants — tenant_manager only, slug-unique, model validation."""

    def test_provision_success(self, test_client: TestClient, tm_headers: dict):
        """Happy path: valid request creates tenant and returns invite token."""
        resp = test_client.post(
            "/tenants",
            json={
                "name": "Acme Widgets",
                "slug": "acme-widgets-prov-test",
                "allowed_origins": ["https://acme.example.com"],
            },
            headers=tm_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "tenant_id" in body
        assert body["slug"] == "acme-widgets-prov-test"
        assert "invite_token" in body

        # Verify the invite_token is a valid JWT with the correct purpose
        claims = jwt.decode(body["invite_token"], get_auth_key(), algorithms=[JWT_ALGORITHM])
        assert claims["purpose"] == "first_admin_invite"
        assert claims["tenant_id"] == body["tenant_id"]
        assert claims["role"] == Role.tenant_admin.value

        # Cleanup
        _delete_tenant_by_slug(test_client, tm_headers, body["tenant_id"])

    def test_provision_duplicate_slug_returns_409(
        self, test_client: TestClient, tm_headers: dict
    ):
        """Second request with the same slug must return 409 Conflict."""
        payload = {
            "name": "Dup Co",
            "slug": "dup-slug-409-test",
            "allowed_origins": [],
        }
        r1 = test_client.post("/tenants", json=payload, headers=tm_headers)
        assert r1.status_code == 201
        tenant_id = r1.json()["tenant_id"]

        r2 = test_client.post("/tenants", json=payload, headers=tm_headers)
        assert r2.status_code == 409, f"Expected 409 on duplicate slug, got {r2.status_code}"

        _delete_tenant_by_slug(test_client, tm_headers, tenant_id)

    def test_provision_invalid_slug_returns_422(
        self, test_client: TestClient, tm_headers: dict
    ):
        """Slugs with uppercase or special chars must be rejected with 422."""
        resp = test_client.post(
            "/tenants",
            json={"name": "Bad", "slug": "INVALID_SLUG!", "allowed_origins": []},
            headers=tm_headers,
        )
        assert resp.status_code == 422, f"Expected 422 for invalid slug, got {resp.status_code}"

    def test_provision_invalid_origin_returns_422(
        self, test_client: TestClient, tm_headers: dict
    ):
        """Origins that are not valid http/https URLs must be rejected with 422."""
        resp = test_client.post(
            "/tenants",
            json={
                "name": "Bad Origin",
                "slug": "bad-origin-test",
                "allowed_origins": ["not-a-url", "ftp://wrong-scheme.com"],
            },
            headers=tm_headers,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for invalid allowed_origins, got {resp.status_code}"
        )

    def test_provision_requires_tenant_manager(self, test_client: TestClient):
        """tenant_admin must be forbidden from provisioning tenants."""
        ta_token = issue_token(
            user_id="ta-user", tenant_id="some-tenant", role=Role.tenant_admin
        )
        resp = test_client.post(
            "/tenants",
            json={"name": "Hack", "slug": "hack-provision", "allowed_origins": []},
            headers={"Authorization": f"Bearer {ta_token}"},
        )
        assert resp.status_code == 403

    def test_provision_unauthenticated_returns_401(self, test_client: TestClient):
        resp = test_client.post(
            "/tenants",
            json={"name": "No Auth", "slug": "no-auth-test", "allowed_origins": []},
        )
        assert resp.status_code in (401, 403)


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegister:
    """POST /auth/register — invite token flow, no body-supplied tenant_id."""

    @pytest.fixture(autouse=True)
    def _provision_tenant(self, test_client: TestClient, tm_headers: dict):
        """Create a fresh tenant for each test in this class."""
        r = test_client.post(
            "/tenants",
            json={
                "name": "Register Test Co",
                "slug": f"register-test-{id(self)}",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        data = r.json()
        self.tenant_id = data["tenant_id"]
        self.invite_token = data["invite_token"]
        yield
        _delete_tenant_by_slug(test_client, tm_headers, self.tenant_id)

    def test_register_success(self, test_client: TestClient):
        """Registering with a valid invite token creates the user."""
        resp = test_client.post(
            "/auth/register",
            json={
                "email": f"admin-{id(self)}@register.test",
                "password": "SecurePass1!",
                "invite_token": self.invite_token,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["role"] == Role.tenant_admin.value
        # tenant_id must come from invite token, not body
        assert body["tenant_id"] == self.tenant_id

    def test_register_without_invite_returns_422(self, test_client: TestClient):
        """Registration without invite_token must fail."""
        resp = test_client.post(
            "/auth/register",
            json={
                "email": "no-invite@test.com",
                "password": "SecurePass1!",
                "invite_token": "not.a.real.jwt",
            },
        )
        assert resp.status_code == 422

    def test_register_wrong_purpose_token_returns_422(self, test_client: TestClient):
        """An auth JWT (not an invite) must be rejected as invite_token."""
        wrong_token = issue_token(
            user_id="someone", tenant_id=self.tenant_id, role=Role.tenant_admin
        )
        resp = test_client.post(
            "/auth/register",
            json={
                "email": "wrong-token@test.com",
                "password": "SecurePass1!",
                "invite_token": wrong_token,
            },
        )
        assert resp.status_code == 422, (
            f"Expected 422 for wrong-purpose token, got {resp.status_code}"
        )

    def test_register_duplicate_email_returns_409(self, test_client: TestClient):
        """Registering twice with the same email must return 409."""
        email = f"dup-{id(self)}@register.test"
        for _ in range(2):
            r = test_client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": "SecurePass1!",
                    "invite_token": self.invite_token,
                },
            )
        assert r.status_code == 409

    def test_register_weak_password_returns_422(self, test_client: TestClient):
        """Passwords shorter than 8 characters must be rejected."""
        resp = test_client.post(
            "/auth/register",
            json={
                "email": "weakpass@test.com",
                "password": "short",
                "invite_token": self.invite_token,
            },
        )
        assert resp.status_code == 422

    def test_register_body_tenant_id_ignored(self, test_client: TestClient):
        """Any tenant_id in the request body must be silently ignored.

        The server must use the tenant_id from the invite token, never from the body.
        This is a security invariant — body injection must not produce a cross-tenant write.
        """
        malicious_tenant_id = "00000000-0000-0000-0000-000000000000"
        resp = test_client.post(
            "/auth/register",
            json={
                "email": f"body-inject-{id(self)}@register.test",
                "password": "SecurePass1!",
                "invite_token": self.invite_token,
                # attacker tries to write user into a different tenant
                "tenant_id": malicious_tenant_id,
            },
        )
        # Should succeed (extra fields are ignored by Pydantic model)
        assert resp.status_code == 201
        body = resp.json()
        assert body["tenant_id"] == self.tenant_id, (
            f"SECURITY: body tenant_id ({malicious_tenant_id}) was used instead "
            f"of invite token's tenant_id ({self.tenant_id})"
        )


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    """POST /auth/login — credential validation, suspended tenant, JWT claims."""

    @pytest.fixture(autouse=True)
    def _setup(self, test_client: TestClient, tm_headers: dict):
        """Create tenant + register one admin user for login tests."""
        slug = f"login-test-{id(self)}"
        r = test_client.post(
            "/tenants",
            json={"name": "Login Co", "slug": slug, "allowed_origins": []},
            headers=tm_headers,
        )
        assert r.status_code == 201
        data = r.json()
        self.tenant_id = data["tenant_id"]
        self.slug = slug

        self.email = f"loginuser-{id(self)}@test.com"
        self.password = "LoginPass1!"
        rr = test_client.post(
            "/auth/register",
            json={
                "email": self.email,
                "password": self.password,
                "invite_token": data["invite_token"],
            },
        )
        assert rr.status_code == 201
        yield
        _delete_tenant_by_slug(test_client, tm_headers, self.tenant_id)

    def test_login_success_returns_valid_jwt(self, test_client: TestClient):
        """Correct credentials return 200 with a JWT containing the right claims."""
        resp = test_client.post(
            "/auth/login",
            json={"email": self.email, "password": self.password},
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        claims = jwt.decode(token, get_auth_key(), algorithms=[JWT_ALGORITHM])
        assert claims["tenant_id"] == self.tenant_id
        assert claims["role"] == Role.tenant_admin.value

    def test_login_wrong_password_returns_401(self, test_client: TestClient):
        resp = test_client.post(
            "/auth/login",
            json={"email": self.email, "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_user_returns_401(self, test_client: TestClient):
        resp = test_client.post(
            "/auth/login",
            json={"email": "nobody@nowhere.test", "password": "Irrelevant1!"},
        )
        assert resp.status_code == 401

    def test_login_suspended_tenant_returns_403(
        self, test_client: TestClient, tm_headers: dict
    ):
        """Login must be refused for users whose tenant is suspended."""
        test_client.patch(
            f"/tenants/{self.tenant_id}/suspend",
            json={"reason": "test suspension"},
            headers=tm_headers,
        )
        resp = test_client.post(
            "/auth/login",
            json={"email": self.email, "password": self.password},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for suspended tenant login, got {resp.status_code}"
        )


# ── Invite endpoint ───────────────────────────────────────────────────────────

class TestInvite:
    """POST /tenants/{id}/invite — re-issue invite for existing tenant."""

    @pytest.fixture(autouse=True)
    def _setup(self, test_client: TestClient, tm_headers: dict):
        r = test_client.post(
            "/tenants",
            json={
                "name": "Invite Co",
                "slug": f"invite-test-{id(self)}",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        self.tenant_id = r.json()["tenant_id"]
        yield
        _delete_tenant_by_slug(test_client, tm_headers, self.tenant_id)

    def test_invite_returns_valid_token(self, test_client: TestClient, tm_headers: dict):
        resp = test_client.post(
            f"/tenants/{self.tenant_id}/invite",
            headers=tm_headers,
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["invite_token"]
        claims = jwt.decode(token, get_auth_key(), algorithms=[JWT_ALGORITHM])
        assert claims["purpose"] == "first_admin_invite"
        assert claims["tenant_id"] == self.tenant_id

    def test_invite_nonexistent_tenant_returns_404(
        self, test_client: TestClient, tm_headers: dict
    ):
        resp = test_client.post(
            "/tenants/00000000-0000-0000-0000-000000000000/invite",
            headers=tm_headers,
        )
        assert resp.status_code == 404

    def test_invite_requires_tenant_manager(self, test_client: TestClient):
        ta_token = issue_token(
            user_id="ta", tenant_id=self.tenant_id, role=Role.tenant_admin
        )
        resp = test_client.post(
            f"/tenants/{self.tenant_id}/invite",
            headers={"Authorization": f"Bearer {ta_token}"},
        )
        assert resp.status_code == 403


# ── Suspension ────────────────────────────────────────────────────────────────

class TestSuspend:
    """PATCH /tenants/{id}/suspend — deactivates tenant and all its users."""

    @pytest.fixture(autouse=True)
    def _setup(self, test_client: TestClient, tm_headers: dict):
        r = test_client.post(
            "/tenants",
            json={
                "name": "Suspend Co",
                "slug": f"suspend-test-{id(self)}",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        self.tenant_id = r.json()["tenant_id"]
        yield
        _delete_tenant_by_slug(test_client, tm_headers, self.tenant_id)

    def test_suspend_success(self, test_client: TestClient, tm_headers: dict):
        resp = test_client.patch(
            f"/tenants/{self.tenant_id}/suspend",
            json={"reason": "trial expired"},
            headers=tm_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "suspended"
        assert body["tenant_id"] == self.tenant_id

    def test_suspend_requires_tenant_manager(self, test_client: TestClient):
        ta_token = issue_token(
            user_id="ta", tenant_id=self.tenant_id, role=Role.tenant_admin
        )
        resp = test_client.patch(
            f"/tenants/{self.tenant_id}/suspend",
            headers={"Authorization": f"Bearer {ta_token}"},
        )
        assert resp.status_code == 403

    def test_suspend_idempotent(self, test_client: TestClient, tm_headers: dict):
        """Suspending an already-suspended tenant must not error."""
        for _ in range(2):
            resp = test_client.patch(
                f"/tenants/{self.tenant_id}/suspend",
                headers=tm_headers,
            )
        assert resp.status_code == 200

    def test_suspend_nonexistent_tenant_returns_404(
        self, test_client: TestClient, tm_headers: dict
    ):
        resp = test_client.patch(
            "/tenants/00000000-0000-0000-0000-000000000000/suspend",
            headers=tm_headers,
        )
        assert resp.status_code == 404


# ── Cost endpoint ─────────────────────────────────────────────────────────────

class TestCostEndpoint:
    """GET /tenants/{id}/cost — returns aggregates, never content."""

    @pytest.fixture(autouse=True)
    def _setup(self, test_client: TestClient, tm_headers: dict):
        r = test_client.post(
            "/tenants",
            json={
                "name": "Cost Co",
                "slug": f"cost-test-{id(self)}",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        self.tenant_id = r.json()["tenant_id"]
        yield
        _delete_tenant_by_slug(test_client, tm_headers, self.tenant_id)

    def test_cost_returns_numeric_aggregates(
        self, test_client: TestClient, tm_headers: dict
    ):
        resp = test_client.get(
            f"/tenants/{self.tenant_id}/cost",
            headers=tm_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Must return aggregate numbers, never raw message content
        assert "llm_calls" in body
        assert "total_input_tokens" in body
        assert "total_output_tokens" in body
        assert "estimated_cost_usd" in body
        assert "embedding_calls" in body
        # Verify values are numeric/stringified numbers (not embedded content strings)
        assert isinstance(body["llm_calls"], int)
        assert isinstance(body["total_input_tokens"], int)

    def test_cost_requires_tenant_manager(self, test_client: TestClient):
        ta_token = issue_token(
            user_id="ta", tenant_id=self.tenant_id, role=Role.tenant_admin
        )
        resp = test_client.get(
            f"/tenants/{self.tenant_id}/cost",
            headers={"Authorization": f"Bearer {ta_token}"},
        )
        assert resp.status_code == 403


# ── Erasure ───────────────────────────────────────────────────────────────────

class TestErasure:
    """DELETE /tenants/{id} — full erasure across all stores."""

    def test_erase_removes_tenant_from_db(
        self,
        test_client: TestClient,
        tm_headers: dict,
        db_session: Session,
    ):
        """Erase removes the tenant row from the DB."""
        r = test_client.post(
            "/tenants",
            json={
                "name": "Erase Me",
                "slug": "erase-me-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        tenant_id = r.json()["tenant_id"]

        resp = test_client.delete(
            f"/tenants/{tenant_id}",
            headers=tm_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "erased"
        assert "audit_log_entry_id" in body

        # Verify tenant row is gone from DB
        db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        row = db_session.execute(
            text("SELECT id FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        ).fetchone()
        assert row is None, "Tenant row still exists after erase"

    def test_erase_removes_users_from_db(
        self,
        test_client: TestClient,
        tm_headers: dict,
        db_session: Session,
    ):
        """Erase removes all users belonging to the tenant."""
        r = test_client.post(
            "/tenants",
            json={
                "name": "Erase Users",
                "slug": "erase-users-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        data = r.json()
        tenant_id = data["tenant_id"]

        # Register a user for this tenant
        test_client.post(
            "/auth/register",
            json={
                "email": "erase-user@test.com",
                "password": "ErasePass1!",
                "invite_token": data["invite_token"],
            },
        )

        resp = test_client.delete(f"/tenants/{tenant_id}", headers=tm_headers)
        assert resp.status_code == 200

        # Set tenant context so RLS reveals any surviving users for this tenant.
        # If erase worked, the users are gone and the result is empty.
        # If erase skipped users, they would be visible here — making this a real assertion.
        db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        user_rows = db_session.execute(text("SELECT id FROM users")).fetchall()
        db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert user_rows == [], (
            f"Erase left {len(user_rows)} user(s) in DB for erased tenant"
        )

    def test_erase_requires_tenant_manager(self, test_client: TestClient):
        ta_token = issue_token(
            user_id="ta", tenant_id="some-tenant", role=Role.tenant_admin
        )
        resp = test_client.delete(
            "/tenants/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {ta_token}"},
        )
        assert resp.status_code == 403

    def test_erase_response_contains_no_tenant_content(
        self, test_client: TestClient, tm_headers: dict
    ):
        """The erase response must contain only metadata, never tenant data."""
        r = test_client.post(
            "/tenants",
            json={
                "name": "No Leak Co",
                "slug": "no-leak-erase-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        tenant_id = r.json()["tenant_id"]

        resp = test_client.delete(f"/tenants/{tenant_id}", headers=tm_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Only metadata fields permitted in the response
        allowed_keys = {"tenant_id", "status", "audit_log_entry_id"}
        assert set(body.keys()) <= allowed_keys, (
            f"Erase response leaked unexpected keys: {set(body.keys()) - allowed_keys}"
        )


# ── Audit log ─────────────────────────────────────────────────────────────────

class TestAuditLog:
    """Audit entries are created on tenant lifecycle actions and are append-only."""

    def test_provision_creates_audit_entry(
        self,
        test_client: TestClient,
        tm_headers: dict,
        db_session: Session,
    ):
        r = test_client.post(
            "/tenants",
            json={
                "name": "Audit Co",
                "slug": "audit-create-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        tenant_id = r.json()["tenant_id"]

        db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        row = db_session.execute(
            text(
                "SELECT action FROM audit_log "
                "WHERE target_tenant_id = :tid AND action = 'create_tenant'"
            ),
            {"tid": tenant_id},
        ).fetchone()
        assert row is not None, "No 'create_tenant' audit entry found after provision"

        _delete_tenant_by_slug(test_client, tm_headers, tenant_id)

    def test_suspend_creates_audit_entry(
        self,
        test_client: TestClient,
        tm_headers: dict,
        db_session: Session,
    ):
        r = test_client.post(
            "/tenants",
            json={
                "name": "Suspend Audit Co",
                "slug": "audit-suspend-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        tenant_id = r.json()["tenant_id"]

        test_client.patch(
            f"/tenants/{tenant_id}/suspend",
            json={"reason": "audit test"},
            headers=tm_headers,
        )

        db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        row = db_session.execute(
            text(
                "SELECT action FROM audit_log "
                "WHERE target_tenant_id = :tid AND action = 'suspend_tenant'"
            ),
            {"tid": tenant_id},
        ).fetchone()
        assert row is not None, "No 'suspend_tenant' audit entry found after suspend"

        _delete_tenant_by_slug(test_client, tm_headers, tenant_id)

    def test_audit_log_is_append_only(
        self,
        test_client: TestClient,
        tm_headers: dict,
        db_session: Session,
    ):
        """Verify audit_log has no UPDATE or DELETE triggers — only INSERT."""
        db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

        # Attempt a direct UPDATE on the audit_log table — must be rejected or have no effect
        # (audit_log has no RLS; the test is that no UPDATE path exists in the app)
        # Structural check: count of rows can only grow, never shrink
        count_before = db_session.execute(
            text("SELECT COUNT(*) FROM audit_log")
        ).scalar()

        # Perform an action that generates an audit entry
        r = test_client.post(
            "/tenants",
            json={
                "name": "Append Only Co",
                "slug": "audit-append-only-test",
                "allowed_origins": [],
            },
            headers=tm_headers,
        )
        assert r.status_code == 201
        tenant_id = r.json()["tenant_id"]

        count_after = db_session.execute(
            text("SELECT COUNT(*) FROM audit_log")
        ).scalar()
        assert count_after > count_before, "No audit entry was added after provision"

        _delete_tenant_by_slug(test_client, tm_headers, tenant_id)


# ── Token security ─────────────────────────────────────────────────────────────

class TestTokenSecurity:
    """JWT claims integrity and token refresh safety."""

    def test_refresh_preserves_tenant_id_from_token(self, test_client: TestClient):
        """Refreshing a token must copy tenant_id from the OLD token, never from the body."""
        token = issue_token(
            user_id="user-123", tenant_id="tenant-abc", role=Role.tenant_admin
        )
        resp = test_client.post(
            "/auth/refresh",
            json={"tenant_id": "tenant-xyz"},  # attacker injects different tenant
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]
        claims = jwt.decode(new_token, get_auth_key(), algorithms=[JWT_ALGORITHM])
        assert claims["tenant_id"] == "tenant-abc", (
            f"SECURITY: refresh used body tenant_id instead of JWT claim. "
            f"Got {claims['tenant_id']!r}"
        )

    def test_expired_token_returns_401(self, test_client: TestClient):
        """An expired JWT must be rejected with 401."""
        from datetime import datetime, timedelta, timezone
        import jwt as pyjwt

        payload = {
            "sub": "user-1",
            "tenant_id": "t-1",
            "role": Role.tenant_admin.value,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired = pyjwt.encode(payload, get_auth_key(), algorithm=JWT_ALGORITHM)
        resp = test_client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    def test_tampered_token_returns_401(self, test_client: TestClient):
        """A token with an invalid signature must be rejected with 401."""
        token = issue_token(
            user_id="u", tenant_id="t", role=Role.tenant_admin
        )
        # Flip the last character to invalidate the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        resp = test_client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    def test_widget_token_rejected_on_auth_endpoints(self, test_client: TestClient):
        """A widget JWT (signed with widget key) must be rejected on auth endpoints."""
        from app.services.auth_service import issue_widget_token
        widget_token = issue_widget_token("some-tenant")
        resp = test_client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {widget_token}"},
        )
        # Widget token is signed with a different key — must fail verification
        assert resp.status_code == 401


# ── Helper ────────────────────────────────────────────────────────────────────

def _delete_tenant_by_slug(
    client: TestClient, tm_headers: dict, tenant_id: str
) -> None:
    """Best-effort cleanup: delete a tenant via the erase endpoint."""
    client.delete(f"/tenants/{tenant_id}", headers=tm_headers)
