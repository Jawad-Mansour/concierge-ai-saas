# Owner: Jana
"""Vault credential bootstrap + FastAPI auth dependency.

Vault KV path:
    secret/data/modelserver/service_credential

TBD: confirm against `infra/vault/policies/` (Mohammad) before merging the
serving slice. The placeholder is treated as load-bearing — the agent will
swap in the real path during integration.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys

from fastapi import Header, HTTPException

from .telemetry import structured_log

logger = logging.getLogger("modelserver.deps")

VAULT_KV_PATH = "modelserver/service_credential"  # mount: secret/, data prefix added by hvac kv v2

_BOOT_CREDENTIAL: str | None = None


def fetch_vault_credential() -> str:
    """Fetch the service credential once at boot.

    Reads from the Vault KV v2 path agreed with Mohammad (TBD — see module docstring).
    On any failure, logs and calls `sys.exit(1)` so the listener never opens
    without a real credential (Principle V).
    """
    global _BOOT_CREDENTIAL
    if _BOOT_CREDENTIAL is not None:
        return _BOOT_CREDENTIAL

    # Dev escape hatch: in unit tests / local quickstart, allow the credential
    # to be injected via env so the test harness doesn't need Vault running.
    env_override = os.environ.get("MODELSERVER_SERVICE_CREDENTIAL")
    if env_override:
        _BOOT_CREDENTIAL = env_override
        structured_log("service_credential_loaded", source="env")
        return _BOOT_CREDENTIAL

    try:
        import hvac

        client = hvac.Client(
            url=os.environ.get("VAULT_ADDR", "http://vault:8200"),
            token=os.environ.get("VAULT_TOKEN"),
        )
        if not client.is_authenticated():
            structured_log("vault_auth_failed")
            sys.exit(1)
        resp = client.secrets.kv.v2.read_secret_version(path=VAULT_KV_PATH)
        token = resp["data"]["data"]["token"]
    except Exception as exc:  # noqa: BLE001 — boot-time, exit-on-any-failure
        structured_log("vault_fetch_failed", error=type(exc).__name__)
        sys.exit(1)

    _BOOT_CREDENTIAL = str(token)
    structured_log("service_credential_loaded", source="vault")
    return _BOOT_CREDENTIAL


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="unauthenticated")


def require_service_credential(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — constant-time check of the bearer token.

    Any failure mode (missing header, wrong scheme, mismatch) raises 401 with
    the byte-identical `{"detail": "unauthenticated"}` body — no information
    leak about which failure occurred (FR-004).
    """
    if _BOOT_CREDENTIAL is None:
        # Boot-time invariant violation — refuse to serve.
        raise _unauthenticated()
    if not authorization:
        raise _unauthenticated()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated()
    if not hmac.compare_digest(token, _BOOT_CREDENTIAL):
        raise _unauthenticated()
