# Owner: Jana
"""Vault credential bootstrap + FastAPI auth dependency.

Vault KV v2 path:
    secret/data/guardrails/service_credential

TBD: confirm against `infra/vault/policies/` (Mohammad) before merging.
"""
from __future__ import annotations

import hmac
import logging
import os
import sys

from fastapi import Header, HTTPException

from .telemetry import structured_log

logger = logging.getLogger("guardrails.deps")

VAULT_KV_PATH = "guardrails/service_credential"
_BOOT_CREDENTIAL: str | None = None


def fetch_vault_credential() -> str:
    global _BOOT_CREDENTIAL
    if _BOOT_CREDENTIAL is not None:
        return _BOOT_CREDENTIAL

    env_override = os.environ.get("GUARDRAILS_SERVICE_CREDENTIAL")
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
    except Exception as exc:  # noqa: BLE001 — boot-time, exit on any failure
        structured_log("vault_fetch_failed", error=type(exc).__name__)
        sys.exit(1)

    _BOOT_CREDENTIAL = str(token)
    structured_log("service_credential_loaded", source="vault")
    return _BOOT_CREDENTIAL


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="unauthenticated")


def require_service_credential(authorization: str | None = Header(default=None)) -> None:
    """Constant-time check of the bearer token. Any failure mode raises 401
    with the byte-identical `{"detail":"unauthenticated"}` body (FR-008)."""
    if _BOOT_CREDENTIAL is None:
        raise _unauthenticated()
    if not authorization:
        raise _unauthenticated()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated()
    if not hmac.compare_digest(token, _BOOT_CREDENTIAL):
        raise _unauthenticated()
