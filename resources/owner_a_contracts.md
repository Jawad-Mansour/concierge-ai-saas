# Owner A — Team Integration Guide

<!-- Owner: Mohammad -->

**Slice**: Platform, Tenancy, Isolation & Provisioning  
**Owner**: Mohammad

This file is the **single source of truth** for everything your slice depends on from mine.
If something changes here I will update this file and flag it in the PR description.

---

## What I Built

My slice is the foundation every other slice runs on. Nothing works without this layer.

| Component | What it does |
|-----------|-------------|
| **Authentication** | JWT login/refresh/register. Issues tokens for `tenant_admin`, `tenant_manager`, and `member` (visitor) roles. |
| **Authorization middleware** | `get_current_user` and `require_role` FastAPI dependencies — verify the token, extract the user, block wrong roles. |
| **Tenant context / RLS** | `set_tenant_context` dependency — sets `app.tenant_id` on the DB connection so Postgres RLS filters rows automatically. Always resets in `finally` to prevent cross-tenant leaks across pooled connections. |
| **Tenant provisioning** | `POST /tenants`, `PATCH /tenants/{id}`, `DELETE /tenants/{id}` — Tenant Manager only. Full erasure deletes data from every table + MinIO + Redis in the correct order. |
| **User management** | Invite flow, user CRUD within a tenant. |
| **Rate limiting** | Per-tenant Redis counter. Tenant A hitting the limit never affects Tenant B. Returns `HTTP 429` with `Retry-After`. |
| **Database migrations** | All Alembic migrations. Every table I own has `tenant_id UUID NOT NULL` + RLS policy. I also write the RLS policies for Ali's tables (`leads`, `conversations`, `embeddings`) and Charbel's table (`widget_configs`). |
| **Vault secrets** | `infra/vault/seed.sh` seeds the JWT signing key and DB credentials on first boot. All services read from Vault at runtime — never from `.env`. |
| **Audit log** | Every Tenant Manager action (create/suspend/erase tenant) is written to `audit_log`. Cross-tenant by design — no RLS. |

---

## Ali — Agent, RAG, Memory, Chat

### What you get from me

**1. Auth dependencies — import these, do not rewrite them**

```python
from app.middleware.auth_middleware import get_current_user, require_role
from app.middleware.tenant_context import set_tenant_context
from app.models.user import User
```

**2. `get_current_user` — decoded User object on every request**

```python
@router.get("/leads")
def get_leads(current_user: User = Depends(get_current_user)):
    tenant_id = current_user.tenant_id  # UUID — always present for tenant_admin/member
    role      = current_user.role       # "tenant_admin" | "member"
    user_id   = current_user.id         # UUID
```

`User` fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | `UUID` | From the `users` table |
| `tenant_id` | `UUID \| None` | Always set for `tenant_admin` and `member`; `None` only for `tenant_manager` |
| `role` | `str` | `"tenant_admin"`, `"tenant_manager"`, `"member"` |
| `email` | `str` | |
| `is_active` | `bool` | False = suspended |

**3. `require_role` — role gate, returns 403 if wrong**

```python
@router.post("/conversations")
def create_conversation(current_user: User = Depends(require_role("tenant_admin"))):
    ...
```

**4. `set_tenant_context` — RLS-scoped DB session**

```python
@router.get("/conversations")
def get_conversations(db: Session = Depends(set_tenant_context)):
    # db already has app.tenant_id set — RLS filters automatically
    # still add explicit .filter(Conversation.tenant_id == ...) as first line of defense
    ...
```

**5. Rate limit response — your `/chat` route will receive this from my middleware**

```
HTTP 429 Too Many Requests
Retry-After: <seconds until window resets>

Body: { "detail": "Rate limit exceeded" }
```

The counter is per-tenant, per 60-second window. Threshold: 60 messages/minute.  
`Retry-After` = `60 - (unix_time % 60)`.

**6. Redis key namespace — do not write outside this pattern**

Your session keys must follow this exact format (I flush this pattern on tenant erasure):

```
session:tenant:{tenant_id}:{conversation_id}
```

Example: `session:tenant:a1b2c3d4-...:f9e8d7c6-...`

**7. pgvector — every similarity search must include tenant_id filter**

```python
# CORRECT
results = vector_store.similarity_search(
    query_embedding,
    k=5,
    filter={"tenant_id": str(current_user.tenant_id)}
)

# WRONG — exposes all tenants' embeddings
results = vector_store.similarity_search(query_embedding, k=5)
```

**8. RLS policies for your tables — I write and own these**

| Table | Your model owns it | My RLS policy covers it |
|-------|--------------------|------------------------|
| `leads` | Ali | Yes |
| `conversations` | Ali | Yes |
| `embeddings` | Ali | Yes |

### What I need from you

| # | What I need | Why | Where I use it |
|---|-------------|-----|----------------|
| 1 | Confirm the embeddings table is named exactly `embeddings` | Erasure step 4: `DELETE FROM embeddings WHERE tenant_id = ?` | `scripts/delete_tenant.py` |
| 2 | Confirm Redis session key format is `session:tenant:{tenant_id}:{conversation_id}` | Erasure step 7: flush `session:tenant:{tenant_id}:*` | `scripts/delete_tenant.py` |
| 3 | Tell me which pgvector library you use (`pgvector-python` direct, LangChain, LlamaIndex, etc.) | The `filter=` syntax differs per library — I need to document the correct call in contracts | `owner_a_contracts.md` §7 |

### Payload summary

```
I give you:
  User { id, tenant_id, role, email, is_active }        ← via get_current_user
  Session (DB) with app.tenant_id set                   ← via set_tenant_context
  HTTP 429 + Retry-After header                         ← from rate limiter

I need from you:
  Confirm: table name "embeddings"
  Confirm: Redis key "session:tenant:{tid}:{cid}"
  Tell me: which pgvector library
```

---

## Jana — Models, Security, Guardrails

### What you get from me

**1. JWT payload — your guardrails service reads the `role` claim**

Every token I issue contains:

```json
{
  "sub": "user-uuid-string",
  "tenant_id": "tenant-uuid-string-or-null",
  "role": "tenant_admin",
  "exp": 1748999999
}
```

The `role` field is the authoritative claim for security enforcement:
- `tenant_manager` — platform operator, no tenant content access
- `tenant_admin` — one business's admin, scoped to their tenant
- `member` — anonymous visitor, scoped to one tenant via widget JWT

Widget visitor tokens have `role = "member"` and `tenant_id` = the widget's tenant.  
They are validated by `auth_middleware.py` exactly like admin tokens — same signature, same claims.

**2. Auth dependency — if your guardrails sidecar needs to verify tokens**

```python
from app.middleware.auth_middleware import get_current_user
```

`get_current_user` returns the `User` object or raises `HTTP 401` if the token is invalid/expired.

**3. Audit log — cross-tenant security events land here**

Table: `audit_log`  
No RLS (cross-tenant by design). Every Tenant Manager action is written here.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | |
| `action` | str | e.g. `"erase_tenant"`, `"suspend_tenant"` |
| `actor_id` | UUID | The Tenant Manager's user ID |
| `target_tenant_id` | UUID | Which tenant was affected |
| `created_at` | DateTime | UTC |

**4. Rate limit response — if guardrails needs to handle 429**

```
HTTP 429 Too Many Requests
Retry-After: <seconds>
```

### What I need from you

| # | What I need | Why | Where I use it |
|---|-------------|-----|----------------|
| 1 | `metrics.py` function signature | I call it from Tenant Manager to attribute compute cost per tenant | `backend/app/services/tenant_service.py` |

Specifically I need to know:
- Function name
- Parameters (does it take `tenant_id`? a date range?)
- Return type (a float? a dict with breakdown?)

### Payload summary

```
I give you:
  JWT { sub, tenant_id, role, exp }                     ← in every Authorization header
  User { id, tenant_id, role, email, is_active }        ← via get_current_user dependency
  audit_log table (read-only for you)

I need from you:
  metrics.py function signature (name, params, return type)
```

---

## Charbel — Widget, Admin UX, CI/CD

### What you get from me

**1. Auth dependencies for the admin panel**

```python
from app.middleware.auth_middleware import get_current_user, require_role

# Admin dashboard — only tenant_admin
@router.get("/admin/dashboard")
def dashboard(current_user: User = Depends(require_role("tenant_admin"))):
    ...
```

**2. `allowed_origins` on the Tenant model — drives your CORS and CSP**

```python
from app.repositories.tenant_repo import tenant_repo

tenant = tenant_repo.get_by_id(tenant_id, db)
origins = tenant.allowed_origins  # List[str], e.g. ["https://acme.com", "https://demo.acme.com"]
```

Use this list for:
- CORS `Access-Control-Allow-Origin` header
- `Content-Security-Policy: frame-ancestors` header
- Server-side 403 check if origin not in the list

**3. Widget JWT validation — I handle this for you**

`auth_middleware.py` validates widget visitor tokens automatically.  
The widget JWT your `widget_auth_service.py` generates must follow this structure:

```json
{
  "sub": "visitor-session-uuid",
  "tenant_id": "tenant-uuid",
  "role": "member",
  "exp": 1748999999
}
```

Signed with HS256 using the key at `secret/concierge/auth_jwt.signing_key` in Vault.  
My middleware validates it exactly like an admin token — no special handling needed on your side.

**4. Auth endpoints for your admin dashboard login**

`POST /auth/login`:
```json
Request:  { "email": "string", "password": "string" }
Response: { "access_token": "string", "token_type": "bearer", "expires_in": 3600 }
Errors:   401 (wrong credentials), 403 (account suspended)
```

`POST /auth/refresh`:
```json
Request:  empty body — send Bearer token in Authorization header
Response: { "access_token": "string", "token_type": "bearer", "expires_in": 3600 }
Errors:   401 (expired or invalid)
```

**5. Tenant Manager endpoints (for your admin Streamlit panel)**

`GET /tenants` — list all tenants (Tenant Manager only):
```json
Response: [
  {
    "id": "uuid",
    "name": "Acme Coffee",
    "slug": "acme-coffee",
    "allowed_origins": ["https://acme.com"],
    "is_active": true,
    "created_at": "2025-01-15T10:00:00Z"
  }
]
```

`POST /tenants` — create tenant:
```json
Request:  { "name": "string", "slug": "string", "allowed_origins": ["string"] }
Response: { "id": "uuid", "name": "string", "slug": "string", "allowed_origins": ["string"], "is_active": true, "created_at": "datetime" }
Errors:   409 (slug taken), 422 (validation)
```

`PATCH /tenants/{id}` — suspend/reactivate:
```json
Request:  { "is_active": false }
Response: { "id": "uuid", "is_active": false, ... }
```

`DELETE /tenants/{id}` — full erasure (no body, no response body):
```
Response: 204 No Content
```

### What I need from you

| # | What I need | Why | Where I use it |
|---|-------------|-----|----------------|
| 1 | Functions available in `token_utils.py` | I want to call existing widget token logic rather than duplicate it | `auth_middleware.py` widget token validation |
| 2 | `vault/seed.sh` key generation: is it get-or-generate? | The JWT signing key must survive container restarts — it must be generated once, then reused | `infra/vault/seed.sh` |

### Payload summary

```
I give you:
  GET    /tenants              → List[Tenant]
  POST   /tenants              ← { name, slug, allowed_origins }
  PATCH  /tenants/{id}         ← { is_active }
  DELETE /tenants/{id}         → 204
  POST   /auth/login           ← { email, password }   → { access_token, token_type, expires_in }
  POST   /auth/refresh         → { access_token, token_type, expires_in }
  User { id, tenant_id, role } ← via get_current_user dependency
  tenant.allowed_origins       ← via tenant_repo.get_by_id()

I need from you:
  token_utils.py function list
  vault/seed.sh get-or-generate confirmation for JWT key
```

---

## Technical Reference

The sections below are the definitive, versioned contracts.
Update the relevant section if any interface changes — not just the narrative above.

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
