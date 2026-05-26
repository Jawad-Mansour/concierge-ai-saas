# Owner A — Team Contracts

<!-- Owner: Mohammad -->

**Slice**: Platform, Tenancy, Isolation & Provisioning  
**Owner**: Mohammad

This file is the **single source of truth** for everything your slice depends on from mine.
If something changes here I will update this file and flag it in the PR description.

---

## 1. Table Names & Schema Conventions

These are the definitive table names. Use them in your SQLAlchemy models, migrations, and queries.
Every table in this list has `tenant_id UUID NOT NULL` and a RLS policy applied by me.

| Table | Owner (model/service) | tenant_id present | RLS policy |
|-------|-----------------------|-------------------|------------|
| `tenants` | Mohammad | No (IS the tenant) | No RLS |
| `users` | Mohammad | Yes (NULL for tenant_manager) | Yes |
| `audit_log` | Mohammad | No (cross-tenant by design) | No RLS |
| `leads` | Ali | Yes | Yes — Mohammad writes policy |
| `cms_content` | Ali | Yes | Yes — Mohammad writes policy |
| `conversations` | Ali | Yes | Yes — Mohammad writes policy |
| `embeddings` | Ali | Yes | Yes — Mohammad writes policy |
| `widget_configs` | Charbel | Yes | Yes — Mohammad writes policy |

**tenant_id type**: `UUID` (Python: `uuid.UUID`, Postgres: `UUID NOT NULL`)  
**tenant_id source in every request**: extracted from verified JWT claim — never from request body.

---

## 2. JWT Payload Structure

Every access token issued by `POST /auth/login` or `POST /auth/refresh` contains:

```json
{
  "sub": "user-uuid-string",
  "tenant_id": "tenant-uuid-string-or-null",
  "role": "tenant_admin",
  "exp": 1748999999
}
```

| Field | Type | Notes |
|-------|------|-------|
| `sub` | string (UUID) | The user's `id` from the `users` table |
| `tenant_id` | string (UUID) or `null` | `null` for `tenant_manager` accounts |
| `role` | string enum | One of: `tenant_manager`, `tenant_admin`, `member` |
| `exp` | integer (Unix timestamp) | Token lifetime: 3600 seconds |

**Signing**: HS256, key fetched from Vault at `secret/concierge/auth_jwt.signing_key`

**Widget visitor tokens** (issued by Charbel's `widget_auth_service.py`): same structure,
`role = "member"`, `tenant_id` = the widget's tenant. My `auth_middleware.py` validates them.

---

## 3. Three-Role Capability Matrix

```
tenant_manager  — platform operator; tenant_id = null in JWT
tenant_admin    — one business's admin; tenant_id = their tenant's UUID
member          — anonymous visitor; scoped to one tenant via widget JWT
```

| Capability | tenant_manager | tenant_admin | member |
|------------|:--------------:|:------------:|:------:|
| Create / suspend / erase tenants | ✅ | ❌ | ❌ |
| Read tenant conversations, leads, CMS | ❌ | ✅ (own only) | ❌ |
| Write leads | ❌ | ✅ | ✅ (via agent) |
| Configure agent / guardrails | ❌ | ✅ | ❌ |
| Access `/chat` | ❌ | ✅ | ✅ |
| Access `/admin` | ❌ | ✅ | ❌ |
| Access `/tenants` endpoints | ✅ | ❌ | ❌ |
| View aggregate cost (no content) | ✅ | ❌ | ❌ |

**Critical rule**: `tenant_manager` has **no RLS bypass on content**.
Its DB session never sets `app.tenant_id`, so any accidental SELECT on a tenant-scoped
table returns empty rows. It deletes blindly — it never reads what it deletes.

---

## 4. FastAPI Dependency Signatures

### `get_current_user` — verify token and return the User object

```python
from app.middleware.auth_middleware import get_current_user
from app.models.user import User

@router.get("/your-endpoint")
def your_endpoint(current_user: User = Depends(get_current_user)):
    tenant_id = current_user.tenant_id  # UUID or None
    role = current_user.role            # Role enum
```

### `require_role` — enforce a role gate (returns 403 if wrong role)

```python
from app.middleware.auth_middleware import require_role

@router.get("/admin-only")
def admin_only(current_user: User = Depends(require_role("tenant_admin"))):
    ...

@router.post("/tenants")
def create_tenant(current_user: User = Depends(require_role("tenant_manager"))):
    ...
```

### `set_tenant_context` — set app.tenant_id for RLS (use instead of get_db directly)

```python
from app.middleware.tenant_context import set_tenant_context

@router.get("/leads")
def get_leads(db: Session = Depends(set_tenant_context)):
    # db already has app.tenant_id set — RLS filters automatically
    # still add .filter(Lead.tenant_id == current_user.tenant_id) as first line of defense
    ...
```

**Important**: `tenant_manager` endpoints must NOT use `set_tenant_context`.
Use raw `get_db` instead — Tenant Manager runs without a tenant context.

---

## 5. Authentication Endpoint Contracts

### POST /auth/register

**Use**: First-admin invite acceptance only. `tenant_id` and `role` come from invite token claims.

```json
Request:  { "email": "string", "password": "string", "invite_token": "string" }
Response: { "user_id": "uuid", "email": "string", "role": "string", "tenant_id": "uuid" }
Errors:   400 (bad input), 409 (email taken), 422 (bad/expired invite)
```

### POST /auth/login

```json
Request:  { "email": "string", "password": "string" }
Response: { "access_token": "string", "token_type": "bearer", "expires_in": 3600 }
Errors:   401 (wrong credentials), 403 (account suspended)
```

### POST /auth/refresh

```json
Request:  empty body — Bearer token in Authorization header
Response: { "access_token": "string", "token_type": "bearer", "expires_in": 3600 }
Errors:   401 (expired or invalid)
```

---

## 6. Tenant Model Fields

The `Tenant` SQLAlchemy model (`backend/app/models/tenant.py`):

```python
id              UUID        # PK, generated server-side — never from request body
name            String(255) # Display name e.g. "Acme Coffee"
slug            String(63)  # URL-safe, unique, immutable e.g. "acme-coffee"
allowed_origins ARRAY(Text) # Per-tenant origins allowed to embed the widget
is_active       Boolean     # False = suspended; all users blocked from login
created_at      DateTime    # UTC, set at provisioning
```

**`allowed_origins` usage** (Charbel): drives CORS headers and `Content-Security-Policy: frame-ancestors`.
Read via `tenant_repo.get_by_id(tenant_id, db).allowed_origins`. Returns a Python list of strings.

---

## 7. pgvector Filter Convention

**Every** vector similarity search must include a tenant_id filter. No exceptions.

```python
# CORRECT — always include filter
results = vector_store.similarity_search(
    query_embedding,
    k=5,
    filter={"tenant_id": str(current_user.tenant_id)}
)

# WRONG — exposes all tenants' embeddings
results = vector_store.similarity_search(query_embedding, k=5)
```

The `embeddings` table has `tenant_id UUID NOT NULL` and a RLS policy — but the application-layer
filter must still be present. RLS is the safety net; the filter is the first line of defense.

---

## 8. Redis Key Convention

Session memory keys (Ali's scope):

```
session:tenant:{tenant_id}:{conversation_id}
```

Rate limit counters (Mohammad's scope — do not write to these from other services):

```
ratelimit:{tenant_id}:{unix_minute}
```

**Erasure**: `delete_tenant.py` flushes all `session:tenant:{tenant_id}:*` keys.
Ali must confirm this pattern matches what `memory_service.py` writes.

---

## 9. Rate Limit Response

When a tenant exceeds `MAX_MESSAGES_PER_MINUTE` (default: 60), the `/chat` and
`/widget/token` routes return:

```
HTTP 429 Too Many Requests
Retry-After: <seconds until current window expires>
```

This is **per-tenant** — Tenant A hitting the limit does not affect Tenant B.
The counter resets every 60 seconds. `Retry-After` = `60 - (unix_time % 60)`.

Jana: the noisy-neighbor test should send N+1 requests as Tenant A and N requests as
Tenant B in the same 60-second window. Tenant A → 429, Tenant B → 200.

---

## 10. Erasure Path Sequence

When `DELETE /tenants/{id}` is called (Tenant Manager only), the following deletions
execute in this exact order:

```
1. DELETE FROM leads           WHERE tenant_id = ?
2. DELETE FROM cms_content     WHERE tenant_id = ?
3. DELETE FROM conversations   WHERE tenant_id = ?
4. DELETE FROM embeddings      WHERE tenant_id = ?   ← Ali: confirm table name
5. DELETE FROM users           WHERE tenant_id = ?
6. Delete MinIO bucket         tenant-{tenant_id}
7. Flush Redis keys            session:tenant:{tenant_id}:*
8. DELETE FROM tenants         WHERE id = ?
9. Write audit_log entry       action="erase_tenant"
```

Each step is idempotent — re-running after a partial failure is safe.
The Tenant Manager's session has no `app.tenant_id` set during this operation —
any accidental SELECT returns empty rows (RLS enforces it).

---

## 11. Coordination Requests

Before implementing, I need confirmation from:

| Who | What I need | Why | Urgency |
|-----|-------------|-----|---------|
| **Ali** | Exact table name for embeddings (`embeddings`?) | Erasure step 4 + RLS policy | Before Phase 2 |
| **Ali** | Redis session key format | Erasure step 7 flush pattern | Before Phase 4 |
| **Ali** | pgvector library used (pgvector-python? LangChain?) | Affects filter syntax | Before Phase 2 |
| **Jana** | `metrics.py` function signature | Cost attribution call | Before Phase 5 |
| **Charbel** | `token_utils.py` functions available | Avoid duplicating token logic | Before Phase 3 |
| **Charbel** | `vault/seed.sh` key generation: get-or-generate for JWT signing key? | Key must survive restarts | Before Phase 3 |
