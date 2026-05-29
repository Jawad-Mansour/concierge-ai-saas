# Owner: Shared Core

import os
from contextlib import asynccontextmanager

import hvac
from fastapi import FastAPI

from app.db import init_db
from app.services import tracing_service
from app.services.auth_service import load_signing_keys
from app.services.classifier_client import ClassifierClient
from app.services.guardrail_service import GuardrailClient
from app.utils import metrics


# ── Vault helpers ─────────────────────────────────────────────────────────────

def _load_database_url() -> str:
    """Fetch database URL from Vault; fall back to DATABASE_URL env var for CI/tests."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    vault_addr = os.environ.get("VAULT_ADDR", "http://vault:8200")
    vault_token = os.environ.get("VAULT_TOKEN", "")
    client = hvac.Client(url=vault_addr, token=vault_token)
    if not client.is_authenticated():
        raise RuntimeError(f"Vault unreachable at startup (addr={vault_addr})")

    secret = client.secrets.kv.v2.read_secret_version(
        path="concierge/db", mount_point="secret"
    )
    return secret["data"]["data"]["url"]


def _load_service_credential(*, vault_path: str, env_var: str) -> str:
    """Fetch a service-to-service credential from Vault; fall back to env var.

    vault_path: KV v2 path relative to the 'secret/' mount — matches the
                'concierge/' prefix convention used throughout this file and
                modelserver/app/deps.py.
    env_var:    CI/test escape hatch; avoids requiring a live Vault locally.

    Fails fast on any error — the backend MUST NOT serve requests without valid
    outbound credentials (Constitution Principle V: secrets via Vault only)."""

    env_cred = os.environ.get(env_var)
    if env_cred:
        return env_cred

    vault_addr = os.environ.get("VAULT_ADDR", "http://vault:8200")
    vault_token = os.environ.get("VAULT_TOKEN", "")
    client = hvac.Client(url=vault_addr, token=vault_token)
    if not client.is_authenticated():
        raise RuntimeError(
            f"Vault unreachable fetching {vault_path!r} (addr={vault_addr})"
        )
    try:
        secret = client.secrets.kv.v2.read_secret_version(
            path=vault_path, mount_point="secret"
        )
        return secret["data"]["data"]["token"]
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch service credential {vault_path!r}: {type(exc).__name__}"
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Observability first — errors during the rest of startup are traced ───
    tracing_service.init("backend")
    tracing_service.instrument_app(app)
    metrics.init("backend")

    # ── Database + signing keys ──────────────────────────────────────────────
    database_url = _load_database_url()
    init_db(database_url)
    load_signing_keys()

    # ── Service clients ──────────────────────────────────────────────────────
    # Base URL defaults assume Charbel's docker-compose service names + ports.
    # Override via env if they differ.
    classifier_client = ClassifierClient(
        base_url=os.environ.get("MODELSERVER_URL", "http://modelserver:8001"),
        service_credential=_load_service_credential(
            vault_path="concierge/service_auth",
            env_var="MODELSERVER_SERVICE_CREDENTIAL",
        ),
    )
    guardrail_client = GuardrailClient(
        base_url=os.environ.get("GUARDRAILS_URL", "http://guardrails:8002"),
        service_credential=_load_service_credential(
            vault_path="concierge/service_auth",
            env_var="GUARDRAILS_SERVICE_CREDENTIAL",
        ),
    )

    app.state.classifier_client = classifier_client
    app.state.guardrail_client = guardrail_client

    yield

    # ── Teardown — close httpx sessions cleanly ──────────────────────────────
    await classifier_client.aclose()
    await guardrail_client.aclose()


app = FastAPI(title="Concierge backend", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from app.middleware.csp import CSPMiddleware  # noqa: E402

# CORS: allow_origins=["*"] because per-tenant origin validation happens
# server-side in widget_auth_service.exchange_token(). CORS is defense-in-depth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(CSPMiddleware)

# ── Routers ──────────────────────────────────────────────────────────────────
from app.api.admin import router as admin_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.cms import router as cms_router  # noqa: E402
from app.api.tenants import router as tenants_router  # noqa: E402
from app.api.widget import router as widget_router  # noqa: E402
from app.api.widget_js import router as widget_js_router  # noqa: E402

app.include_router(admin_router)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(chat_router)
app.include_router(cms_router)
app.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
app.include_router(widget_router)
app.include_router(widget_js_router)

# ── Health (no auth required) ────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "backend"}
