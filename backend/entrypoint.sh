#!/bin/sh
set -e

# Bootstrap alembic_version if empty (fresh init.sql database).
# init.sql already created the legacy tables (001-003), so Alembic must skip
# those migrations. We stamp directly via psycopg2 (single autocommit
# connection) instead of `alembic stamp` because alembic 1.18.x opens two
# concurrent connections for stamp, causing a self-deadlock on CREATE TABLE
# alembic_version. On subsequent restarts the count check is a no-op.
python3 - <<'EOF'
import os
import psycopg2

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
conn = psycopg2.connect(url, connect_timeout=10)
conn.autocommit = True
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS alembic_version (
        version_num VARCHAR(32) NOT NULL
            CONSTRAINT alembic_version_pkc PRIMARY KEY
    )
""")
cur.execute("SELECT COUNT(*) FROM alembic_version")
if cur.fetchone()[0] == 0:
    cur.execute("INSERT INTO alembic_version (version_num) VALUES ('003')")
    print("[entrypoint] Stamped alembic_version to 003 (init.sql bootstrap)")
else:
    print("[entrypoint] alembic_version already set — skipping stamp")
conn.close()
EOF

# alembic 1.18.x matches every *.py file in version_locations (regex
# (?!\.\#|__init__)(.*\.py)$), which means it tries to load env.py as a
# version script. env.py has module-level code that calls
# run_migrations_online(), causing infinite recursion.
#
# Fix: copy only the numbered migration files to a clean temp directory and
# point version_locations there. script_location still points to the original
# directory so alembic can find env.py as the environment script.
mkdir -p /tmp/alembic_versions
cp /infra/postgres/migrations/[0-9]*.py /tmp/alembic_versions/

sed \
  -e 's|script_location = .*|script_location = /infra/postgres/migrations|' \
  -e 's|version_locations = .*|version_locations = /tmp/alembic_versions|' \
  /app/alembic.ini > /tmp/alembic_runtime.ini

alembic -c /tmp/alembic_runtime.ini upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
