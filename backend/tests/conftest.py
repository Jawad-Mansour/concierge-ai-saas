# Owner: Mohammad

"""Shared test fixtures and environment bootstrap.

Must be loaded before any test module imports app code that touches Vault or DB.
Pre-injects JWT signing keys so load_signing_keys() becomes a no-op, preventing
Vault connection attempts during pytest runs inside Docker.
"""

import os
import pytest

# ── Inject test JWT keys BEFORE any app module is imported ────────────────────
# load_signing_keys() is idempotent: if these are set it returns immediately.
# Test keys are long enough to satisfy HS256 but are never used in production.
_TEST_AUTH_KEY = os.environ.get(
    "TEST_JWT_KEY", "test-auth-signing-key-for-pytest-only-NOT-production-safe!!"
)
_TEST_WIDGET_KEY = os.environ.get(
    "TEST_WIDGET_KEY", "test-widget-signing-key-for-pytest-only-NOT-production-safe"
)

import app.services.auth_service as _auth_svc  # noqa: E402

if _auth_svc._AUTH_JWT_KEY is None:
    _auth_svc._AUTH_JWT_KEY = _TEST_AUTH_KEY
if _auth_svc._WIDGET_JWT_KEY is None:
    _auth_svc._WIDGET_JWT_KEY = _TEST_WIDGET_KEY

# ── DB setup ──────────────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@postgres:5432/concierge",
)
os.environ.setdefault("DATABASE_URL", _DATABASE_URL)

from app.db import init_db, SessionLocal  # noqa: E402

init_db(_DATABASE_URL)

# ── Session-scoped test client ────────────────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def test_client() -> TestClient:
    """Shared FastAPI test client for all integration tests."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ── Tenant Manager fixtures ───────────────────────────────────────────────────
import bcrypt  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.services.auth_service import issue_token  # noqa: E402


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@pytest.fixture(scope="session")
def db_session() -> Session:
    """Session-scoped DB session for fixture setup/teardown."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def tm_user(db_session: Session) -> User:
    """A Tenant Manager user inserted directly — no app.tenant_id set during creation.

    Uses UPSERT because FORCE RLS blocks DELETE on TM users (tenant_id=NULL) even
    for superusers. The UPSERT keeps the fixture idempotent across multiple test runs.
    """
    hashed = _hash("TmPass123!")
    db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # UPSERT: first run inserts; subsequent runs update hashed_password in-place.
    # The functional index idx_users_email ON users (LOWER(email)) supports ON CONFLICT.
    row = db_session.execute(
        text("""
            INSERT INTO users (email, hashed_password, role, tenant_id, is_active)
            VALUES (:email, :hash, 'tenant_manager', NULL, true)
            ON CONFLICT (LOWER(email)) DO UPDATE
                SET hashed_password = EXCLUDED.hashed_password,
                    is_active = true
            RETURNING id, email, role, tenant_id, is_active
        """),
        {"email": "tm-conftest@internal.test", "hash": hashed},
    ).fetchone()
    db_session.commit()

    # Construct a User object from the returned row — do not use ORM query
    # (RLS would block SELECT on tenant_id=NULL users under empty context)
    user = User.__new__(User)
    user.id = row[0]
    user.email = row[1]
    user.hashed_password = hashed
    user.role = Role(row[2])
    user.tenant_id = row[3]
    user.is_active = row[4]
    yield user
    # No teardown: FORCE RLS blocks DELETE on TM users; the UPSERT above
    # handles stale rows cleanly on the next test run.


@pytest.fixture(scope="session")
def tm_token(tm_user: User) -> str:
    """Valid Tenant Manager JWT for use in HTTP test calls."""
    return issue_token(
        user_id=tm_user.id,
        tenant_id=None,
        role=Role.tenant_manager,
    )


@pytest.fixture(scope="session")
def tm_headers(tm_token: str) -> dict:
    return {"Authorization": f"Bearer {tm_token}"}
