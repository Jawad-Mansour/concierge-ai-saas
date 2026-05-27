# Owner: Mohammad

"""Seed two demo tenants via the provisioning API.

Idempotent: checks if slug exists before creating. Safe to run multiple times.
Exercises the full provisioning flow (API → service → DB) rather than raw SQL.

Usage (from repo root):
    python scripts/seed_tenants.py

Requires:
    - Backend running at BACKEND_URL (default: http://localhost:8000)
    - A seeded Tenant Manager account (email/password below)

The script creates:
    acme-coffee  → admin: admin@acme-coffee.com / demo-password-1
    brew-bar     → admin: admin@brew-bar.com    / demo-password-2
"""

import os
import sys

import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

TENANT_MANAGER_EMAIL = os.environ.get("TM_EMAIL", "manager@concierge.internal")
TENANT_MANAGER_PASSWORD = os.environ.get("TM_PASSWORD", "manager-password-change-me")

DEMO_TENANTS = [
    {
        "name": "Acme Coffee",
        "slug": "acme-coffee",
        "allowed_origins": ["http://localhost:8080", "https://acme-coffee.com"],
        "admin_email": "admin@acme-coffee.com",
        "admin_password": "demo-password-1",
    },
    {
        "name": "Brew Bar",
        "slug": "brew-bar",
        "allowed_origins": ["http://localhost:8080", "https://brew-bar.com"],
        "admin_email": "admin@brew-bar.com",
        "admin_password": "demo-password-2",
    },
]


def get_tm_token() -> str:
    resp = requests.post(
        f"{BACKEND_URL}/auth/login",
        json={"email": TENANT_MANAGER_EMAIL, "password": TENANT_MANAGER_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Tenant Manager login failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()["access_token"]


def provision_tenant(token: str, tenant: dict) -> str | None:
    """Create tenant and return invite_token. Returns None if already exists."""
    resp = requests.post(
        f"{BACKEND_URL}/tenants",
        json={
            "name": tenant["name"],
            "slug": tenant["slug"],
            "allowed_origins": tenant["allowed_origins"],
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 409:
        print(f"  {tenant['slug']}: already exists, skipping provision")
        return None
    if resp.status_code != 201:
        print(f"  ERROR provisioning {tenant['slug']}: {resp.status_code} {resp.text}")
        sys.exit(1)
    print(f"  {tenant['slug']}: provisioned (id={resp.json()['tenant_id']})")
    return resp.json()["invite_token"]


def register_admin(invite_token: str, email: str, password: str) -> None:
    resp = requests.post(
        f"{BACKEND_URL}/auth/register",
        json={"email": email, "password": password, "invite_token": invite_token},
        timeout=10,
    )
    if resp.status_code == 409:
        print(f"  {email}: already registered, skipping")
        return
    if resp.status_code != 201:
        print(f"  ERROR registering {email}: {resp.status_code} {resp.text}")
        sys.exit(1)
    print(f"  {email}: registered as tenant_admin")


def main() -> None:
    print(f"Seeding demo tenants at {BACKEND_URL}...")

    print("Authenticating as Tenant Manager...")
    token = get_tm_token()

    for tenant in DEMO_TENANTS:
        print(f"\nProcessing: {tenant['slug']}")
        invite_token = provision_tenant(token, tenant)
        if invite_token:
            register_admin(invite_token, tenant["admin_email"], tenant["admin_password"])

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
