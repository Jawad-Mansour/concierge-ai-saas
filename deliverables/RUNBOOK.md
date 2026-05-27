<!-- Owner: Shared -->

# Concierge — Operational Runbook

---

## First Boot

```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, EMBEDDINGS_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
docker compose up
```

`vault-init` runs first and seeds all secrets into Vault (`infra/vault/seed.sh`). Every other service waits on `vault-init`'s health check before starting. The backend reads signing keys and DB credentials from Vault at startup — never from `.env` directly.

**First boot takes ~60 s** for Vault to unseal, Postgres to run migrations, and all 13 health checks to pass.

---

## Daily Operations

### Start / stop the stack

```bash
docker compose up -d          # start in background
docker compose down           # stop; volumes persist
docker compose down -v        # stop AND wipe all data (full reset)
```

### Restart a single service after code change

```bash
docker compose restart backend
docker compose logs -f backend   # confirm clean startup
```

### Check health

```bash
curl http://localhost:8000/health     # backend
curl http://localhost:8001/health     # modelserver
curl http://localhost:8002/health     # guardrails
```

---

## Provisioning Demo Tenants

The `seed_tenants.py` script is idempotent — safe to re-run.

```bash
# With the stack running:
python scripts/seed_tenants.py
```

This creates two demo tenants via the full provisioning API flow:

| Tenant | Slug | Admin email | Password |
|--------|------|-------------|----------|
| Acme Coffee | `acme-coffee` | `admin@acme-coffee.com` | `demo-password-1` |
| Brew Bar | `brew-bar` | `admin@brew-bar.com` | `demo-password-2` |

Override defaults with env vars:

```bash
BACKEND_URL=http://localhost:8000 \
TM_EMAIL=manager@concierge.internal \
TM_PASSWORD=manager-password-change-me \
python scripts/seed_tenants.py
```

---

## Provisioning a New Tenant (manual)

1. **Login as Tenant Manager** and obtain a token:

```bash
TOKEN=$(curl -sX POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"manager@concierge.internal","password":"manager-password-change-me"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

2. **Create the tenant** — receives an invite token:

```bash
curl -sX POST http://localhost:8000/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Corp","slug":"my-corp","allowed_origins":["https://my-corp.com"]}' \
  | python -m json.tool
```

3. **Register the first admin** using the `invite_token` from the response:

```bash
curl -sX POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@my-corp.com","password":"SecurePass1!","invite_token":"<invite_token>"}' \
  | python -m json.tool
```

---

## Erasing a Tenant (GDPR / off-boarding)

The erasure path is irreversible. It deletes all tenant data across Postgres, pgvector, MinIO, and Redis in the 9-step sequence defined in `DESIGN.md §5`.

```bash
python scripts/delete_tenant.py <tenant_uuid>
```

Or directly via API:

```bash
curl -sX DELETE http://localhost:8000/tenants/<tenant_uuid> \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool
```

Expected response:

```json
{
  "tenant_id": "<uuid>",
  "status": "erased",
  "audit_log_entry_id": "<uuid>"
}
```

**Idempotent**: re-running after a partial failure resumes from the first incomplete step. The audit log entry (`action: erase_tenant`) survives erasure and is the permanent compliance record.

---

## Running Tests

All tests require a running Postgres instance with migrations applied.

```bash
# Full backend test suite inside Docker
docker compose run --rm backend python -m pytest backend/tests/ -v

# RLS isolation tests only
docker compose run --rm backend python -m pytest backend/tests/test_rls.py -v

# Provisioning / auth integration tests
docker compose run --rm backend python -m pytest backend/tests/test_provisioning.py -v

# Role fence tests
docker compose run --rm backend python -m pytest backend/tests/test_tenant_isolation.py -v
```

---

## Running Evals

```bash
bash scripts/run_evals.sh          # all gates
python evals/security/red_team_tests.py   # security gate alone (must be 100%)
```

Security gate failure is a hard block — no exceptions. See `eval_thresholds.yaml` and `EVALS.md`.

---

## Ingest CMS Content

```bash
python scripts/ingest_cms.py       # embed CMS content into pgvector for a tenant
```

---

## Vault: Manual Secret Inspection

```bash
docker compose exec vault vault kv get secret/concierge/auth_jwt
docker compose exec vault vault kv get secret/concierge/widget_jwt
docker compose exec vault vault kv get secret/concierge/db
```

Vault token is `root` in dev mode (see `docker-compose.yml`). Never use the root token in production.

---

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Backend exits with `ModuleNotFoundError` | `Dockerfile` hardcodes 3 packages instead of reading `pyproject.toml` | Charbel: change `RUN uv pip install fastapi uvicorn hvac` → `RUN uv pip install -e .` |
| `cross-tenant data visible` assertion in RLS tests | Missing `NULLIF` in RLS policy SQL | Check `infra/postgres/rls_policies.sql`; `NULLIF(current_setting(...), '')::UUID` is required |
| Widget token endpoint returns 404 for widget_id | `widget_configs.widget_id` column not populated | Charbel: run migration to add `widget_id UUID` column and populate it |
| Login returns 403 "Tenant is suspended" | Tenant was suspended via `/tenants/{id}/suspend` | Reactivate via `PATCH /tenants/{id}` or erase and reprovision |
| Tests fail on second run with "duplicate key" | TM user fixture used INSERT instead of UPSERT | `conftest.py` uses `ON CONFLICT (LOWER(email)) DO UPDATE` — if this fails, wipe the DB |
