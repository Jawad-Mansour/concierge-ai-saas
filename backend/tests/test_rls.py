# Owner: Mohammad

"""RLS isolation tests — all three MUST pass before any other slice ships data.

Run with:
    docker compose run --rm backend python -m pytest backend/tests/test_rls.py -v

These tests verify that Postgres RLS physically blocks cross-tenant access,
independently of application-layer .filter() calls.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

from app.db import SessionLocal, init_db
from app.models.tenant import Tenant
from app.models.user import Role, User


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    """Module-scoped DB session for RLS tests. Rolls back after all tests."""
    import os
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@postgres:5432/concierge",
    )
    init_db(database_url)
    session: Session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="module")
def two_tenants(db: Session):
    """Create two fixture tenants and one user each, committing to DB."""
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    tenant_a = Tenant(name="Tenant A", slug="tenant-a-rls-test", allowed_origins=[])
    tenant_b = Tenant(name="Tenant B", slug="tenant-b-rls-test", allowed_origins=[])
    db.add_all([tenant_a, tenant_b])
    db.flush()

    import bcrypt

    def _hash(p: str) -> str:
        return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

    user_a = User(
        email="user_a_rls@test.com",
        hashed_password=_hash("password"),
        role=Role.tenant_admin,
        tenant_id=tenant_a.id,
    )
    user_b = User(
        email="user_b_rls@test.com",
        hashed_password=_hash("password"),
        role=Role.tenant_admin,
        tenant_id=tenant_b.id,
    )
    db.add_all([user_a, user_b])
    db.commit()

    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "user_a": user_a, "user_b": user_b}

    # Cleanup: FORCE RLS blocks DELETE without app.tenant_id set, so we must set
    # each tenant's context before deleting its users, then clear for the next one.
    for tid, email in [
        (str(tenant_a.id), "user_a_rls@test.com"),
        (str(tenant_b.id), "user_b_rls@test.com"),
    ]:
        db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tid},
        )
        db.execute(
            text("DELETE FROM users WHERE email = :email"),
            {"email": email},
        )

    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    db.execute(
        text("DELETE FROM tenants WHERE slug IN ('tenant-a-rls-test', 'tenant-b-rls-test')")
    )
    db.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_cross_tenant_select_blocked(db: Session, two_tenants):
    """SELECT in Tenant A's context must return zero Tenant B rows even without .filter().

    This test removes the application-layer filter to verify RLS alone is sufficient.
    """
    tenant_a_id = two_tenants["tenant_a"].id
    tenant_b_id = two_tenants["tenant_b"].id

    # Set Tenant A context
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_a_id)},
    )

    # Raw SQL to bypass the application .filter() — RLS should still block Tenant B rows
    result = db.execute(
        text("SELECT id, tenant_id FROM users WHERE tenant_id = :b_id"),
        {"b_id": str(tenant_b_id)},
    ).fetchall()

    assert result == [], (
        f"RLS FAILED: Tenant A context returned {len(result)} Tenant B user row(s). "
        "Cross-tenant isolation is broken."
    )

    # Reset
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))


def test_finally_reset_on_connection_reuse(db: Session, two_tenants):
    """Simulate request sequence: Tenant A request, then Tenant B request on same connection.

    Verifies that the finally-reset pattern in tenant_context.py prevents the prior
    tenant's context from leaking into the next request.
    """
    tenant_a_id = two_tenants["tenant_a"].id
    tenant_b_id = two_tenants["tenant_b"].id
    user_a_id = two_tenants["user_a"].id
    user_b_id = two_tenants["user_b"].id

    # Simulate Tenant A request (with finally reset)
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_a_id)},
    )
    try:
        rows_a = db.execute(text("SELECT id FROM users")).fetchall()
        ids_a = {r[0] for r in rows_a}
        assert user_a_id in ids_a, "Tenant A should see their own user"
        assert user_b_id not in ids_a, "Tenant A should NOT see Tenant B's user"
    finally:
        db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # Simulate Tenant B request on same connection — must not inherit Tenant A context
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_b_id)},
    )
    try:
        rows_b = db.execute(text("SELECT id FROM users")).fetchall()
        ids_b = {r[0] for r in rows_b}
        assert user_b_id in ids_b, "Tenant B should see their own user"
        assert user_a_id not in ids_b, "Tenant B should NOT see Tenant A's user after connection reuse"
    finally:
        db.execute(text("SELECT set_config('app.tenant_id', '', true)"))


def test_tenant_manager_select_returns_empty(db: Session, two_tenants):
    """SELECT with no app.tenant_id set must return zero rows (Tenant Manager read prohibition).

    The Tenant Manager's session never sets app.tenant_id. RLS policy returns false for
    NULL context (current_setting(..., true) returns NULL which fails UUID cast equality).
    No error — just empty result. This is structural, not procedural.
    """
    # Explicitly clear context (simulates Tenant Manager request path)
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    rows = db.execute(text("SELECT id FROM users")).fetchall()

    assert rows == [], (
        f"Tenant Manager read prohibition FAILED: {len(rows)} user row(s) visible "
        "without app.tenant_id set. RLS must return empty for unset context."
    )


# ── Six-table RLS coverage ────────────────────────────────────────────────────

_TENANT_TABLES = ("users", "leads", "cms_content", "conversations", "embeddings", "widget_configs")


def test_all_six_tables_have_rls_enabled(db: Session, two_tenants):
    """Every tenant-scoped table must have RLS enabled and forced.

    Checks pg_class.relrowsecurity (ENABLE ROW LEVEL SECURITY) and
    pg_class.relforcerowsecurity (FORCE ROW LEVEL SECURITY) for each table.
    FORCE is required so that the postgres superuser (used in Docker) is also blocked.
    """
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    for table in _TENANT_TABLES:
        row = db.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = :tbl"
            ),
            {"tbl": table},
        ).fetchone()

        assert row is not None, f"Table '{table}' not found in pg_class"
        assert row[0] is True, (
            f"ENABLE ROW LEVEL SECURITY missing on '{table}'. "
            "Postgres will skip the policy entirely without it."
        )
        assert row[1] is True, (
            f"FORCE ROW LEVEL SECURITY missing on '{table}'. "
            "Superuser bypasses RLS without FORCE — all Docker tests pass vacuously."
        )


def test_all_six_tables_have_tenant_isolation_policy(db: Session, two_tenants):
    """Every tenant-scoped table must have 'tenant_isolation' (FOR SELECT) and
    'erase_isolation' (FOR DELETE) policies. The users table also needs
    'email_login_lookup' (FOR SELECT) for the login flow."""
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    for table in _TENANT_TABLES:
        for policy in ("tenant_isolation", "erase_isolation"):
            row = db.execute(
                text(
                    "SELECT policyname FROM pg_policies "
                    "WHERE tablename = :tbl AND policyname = :pol"
                ),
                {"tbl": table, "pol": policy},
            ).fetchone()

            assert row is not None, (
                f"'{policy}' policy missing on table '{table}'. "
                "RLS is enabled but this policy is required for correct behaviour."
            )

    # users-only: login bypass policy
    row = db.execute(
        text(
            "SELECT policyname FROM pg_policies "
            "WHERE tablename = 'users' AND policyname = 'email_login_lookup'"
        ),
    ).fetchone()
    assert row is not None, (
        "'email_login_lookup' policy missing on 'users'. "
        "Login flow cannot find users by email without this policy."
    )


def test_teammate_tables_cross_tenant_blocked(db: Session, two_tenants):
    """Stub teammate tables (leads, widget_configs, etc.) must enforce tenant isolation.

    Inserts one row into each table for Tenant A, then verifies that Tenant B's context
    returns zero rows — confirming that RLS on teammate tables is active, not just configured.
    """
    tenant_a_id = str(two_tenants["tenant_a"].id)
    tenant_b_id = str(two_tenants["tenant_b"].id)

    # tables that have a tenant_id column with no other NOT NULL constraints
    stub_tables = ("leads", "cms_content", "conversations", "embeddings", "widget_configs")

    inserted_ids: dict[str, str] = {}

    # Insert one row per table in Tenant A's context
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_a_id},
    )
    for table in stub_tables:
        row = db.execute(
            text(f"INSERT INTO {table} (tenant_id) VALUES (:tid) RETURNING id"),
            {"tid": tenant_a_id},
        ).fetchone()
        inserted_ids[table] = str(row[0])
    db.commit()

    # Verify Tenant B's context sees zero rows in each table
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_b_id},
    )
    for table in stub_tables:
        rows = db.execute(
            text(f"SELECT id FROM {table} WHERE id = :rid"),
            {"rid": inserted_ids[table]},
        ).fetchall()
        assert rows == [], (
            f"RLS FAILED on '{table}': Tenant B context returned "
            f"{len(rows)} row(s) belonging to Tenant A. "
            "widget_configs and teammate tables must be fully isolated."
        )

    # Cleanup: delete the inserted rows in Tenant A's context
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_a_id},
    )
    for table in stub_tables:
        db.execute(
            text(f"DELETE FROM {table} WHERE id = :rid"),
            {"rid": inserted_ids[table]},
        )
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    db.commit()
