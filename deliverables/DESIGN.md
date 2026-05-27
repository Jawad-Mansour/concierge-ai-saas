<!-- Owner: Shared -->

# Concierge — System Design

This document covers the five technical design areas graded in the Week 8 deliverable.
Each section is owned by the teammate whose slice it covers; sections are appended as
work lands. Mohammad owns §1–§5.

---

## §1 Tenant Isolation Strategy

Tenant isolation is the central design constraint of this system. **Tenant A must never
access Tenant B's data, even deliberately.** Three enforced layers are stacked so that a
single bug in any one layer cannot cause a breach.

### Layer 1 — Postgres Row-Level Security (database level)

Every tenant-scoped table (`users`, `leads`, `cms_content`, `conversations`, `embeddings`,
`widget_configs`) has `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. Each table
carries two or more per-command policies — SELECT and DELETE are separated so the Tenant
Manager's erasure path can delete without being able to read:

```sql
-- Normal tenant reads (SELECT) — requires app.tenant_id set by tenant_context.py
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON leads
    FOR SELECT
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

-- Erasure DELETEs by Tenant Manager — app.erase_target set during erase_tenant()
CREATE POLICY erase_isolation ON leads
    FOR DELETE
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
        OR tenant_id::TEXT = current_setting('app.erase_target', true)
    );
```

**Why separate SELECT vs DELETE policies**: A single `USING` policy applies to both
operations. Setting `app.tenant_id` to the target UUID would allow the DELETE (rows match)
but also allow a SELECT (same rows match), violating the TM read prohibition. Separate
per-command policies let the TM delete via `app.erase_target` without enabling reads.

The `users` table also carries a third policy for the login flow:

```sql
-- Login email lookup — app.login_lookup='true' set only inside user_repo.get_by_email()
CREATE POLICY email_login_lookup ON users
    FOR SELECT
    USING (current_setting('app.login_lookup', true) = 'true');
```

This is needed because the email lookup precedes tenant context — we cannot set
`app.tenant_id` to find the user before we know which tenant they belong to.

The database physically refuses to return rows that no policy permits. No application code
can bypass the policies except through the specific GUC variables listed above.

`NULLIF(current_setting('app.tenant_id', true), '')` is critical: `current_setting` returns
an empty string `''` when the variable has been explicitly cleared (our `finally` reset sets
it to `''`, not NULL). Casting `''` directly to UUID raises a Postgres error — `NULLIF`
converts `''` to SQL NULL first. A UUID equality check against NULL returns false → zero rows.
`FORCE ROW LEVEL SECURITY` ensures even the `postgres` superuser (used in Docker) is blocked.
This is how the **Tenant Manager read prohibition** is enforced structurally: the Tenant
Manager's session never sets
`app.tenant_id`, so any accidental SELECT on a content table returns empty.

### Layer 2 — Repository layer (first line of defence)

Every data-access query explicitly filters by tenant:

```python
db.query(Lead).filter(Lead.tenant_id == ctx.tenant_id)
```

Layer 1 is the safety net; Layer 2 is the first line. Both must be present. A developer
who forgets Layer 2 on a new query is protected by Layer 1. A developer who somehow
disables Layer 1 is still partially protected by Layer 2.

### Layer 3 — pgvector semantic search

All vector similarity searches include a metadata filter:

```python
results = collection.query(query_embeddings=[...], where={"tenant_id": ctx.tenant_id})
```

The most common real-world multi-tenant RAG data leak is a missing vector filter: source
rows are deleted but embeddings remain searchable. Our erasure path explicitly deletes
embeddings in step 4 of the 9-step sequence.

### Connection pool safety

SQLAlchemy uses a connection pool. A connection reused from a prior request carries the
previous session's `app.tenant_id` unless it is explicitly reset. Our `tenant_context.py`
dependency uses **two safety nets**:

```python
db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)})
try:
    yield db
finally:
    # Resets to '' (empty string), not NULL — NULLIF in the RLS policy converts
    # '' to NULL safely. Direct UUID cast of '' raises a Postgres error.
    db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
```

`set_config(..., true)` (third argument) makes the value transaction-scoped, so it is
automatically cleared at transaction end. The `finally` block provides a second reset for
connection-pool safety.

---

## §2 Role Model

The platform uses exactly three fixed roles. No configurable RBAC engine is used — three
named roles with fixed, enumerable capabilities can be verified by inspection and tested
exhaustively.

### Roles

| Role | Platform affiliation | tenant_id in JWT |
|------|---------------------|-----------------|
| `tenant_manager` | Platform operator | `null` |
| `tenant_admin` | One business customer | Tenant UUID |
| `member` | Widget visitor (ephemeral) | Tenant UUID (from widget config) |

### Capability matrix

| Capability | tenant_manager | tenant_admin | member |
|------------|:-:|:-:|:-:|
| Create / suspend / erase tenant | ✅ | ❌ | ❌ |
| Invite first admin | ✅ | ❌ | ❌ |
| Read tenant content | ❌ | ✅ (own) | ❌ |
| Manage widget config / allowed_origins | ❌ | ✅ | ❌ |
| Submit chat message | ❌ | ❌ | ✅ |
| Delete own tenant's content | ❌ | ✅ | ❌ |
| Blind delete (no read) | ✅ | ❌ | ❌ |

### JWT payload

```json
{
  "sub":       "<user_id UUID | null for widget visitors>",
  "tenant_id": "<tenant UUID | null for tenant_manager>",
  "role":      "tenant_manager | tenant_admin | member",
  "exp":       1234567890
}
```

`tenant_id` in the JWT payload is **always** the authority. Any `tenant_id` in the request
body, query parameters, or path (beyond routing) is ignored for security decisions.

### Two signing keys

Admin tokens (`tenant_admin`, `tenant_manager`): signed with
`secret/concierge/auth_jwt.signing_key`. TTL: 60 minutes.

Widget visitor tokens (`member`): signed with a **separate** key —
`secret/concierge/widget_jwt.signing_key`. TTL: 15 minutes. Using a separate key means a
compromised widget token cannot be used to impersonate an admin.

Both keys are generated once (get-or-generate in `seed.sh`) and stable across restarts.

### Tenant Manager read prohibition — structural enforcement

The Tenant Manager's DB session **never** sets `app.tenant_id`. RLS policy:

```sql
USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
```

With `app.tenant_id` unset → `current_setting` returns NULL → UUID cast of NULL = NULL →
`NULL = tenant_id` evaluates to NULL (not true) → row is invisible. Every content table
returns empty for the Tenant Manager regardless of what SQL they run. This is structural
(enforced by the database), not procedural (enforced by code that could have bugs).

---

## §3 Scaling Story

### At 10 tenants (current)

The shared Postgres instance, single backend process, and single Redis instance are all
sufficient. Isolation is already enforced by RLS — adding tenants has no code changes.

**Bottlenecks** at this scale: cold-start Vault reads (mitigated by in-memory key cache),
and synchronous bcrypt hashing on login (acceptable at < 100 RPS).

### At 1000 tenants

**Postgres connection pool exhaustion**: 1000 active tenants × ~5 connections each = 5000
connections. Postgres default `max_connections = 100`. Solution: add PgBouncer as a
connection pooler between the backend and Postgres. SQLAlchemy's `pool_pre_ping=True` is
already set to handle stale connections after PgBouncer recycles them.

**Redis key space growth**: rate-limit keys `ratelimit:{tenant_id}:{minute}` and session
keys `session:tenant:{tenant_id}:*`. At 1000 tenants × 2-minute window × 60 req/min =
~120K keys. Well within Redis limits. TTL-based expiry (already implemented) prevents
unbounded growth.

**MinIO bucket count**: 1000 buckets is within MinIO's supported range. Bucket-per-tenant
is intentional — it allows per-tenant access policies and simplifies erasure (delete entire
bucket, not a prefix scan).

**pgvector index scan cost**: at 1000 tenants with 10K chunks each = 10M vectors. HNSW
index (`lists` parameter) should be tuned to `sqrt(total_vectors)`. The `tenant_id` filter
in the WHERE clause applied before ANN search reduces the scan to ~10K vectors per tenant.

**Fix-priority list**:
1. PgBouncer connection pooler (highest ROI)
2. Async Celery workers for embedding jobs (unblocks the web thread)
3. Read replica for analytics/cost queries

---

## §4 Cost-Per-Tenant Model

Every LLM and embedding API call is attributed to a tenant. The cost log table stores:
`tenant_id`, `model`, `input_tokens`, `output_tokens`, `timestamp`. No message content is
stored — only token counts.

### Formula

```
cost_usd = (input_tokens / 1_000_000 × INPUT_PRICE)
         + (output_tokens / 1_000_000 × OUTPUT_PRICE)
```

Example using claude-sonnet-4-6 pricing (indicative):

```
A tenant with 500 chat sessions/week, avg 200 input tokens + 100 output tokens per turn:
  input:   500 × 200 = 100,000 tokens  ×  $3.00 / 1M  = $0.30
  output:  500 × 100 =  50,000 tokens  × $15.00 / 1M  = $0.75
  weekly cost attribution: ≈ $1.05
```

### Break-even

At $29/month SaaS price, a tenant must stay under ≈ $29 in API costs.
Break-even session count: `$29 / $1.05/week × (1 week/7 days)` ≈ **196 sessions/day**
before the tenant becomes unprofitable. The `GET /tenants/{id}/cost` endpoint lets the
Tenant Manager see weekly attribution without reading any message content.

---

## §5 Erasure Path

Full erasure is triggered by `DELETE /tenants/{id}` (Tenant Manager only).
The backend executes a fixed 9-step sequence across all stores:

| Step | Store | Operation |
|------|-------|-----------|
| 1 | Postgres: `leads` | `DELETE WHERE tenant_id = ?` |
| 2 | Postgres: `cms_content` | `DELETE WHERE tenant_id = ?` |
| 3 | Postgres: `conversations` | `DELETE WHERE tenant_id = ?` |
| 4 | Postgres: `embeddings` | `DELETE WHERE tenant_id = ?` — most commonly missed |
| 5 | Postgres: `users` | `DELETE WHERE tenant_id = ?` |
| 6 | MinIO | Remove bucket `tenant-{id}` + all objects |
| 7 | Redis | Flush keys matching `session:tenant:{id}:*` |
| 8 | Postgres: `tenants` | `DELETE WHERE id = ?` |
| 9 | Postgres: `audit_log` | INSERT `erase_tenant` entry (survives — no content) |

**Idempotency**: Each deletion step checks existence before executing. Re-running the
endpoint after a partial failure resumes from the first incomplete step without duplicating
audit entries.

**Tenant Manager read prohibition during erasure**: The Tenant Manager's session has no
`app.tenant_id` set. All DELETEs use explicit `WHERE tenant_id = ?` with a literal UUID.
An accidental SELECT would return empty (RLS enforces this). The erasure path deliberately
uses `DELETE` without a prior `SELECT` — it deletes blindly, never reads content.

**Implementation**: `scripts/delete_tenant.py` is the CLI wrapper. It authenticates as
the Tenant Manager, calls `DELETE /tenants/{id}`, and prints each store's deletion
confirmation. The backend service implements the full sequence in
`backend/app/services/tenant_service.py:erase_tenant()`.
