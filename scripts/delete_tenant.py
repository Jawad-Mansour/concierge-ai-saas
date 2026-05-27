# Owner: Mohammad + Jana

"""CLI tool to permanently erase all data for a tenant across every store.

Mohammad: Postgres tables, MinIO bucket, Redis sessions, audit log.
Jana: coordinate on the embeddings table step (Jana confirms table name
      and any additional vector-store cleanup needed in pgvector).

Usage:
    python scripts/delete_tenant.py <tenant_id>

Requires:
    - Backend running at BACKEND_URL (default: http://localhost:8000)
    - A Tenant Manager account authenticated via TM_EMAIL / TM_PASSWORD env vars

The script calls DELETE /tenants/{id} which executes the full 9-step erasure
sequence defined in contracts/tenants.md.
"""

import os
import sys

import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TM_EMAIL = os.environ.get("TM_EMAIL", "manager@concierge.internal")
TM_PASSWORD = os.environ.get("TM_PASSWORD", "manager-password-change-me")


def get_tm_token() -> str:
    resp = requests.post(
        f"{BACKEND_URL}/auth/login",
        json={"email": TM_EMAIL, "password": TM_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Tenant Manager login failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()["access_token"]


def erase_tenant(tenant_id: str, token: str) -> None:
    print(f"Erasing tenant {tenant_id}...")
    resp = requests.delete(
        f"{BACKEND_URL}/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if resp.status_code == 404:
        print(f"Tenant {tenant_id} not found (already erased or never existed).")
        sys.exit(0)
    if resp.status_code != 200:
        print(f"ERROR: {resp.status_code} {resp.text}")
        sys.exit(1)

    result = resp.json()
    print("Erasure complete:")
    print(f"  tenant_id:          {result['tenant_id']}")
    print(f"  status:             {result['status']}")
    print(f"  audit_log_entry_id: {result['audit_log_entry_id']}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <tenant_id>")
        sys.exit(1)

    tenant_id = sys.argv[1]
    print(f"Authenticating as Tenant Manager ({TM_EMAIL})...")
    token = get_tm_token()
    erase_tenant(tenant_id, token)


if __name__ == "__main__":
    main()
