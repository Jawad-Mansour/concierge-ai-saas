# scripts/seed_platform.py
"""Bootstrap the platform-level tenant_manager.

The application has no admin-bootstrap HTTP endpoint by design — the first
tenant_manager must be created out-of-band before the provisioning API can
be used (seed_tenants.py depends on a working tenant_manager login).

Run once after a fresh `docker compose up`. Idempotent.

Usage:
    uv run --with "psycopg2-binary,bcrypt" python scripts/seed_platform.py
"""
import os
import sys

import bcrypt
import psycopg2

DB_HOST = os.environ.get("PG_HOST", "localhost")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_NAME = os.environ.get("PG_DB", "concierge")
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "postgres")

TM_EMAIL = os.environ.get("TM_EMAIL", "manager@concierge.internal")
TM_PASSWORD = os.environ.get("TM_PASSWORD", "manager-password-change-me")


def main() -> int:
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email = %s", (TM_EMAIL,))
    if cur.fetchone():
        print(f"Platform tenant_manager '{TM_EMAIL}' already exists. Skipping.")
        return 0

    hashed = bcrypt.hashpw(TM_PASSWORD.encode(), bcrypt.gensalt()).decode()
    cur.execute(
        """
        INSERT INTO users (tenant_id, email, hashed_password, role)
        VALUES (NULL, %s, %s, 'tenant_manager')
        """,
        (TM_EMAIL, hashed),
    )
    print(f"Created platform tenant_manager: {TM_EMAIL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
