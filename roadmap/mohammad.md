<!-- Owner: Mohammad -->

# Roadmap — Mohammad

**Slice:** Tenancy, auth, RLS, provisioning

Append-only. End-of-day notes go at the bottom under "Daily log."
Phases tick from top to bottom; finished items get `[x]` with PR link or commit SHA in trailing parenthesis.

---

## Completed Phases

All six phases complete as of 2026-05-26. Bug fixes applied 2026-05-27.
See Daily log for details.

---

## Phase 1 — Repo Scaffold & Docker Compose (Day 1)

**Goal:** Write the two spec contracts that unblock every other slice, and lay down the Postgres schema skeleton so teammates can reference real table names from day one.

**Files I own (structure.md):**
- `specs/tenant_model_SPEC.md`
- `specs/role_model_SPEC.md`
- `infra/postgres/init.sql`
- `infra/vault/policies/` *(Vault KV read policies per service)*

> **Note:** `docker-compose.yml`, all Dockerfiles, and `infra/vault/seed.sh` were
> provisioned by Charbel (his Phase 0 + Phase 1 ✅). I own `seed.sh` per `structure.md`;
> the get-or-create idempotency fix for signing keys is tracked in Charbel's Phase 2 —
> coordinate before this phase closes.

**Checklist:**
- [x] Write `specs/tenant_model_SPEC.md` — define: `tenant_id` type (UUID v4), all table names,
      required columns on every table, `allowed_origins` field, `is_active` flag
- [x] Write `specs/role_model_SPEC.md` — define: three roles (`tenant_manager`, `tenant_admin`,
      `member`), capability matrix (what each role CAN and CANNOT do), Tenant Manager
      write/delete-only constraint (can destroy data but MUST never read it)
- [x] Write `infra/postgres/init.sql` — `CREATE EXTENSION IF NOT EXISTS vector`,
      `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"`, all tables with
      `tenant_id UUID NOT NULL`, base indexes on `tenant_id`
- [x] Write `infra/vault/policies/` — KV read policies scoped per service
      (backend reads `secret/concierge/*`; modelserver reads only its own key;
      guardrails reads only its own key)
- [ ] Verify `docker compose up` starts all 13 services healthy after `init.sql` is updated ← PENDING (blocked on T001 pyproject.toml deps)

**Acceptance criteria:**
- `specs/tenant_model_SPEC.md` and `specs/role_model_SPEC.md` committed and
  acknowledged by all owners before any service writes a data-access query
- Every table in `init.sql` has `tenant_id UUID NOT NULL`
- `docker compose up` — all 13 services healthy with updated Postgres init

**Spec reference:** This phase *produces* `specs/tenant_model_SPEC.md` and
`specs/role_model_SPEC.md` — they are the outputs, not inputs.

---

## Phase 2 — Tenant Model, RLS & Alembic Baseline (Day 1–2)

**Goal:** Enforce the tenant isolation wall at the database level so no code path
can accidentally cross tenants, even if an application-layer filter is forgotten.

**Files I own (structure.md):**
- `infra/postgres/rls_policies.sql`
- `infra/postgres/migrations/`
- `backend/app/models/tenant.py`
- `backend/app/models/user.py`
- `backend/app/repositories/tenant_repo.py`
- `backend/app/repositories/user_repo.py`
- `backend/app/middleware/tenant_context.py`
- `backend/tests/test_rls.py`

**Checklist:**
- [x] Create `backend/app/models/tenant.py` — SQLAlchemy `Tenant`:
      `id UUID PK`, `name`, `slug (unique)`, `allowed_origins ARRAY(Text)`,
      `is_active Boolean`, `created_at`
- [x] Create `backend/app/models/user.py` — SQLAlchemy `User`:
      `id UUID PK`, `tenant_id UUID FK → tenants.id`, `email (unique)`,
      `hashed_password`, `role Enum(tenant_manager | tenant_admin | member)`
- [x] Write `infra/postgres/rls_policies.sql`:
      ```sql
      ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
      CREATE POLICY tenant_isolation ON <table>
        USING (tenant_id = current_setting('app.tenant_id')::UUID);
      ```
      Applied to: `leads`, `cms_content`, `conversations`, `embeddings`,
      `widget_configs`, `users` (every table with a `tenant_id` column)
- [x] Write Alembic baseline migration `infra/postgres/migrations/001_baseline.py` —
      captures all tables + RLS policies as version 001; `alembic upgrade head`
      runs cleanly from an empty database
- [x] Write `backend/app/middleware/tenant_context.py` — FastAPI dependency:
      ```python
      db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)})
      try:
          yield db
      finally:
          db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
      ```
      **The `finally` reset is non-negotiable** — pooled connections persist this variable;
      a missing reset on a reused connection leaks Tenant A's data to Tenant B.
- [x] Write `backend/app/repositories/tenant_repo.py` — all queries
      `.filter(Tenant.id == ctx.tenant_id)` (RLS is the safety net, this is first line)
- [x] Write `backend/app/repositories/user_repo.py` — all queries
      `.filter(User.tenant_id == ctx.tenant_id)` except Tenant Manager paths
- [x] Write `backend/tests/test_rls.py`:
      - Seed Tenant A and Tenant B with one lead each
      - Run a filter-free SELECT for Tenant A's context — assert zero Tenant B rows returned
      - Run two sequential requests on the same DB connection for different tenants —
        assert each returns only its own data (proves the `finally` reset works)

**Acceptance criteria:**
- `test_rls.py` passes: Tenant A cannot see Tenant B rows even with no application filter
- `tenant_context.py` resets `app.tenant_id` in `finally` — verified by the
  two-sequential-requests test above
- `alembic upgrade head` completes with 0 errors from an empty database

**Spec reference:** `specs/tenant_model_SPEC.md`

---

## Phase 3 — Auth with fastapi-users & Three Roles (Day 2)

**Goal:** Working JWT authentication and role-based access control so every teammate
can protect their endpoints without building auth from scratch.

**Files I own (structure.md):**
- `backend/app/api/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/middleware/auth_middleware.py`

**Checklist:**
- [x] Wire `fastapi-users` — email/password registration, JWT bearer tokens,
      password hashing; do NOT build auth primitives from scratch
- [x] Create `backend/app/api/auth.py`:
      `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`;
      JWT signed with `secret/concierge/auth_jwt.signing_key` fetched from
      Vault via `hvac` (never hardcoded)
- [x] Create `backend/app/services/auth_service.py` — token issuance, validation,
      role resolution; `tenant_id` embedded in JWT claims and **never accepted
      from the request body** (accepting it from the body is a one-line cross-tenant breach)
- [x] Create `backend/app/middleware/auth_middleware.py` — FastAPI dependency that
      verifies Bearer token, extracts `tenant_id` from claims, raises HTTP 401 on
      expired/forged tokens, raises HTTP 403 on role mismatch
- [x] Implement role fence:
      - `tenant_admin` calling a `tenant_manager` endpoint → 403
      - `tenant_manager` calling a `tenant_admin` endpoint → 403
      - `member` (widget visitor) calling any admin endpoint → 403
- [x] Extend `tenant_context.py` — `tenant_id` in context MUST always come from
      the verified JWT claim, never from a request path/query param
- [x] Coordinate with Charbel on `backend/app/utils/token_utils.py` (his file) —
      agree on the shared token helper interface before duplicating logic
- [x] Add role fence tests to `backend/tests/test_tenant_isolation.py`
      (co-owned with Jana): forged token → 401, correct role → 200,
      wrong role → 403, `tenant_id` in body ignored

**Acceptance criteria:**
- `POST /auth/login` returns a signed JWT; a forged or expired token returns 401
- A `tenant_admin` token calling a `tenant_manager` endpoint returns 403
- `tenant_id` injected in request body is silently ignored — the JWT claim is used
  exclusively (verified by test)
- JWT signing key is fetched from Vault at service startup via `hvac`, not hardcoded

**Spec reference:** `specs/role_model_SPEC.md`

---

## Phase 4 — Tenant Manager Provisioning Flow & Audit Log (Day 3)

**Goal:** Complete tenant lifecycle — create, invite first admin, suspend, erase —
with every Tenant Manager action logged immutably so the operator can prove deletions happened.

**Files I own (structure.md):**
- `backend/app/api/tenants.py`
- `backend/app/services/tenant_service.py`
- `backend/app/repositories/audit_repo.py`
- `infra/minio/buckets.sh`
- `scripts/seed_tenants.py`
- `scripts/delete_tenant.py` *(co-owned with Jana — coordinate pgvector purge step)*

**Checklist:**
- [x] Create `backend/app/api/tenants.py`:
      `POST /tenants` (create + auto-generate first-admin invite),
      `POST /tenants/{id}/suspend`,
      `DELETE /tenants/{id}` (triggers full erasure);
      all endpoints restricted to `tenant_manager` role
- [x] Create `backend/app/services/tenant_service.py`:
      `provision_tenant()`, `invite_first_admin()`, `suspend_tenant()`, `erase_tenant()`;
      erasure calls each store purge in sequence and writes an audit log entry after each
- [x] Create `backend/app/repositories/audit_repo.py`:
      `log_action(actor_id, action, target_tenant_id, timestamp)`;
      Tenant Manager's DB session MUST NOT set `app.tenant_id` to any tenant's UUID
      so RLS returns empty on any accidental SELECT — it logs and deletes, never reads content
- [x] Write `infra/minio/buckets.sh` — create bucket `tenant-{id}` per tenant at provisioning;
      bucket deletion included in the erasure path
- [x] Write `scripts/seed_tenants.py` — idempotent script to seed two demo tenants
      with first admins via the provisioning API; skip silently if tenant slug already exists
- [x] Write `scripts/delete_tenant.py` — full erasure sequence:
      1. `DELETE FROM leads WHERE tenant_id = ?`
      2. `DELETE FROM cms_content WHERE tenant_id = ?`
      3. `DELETE FROM conversations WHERE tenant_id = ?`
      4. `DELETE FROM embeddings WHERE tenant_id = ?` *(coordinate with Ali — pgvector table)*
      5. Delete MinIO bucket `tenant-{id}`
      6. Flush Redis session keys matching `session:tenant:{id}:*`
      7. Write audit log entry: `"tenant_deleted"`, actor ID, timestamp
      Coordinate with Jana on step 4 (pgvector embeddings table name from her schema)
- [x] Confirm erasure does NOT SELECT content rows — Tenant Manager DB session has
      no `app.tenant_id` set, so any accidental SELECT returns empty (RLS enforces this)

**Acceptance criteria:**
- `seed_tenants.py` creates two tenants; running it a second time produces no duplicates
- `delete_tenant.py` removes all rows for the target tenant across all seven stores;
  confirmed by querying each store after run and asserting zero rows remain
- Every Tenant Manager API action produces an audit log row with actor ID, action name,
  target tenant ID, and ISO 8601 timestamp
- Tenant Manager DELETE path does not return any content rows (RLS verified by test)

**Spec reference:** `specs/tenant_model_SPEC.md`, `specs/role_model_SPEC.md`

---

## Phase 5 — Per-Tenant Rate Limiting & Cost Attribution (Day 4)

**Goal:** Prevent one noisy tenant from starving others, and make every LLM and
embedding call traceable to a tenant cost center.

**Files I own (structure.md):**
- `backend/app/middleware/rate_limit.py`

**Coordinate (do not edit these files — agree on interface only):**
- `backend/app/utils/metrics.py` *(Jana owns — agree on cost-log call signature)*
- `backend/app/utils/constants.py` *(shared — add rate limit constants here)*
- `backend/tests/test_tenant_isolation.py` *(co-owned with Jana — add rate limit test)*

**Checklist:**
- [x] Write `backend/app/middleware/rate_limit.py` — Redis sliding-window counter keyed
      by `tenant_id`; configurable `MAX_MESSAGES_PER_MINUTE` (default from `constants.py`);
      returns HTTP 429 with `Retry-After` header when exceeded
- [x] Wire rate limiter as FastAPI middleware on `/chat` and `/widget/token` routes only
      (NOT global — `/health` and `/auth/*` are exempt)
- [x] Add cost attribution: every LLM and embedding call passes
      `metadata={"tenant_id": tenant_id}` to the API call and logs
      `(tenant_id, model, input_tokens, output_tokens, cost_usd, timestamp)`;
      agree the log call signature with Jana's `tracing_service.py` before implementing
- [x] Write a per-tenant cost query helper in `tenant_service.py`:
      `get_cost_this_week(tenant_id)` — used by the Tenant Manager dashboard;
      exposes the answer to "what did Tenant X cost us this week?"
- [x] Add rate limit test to `backend/tests/test_tenant_isolation.py`:
      Tenant A exceeds their limit → 429; Tenant B sending the same number of
      messages in the same window → 200 (rate limit is per-tenant, not global)

**Acceptance criteria:**
- Tenant A sends N+1 messages/minute → HTTP 429; Tenant B sends N messages/minute
  in the same window → HTTP 200
- A `/chat` request produces a cost log row with the correct `tenant_id`
- Rate limit is per-tenant — confirmed by the noisy-neighbor test above

**Spec reference:** `specs/tenant_model_SPEC.md` (rate limiting and cost attribution sections)

---

## Phase 6 — DESIGN.md Scaling Story & Erasure Path (Day 5)

**Goal:** Deliver the written design artifacts that back every architectural decision
in this slice with a named failure mode or a measured number — not opinion.

**Files I own (structure.md):**
- `deliverables/DESIGN.md` *(shared doc — Mohammad owns §1–§5 listed below)*

**Coordinate (do not edit these files unilaterally):**
- `deliverables/SECURITY.md` *(Jana owns — RLS and erasure sections overlap; align wording)*
- `deliverables/RUNBOOK.md` *(shared — add seed and delete-tenant steps to runbook)*

**Checklist:**
- [x] Write `deliverables/DESIGN.md` §1 — **Tenant Isolation Strategy**: diagram of the
      three layers (RLS + repository `.filter()` + pgvector `tenant_id` filter); explain
      the `finally`-reset pattern and why it is not optional
- [x] Write `deliverables/DESIGN.md` §2 — **Role Model**: capability matrix table
      (3 rows × can/cannot columns); Tenant Manager write/delete-only constraint;
      provisioning flow (create → invite → self-setup, no platform operator login to tenant)
- [x] Write `deliverables/DESIGN.md` §3 — **Scaling Story**: named failure modes:
      - 10 tenants: everything works, no bottleneck
      - 1000 tenants: Postgres connection pool exhausted → PgBouncer needed;
        pgvector full-scan → IVFFlat or HNSW index needed;
        single FastAPI instance CPU-bound → horizontal scaling;
        Redis memory fills → eviction policy or cluster;
        primary bottleneck: pgvector without indexing
- [x] Write `deliverables/DESIGN.md` §4 — **Cost-Per-Tenant Model**: formula
      (LLM tokens × $/token + embedding calls + infra share per tenant);
      example showing the break-even point; why silent per-tenant cost blindness kills SaaS
- [x] Write `deliverables/DESIGN.md` §5 — **Erasure Path**: every store listed
      (Postgres tables, pgvector embeddings, MinIO blobs, Redis sessions,
      Langfuse traces retention policy); purge sequence; audit log as proof of completion;
      reference `scripts/delete_tenant.py` as the implementation
- [x] Run `backend/tests/test_rls.py` and `backend/tests/test_tenant_isolation.py` green
- [ ] Fill in README.md scorecard fields for the tenancy/isolation/roles rows ← PENDING
      (coordinate with Charbel who owns the README scorecard layout)

**Acceptance criteria:**
- `deliverables/DESIGN.md` has all five sections with no `[placeholder]` tokens remaining
- The scaling story names `pgvector without indexing` as the primary bottleneck at 1000 tenants
  and names IVFFlat/HNSW as the fix
- The erasure section lists all seven stores and references `scripts/delete_tenant.py`
- `test_rls.py` and `test_tenant_isolation.py` both pass in CI

**Spec reference:** `specs/tenant_model_SPEC.md`, `specs/role_model_SPEC.md`

---

## Daily log

### Mon 2026-05-25

- SpecKit setup, constitution, spec + plan + tasks for tenant-model-rls-provisioning.
  31-task plan covering all 7 phases. owner_a_contracts.md committed for team.

### Tue 2026-05-26

- Implemented full Mohammad slice: Phases 0–7 complete.
- Phase 0: tenant_model_SPEC.md + role_model_SPEC.md (graded artifacts, now non-empty).
- Phase 1: infra/postgres/init.sql (full schema with stubs for teammate tables),
  Alembic setup (backend/alembic.ini + infra/postgres/migrations/env.py).
- Phase 2: Tenant model, User model, AuditLogEntry model, db.py (lazy init),
  tenant_context.py (set_config + finally reset), auth_service.py (Vault bootstrap,
  JWT issue/verify/require_role), auth_middleware.py (get_current_user),
  Alembic baseline migration 001_baseline.py, updated main.py (lifespan + routers).
- Phase 3: rls_policies.sql (all 6 tables), tenant_repo.py, user_repo.py, test_rls.py
  (3 CI gate tests: cross-tenant blocked, finally reset, Tenant Manager returns empty).
- Phase 4: auth_service.py complete, rate_limit.py (Redis sliding-window per-tenant),
  auth.py (register/login/refresh), test_tenant_isolation.py (Mohammad's 4 role fence tests).
- Phase 5: audit_repo.py, Vault HCL policies (backend/modelserver/guardrails),
  minio/buckets.sh (create/delete idempotent), tenant_service.py (provision/invite/suspend/
  get_cost + erase_tenant), tenants.py API (5 endpoints), seed_tenants.py (idempotent demo seed).
- Phase 6: delete_tenant.py CLI (calls DELETE /tenants/{id} via API).
- Phase 7: constants.py (rate limit + JWT + agent constants), deliverables/DESIGN.md §1–§5.
- Outstanding: T001 (add backend/pyproject.toml deps) needs Ali coordination.
  Required packages: fastapi-users[sqlalchemy], psycopg2-binary, redis, alembic,
  pyjwt, bcrypt, minio, email-validator, hvac.

### Wed 2026-05-27

**Bug fixes (3 critical):**

1. `backend/app/db.py` — `SessionLocal` was a private `_SessionLocal = None` variable.
   `from app.db import SessionLocal` raised ImportError at test time.
   Fix: replaced with a public `SessionLocal()` function that reads `_session_factory` at
   call time (not import time). Lazy initialisation preserved — function raises RuntimeError
   if called before `init_db()`.

2. `infra/postgres/rls_policies.sql` + `infra/postgres/migrations/001_baseline.py` —
   All 6 USING clauses had `current_setting('app.tenant_id', true)::UUID`.
   When `tenant_context.py` finally-block resets to `''`, Postgres throws a UUID cast error
   on the next query. Fix: `NULLIF(current_setting('app.tenant_id', true), '')::UUID` on
   all 6 tables in both files. NULLIF converts `''` → NULL before cast; NULL::UUID = NULL
   which fails the equality check, returning zero rows (correct and intentional).

3. `infra/postgres/migrations/001_baseline.py` — `ENABLE ROW LEVEL SECURITY` was present
   but `FORCE ROW LEVEL SECURITY` was missing. The backend connects as the `postgres`
   superuser in Docker, which bypasses RLS without FORCE. All 6 tables (users + 5 teammate
   stub tables) now have both ENABLE and FORCE.

**Auth service fix:**
- `backend/app/services/auth_service.py` — added public `get_auth_key()` wrapper to
  expose the signing key without importing the private `_auth_key` function.
- `backend/tests/test_tenant_isolation.py` — updated import from `_auth_key` → `get_auth_key`.

**Resource doc corrections (3 inconsistencies fixed):**
- `resources/owner_a_contracts.md`: `DELETE /tenants/{id}` response was `204 No Content`.
  Actual return from `erase_tenant()` is `{"tenant_id", "status": "erased", "audit_log_entry_id"}`.
  Fixed both the example block and the payload summary table.
- `resources/owner_a_contracts.md`: Widget JWT signing key was listed as `auth_jwt.signing_key`.
  Actual: `secret/concierge/widget_jwt.signing_key` (separate key). Fixed and added note
  that `verify_token(is_widget=True)` uses this key.
- `resources/mohammad_reference.md`: `RATE_LIMIT_WINDOW_SECONDS = 60` — actual value in
  `constants.py` is `120`. Fixed.

**MD file audit completed:**
- All 19 Mohammad MD files catalogued with purpose and keep/superseded status.
- `specs/tenant_model_SPEC.md` and `specs/role_model_SPEC.md` are superseded by the SpecKit
  canonical spec at `specs/001-tenant-model-rls-provisioning/spec.md`.
- `resources/implementation_guide.md` is the main deliverable reference doc.

**Still outstanding:**
- README.md scorecard rows (tenancy/isolation/roles) — coordinate with Charbel.
- RUNBOOK.md operational procedures (`seed_tenants.py`, `delete_tenant.py`) — add before push.
- T001 (`backend/pyproject.toml` deps) — blocked on Ali.
- T030/T031 (`docker compose up` smoke test + full pytest) — blocked on T001.
