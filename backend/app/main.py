# Owner: Shared Core

import os
from contextlib import asynccontextmanager

import hvac
from fastapi import FastAPI

from app.db import init_db
from app.services.auth_service import load_signing_keys


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = _load_database_url()
    init_db(database_url)
    load_signing_keys()
    yield


app = FastAPI(title="Concierge backend", lifespan=lifespan)

# ── Mohammad's routers ───────────────────────────────────────────────────────
from app.api.auth import router as auth_router      # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402
from app.api.cms import router as cms_router  # noqa: E402
from app.api.tenants import router as tenants_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(chat_router)
app.include_router(cms_router)
app.include_router(tenants_router, prefix="/tenants", tags=["tenants"])

# ── Health (no auth required) ────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "backend"}
