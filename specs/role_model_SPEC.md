<!-- Owner: Mohammad -->

# Feature Specification: Role Model & Auth

**Feature Branch**: `001-tenant-model-rls-provisioning`

**Created**: 2026-05-26

**Status**: Final

## User Scenarios & Testing

### User Story 1 — Tenant Admin Authentication (Priority: P1)

A business owner registers and logs in via the admin UI. On successful login, they receive
a signed JWT that encodes their `tenant_id` and `role`. Every subsequent request carries
that token. The server extracts the tenant context exclusively from the verified token —
never from the request body.

**Why this priority**: Admin auth is the entry point for all content management, widget
configuration, and lead review. No other admin workflow is accessible without it.

**Independent Test**: Call `POST /auth/login` with valid credentials. Decode the returned
JWT (without verifying signature) and confirm the payload contains `sub` (user UUID),
`tenant_id` (tenant UUID), `role: "tenant_admin"`, and `exp` (≥ 55 minutes from now).
Then call `GET /tenants/{id}` with the token — expect 200. Call the same endpoint with
`tenant_id` swapped in the request body for another tenant's ID — confirm the server
ignores the body value and returns only the authenticated tenant's data.

**Acceptance Scenarios**:

1. **Given** a registered `tenant_admin`, **When** they call `POST /auth/login` with
   correct credentials, **Then** a JWT is returned containing `{sub, tenant_id, role, exp}`
   with `role = "tenant_admin"` and a 60-minute expiry.
2. **Given** a valid JWT, **When** a request arrives with `tenant_id` in the request body
   that differs from the JWT claim, **Then** the server uses the JWT `tenant_id` and
   ignores the body value.
3. **Given** a suspended tenant's admin, **When** they call `POST /auth/login`, **Then**
   the request is rejected with 403 (inactive tenant — checked before issuing token).

---

### User Story 2 — Tenant Manager Operations (Priority: P1)

The platform operator (Tenant Manager) can create tenants, invite first admins, suspend,
reactivate, and erase tenants. The Tenant Manager is authenticated with a JWT that has
`tenant_id = null` and `role = "tenant_manager"`. Every action is logged in `audit_log`.

**Why this priority**: The Tenant Manager role is required for onboarding new business
customers. Without it, no tenant can be created and the platform cannot serve anyone.

**Independent Test**: Call `POST /auth/login` as Tenant Manager. Confirm JWT contains
`tenant_id = null` and `role = "tenant_manager"`. Call `POST /tenants` — expect 201.
Call `POST /tenants` as a `tenant_admin` — expect 403.

**Acceptance Scenarios**:

1. **Given** a `tenant_manager` JWT, **When** `POST /tenants` is called, **Then** the
   tenant is created and an `audit_log` entry `create_tenant` is written.
2. **Given** a `tenant_admin` JWT, **When** `POST /tenants` is called, **Then** the
   request is rejected with 403 (role gate enforced).
3. **Given** a `tenant_manager` performing any operation, **When** their DB session
   executes a SELECT on a tenant-content table, **Then** zero rows are returned (no
   `app.tenant_id` set → RLS returns empty).

---

### User Story 3 — Member (Widget Visitor) Authentication (Priority: P2)

A website visitor opens a page with the embedded widget. The widget exchanges the
`widget_id` for a short-lived signed JWT issued by the backend. This JWT encodes the
visitor's `tenant_id` (from the widget's configuration) and `role = "member"`. Every
`/chat` request carries this token. The token expires after 15 minutes; the widget
silently refreshes it.

**Why this priority**: Widget visitor auth is the public-facing entry point. It must be
isolated from admin auth — different signing key, shorter TTL, no user row required.

**Independent Test**: Call `POST /widget/token` with a valid `widget_id`. Decode the JWT
and confirm `role = "member"`, `tenant_id` matches the widget's tenant, and `exp` is
≈ 15 minutes. Call `POST /widget/token` with a `widget_id` from a banned origin — expect
403. Attempt to use a `member` JWT on `POST /tenants` — expect 403.

**Acceptance Scenarios**:

1. **Given** a valid `widget_id` and an allowed origin, **When** `POST /widget/token` is
   called, **Then** a JWT is returned with `{sub: null, tenant_id, role: "member", exp}`
   where `exp = now + 15 min`.
2. **Given** a `member` JWT, **When** the JWT is sent to a `tenant_admin`-only endpoint,
   **Then** the request is rejected with 403.
3. **Given** an expired `member` JWT (15 min elapsed), **When** a `/chat` request is sent,
   **Then** the server returns 401; the widget re-exchanges the `widget_id` for a new token.

---

### User Story 4 — Token Refresh (Priority: P2)

An authenticated `tenant_admin` with a near-expiry JWT can obtain a new token without
re-entering credentials. The refresh token has a longer TTL (configurable; default 7 days)
and is single-use.

**Why this priority**: Admin sessions spanning more than 60 minutes must remain usable
without forcing re-login on every action.

**Independent Test**: Obtain a token pair (access + refresh). Wait until access token
has < 5 min remaining. Call `POST /auth/refresh` with the refresh token. Confirm a new
access token is issued and the old refresh token is invalidated (a second call with the
same refresh token returns 401).

**Acceptance Scenarios**:

1. **Given** a valid refresh token, **When** `POST /auth/refresh` is called, **Then** a
   new access JWT is issued and the old refresh token is marked used (single-use).
2. **Given** an already-used refresh token, **When** `POST /auth/refresh` is called again,
   **Then** the request is rejected with 401.
3. **Given** a refresh token whose user's tenant is now suspended, **When**
   `POST /auth/refresh` is called, **Then** the request is rejected with 403.

---

### Edge Cases

- What happens when a JWT is valid but the user's `is_active = false`? The auth middleware
  must check the user's `is_active` flag on every request, not only at login.
- What happens when the `role` claim in the JWT is forged (e.g., `"tenant_manager"`)? The
  signature check using `secret/concierge/auth_jwt.signing_key` will fail — the forged
  token is rejected before any role gate is evaluated.
- What happens when the Vault signing key is rotated mid-session? All existing tokens
  become invalid. `seed.sh` uses get-or-generate to prevent accidental rotation on restart.
- What happens when a `member` JWT is replayed from a different origin? The server-side
  origin check (from `tenant.allowed_origins`) rejects the request — CORS alone is not
  the boundary.
- What if `tenant_id` is null in a `tenant_admin` JWT? The auth middleware must reject
  this token — `tenant_admin` always requires a non-null `tenant_id`.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST define exactly three roles — `tenant_manager`, `tenant_admin`,
  and `member` — as a fixed enumeration. No custom roles or configurable permission
  matrices are permitted.
- **FR-002**: Every issued JWT MUST contain exactly: `sub` (user UUID or null for visitors),
  `tenant_id` (UUID or null for tenant_manager), `role` (one of the three enum values),
  and `exp` (Unix timestamp).
- **FR-003**: Admin JWTs (`tenant_admin`, `tenant_manager`) MUST be signed with
  `secret/concierge/auth_jwt.signing_key` and expire after 60 minutes.
- **FR-004**: Widget visitor JWTs (`member`) MUST be signed with a SEPARATE key —
  `secret/concierge/widget_jwt.signing_key` — and expire after 15 minutes.
- **FR-005**: The `tenant_id` in any request MUST be sourced exclusively from the
  verified JWT claim; values provided in the request body or query parameters MUST be
  ignored.
- **FR-006**: Every endpoint MUST enforce a role gate; unauthenticated requests and
  requests with insufficient role MUST be rejected with 401 and 403 respectively.
- **FR-007**: `tenant_manager` rows in the `users` table MUST have `tenant_id = NULL`
  enforced as a NOT NULL constraint on the other direction (i.e., at the application layer
  before insert and checked by the auth middleware on each request).
- **FR-008**: `tenant_admin` rows MUST have a non-null `tenant_id` pointing to an existing
  active tenant; login for suspended tenant's admin MUST be rejected.
- **FR-009**: The signing keys for both JWT types MUST be stable across application restarts
  (get-or-generate pattern in `seed.sh`) — key rotation invalidates all sessions and
  MUST be a deliberate action.
- **FR-010**: Passwords MUST be stored as bcrypt hashes; plaintext passwords MUST never
  appear in logs, traces, or API responses.

### Key Entities

- **Role** (enum): `tenant_manager` | `tenant_admin` | `member`. Python `StrEnum`; Postgres
  `ENUM` type. The three roles encode the full capability matrix — no permission table
  required.
- **User**: A person with a platform account. Holds exactly one `role`. Widget visitors
  (`member` role) may be ephemeral — they do not require a User row; their identity is
  carried entirely in the widget JWT.
- **JWT Payload**:
  ```json
  {
    "sub":       "<user_id UUID | null for widget visitors>",
    "tenant_id": "<tenant UUID | null for tenant_manager>",
    "role":      "<tenant_manager | tenant_admin | member>",
    "exp":       <Unix timestamp>
  }
  ```

## Role Capability Matrix

| Capability | tenant_manager | tenant_admin | member |
|------------|:--------------:|:------------:|:------:|
| Create / suspend / erase tenant | ✅ | ❌ | ❌ |
| Invite first admin | ✅ | ❌ | ❌ |
| Read tenant content (leads, CMS, conversations) | ❌ (RLS blocks) | ✅ (own only) | ❌ |
| Manage widget config, allowed_origins | ❌ | ✅ | ❌ |
| Submit chat message | ❌ | ❌ | ✅ |
| Read own audit log | ✅ | ❌ | ❌ |
| Delete own content | ❌ | ✅ | ❌ |
| Blind delete (no read, just delete) | ✅ | ❌ | ❌ |

**Tenant Manager read prohibition** is structural: the DB session for Tenant Manager
requests never sets `app.tenant_id`, so the RLS policy `tenant_id = current_setting(...)`
evaluates to false for every row on every content table. An accidental SELECT returns
empty regardless of application code.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A `tenant_admin` JWT accepted on an endpoint restricted to `tenant_manager`
  returns 403 in 100% of test cases — verified by `test_tenant_isolation.py`.
- **SC-002**: A forged JWT with a modified `role` claim is rejected in 100% of test
  cases (signature verification failure).
- **SC-003**: A `member` JWT replayed from an origin not in `allowed_origins` is rejected
  with 403 in 100% of test cases — verified by `tests/test_widget_auth.py` (Charbel).
- **SC-004**: A Tenant Manager query against a content table returns zero rows in 100%
  of test cases — verified by `test_rls.py`.
- **SC-005**: JWT signing key reads from Vault add no more than 50ms to service cold-start
  time (key is cached in memory after first read, never re-fetched per request).
- **SC-006**: 100% of red-team security eval cases for role elevation are blocked.

## Assumptions

- There is no self-registration path for `tenant_manager` — the first Tenant Manager user
  is seeded via `scripts/seed_tenants.py`. Subsequent managers are created by an existing
  Tenant Manager (not in scope for Week 8).
- `member` (widget visitor) role tokens do not require a User row in the database; the
  widget JWT is sufficient to establish tenant context for a chat session.
- Role is immutable after creation — there is no endpoint to change a user's role. A
  `tenant_admin` who needs `tenant_manager` access requires a new account.
- Both JWT signing keys (`auth_jwt` and `widget_jwt`) are 32-byte random secrets stored
  as base64 strings in Vault. The algorithm is HS256.
- The 60-minute access token TTL and 15-minute widget token TTL are constants defined in
  `backend/app/constants.py`; they are not configurable per tenant.
- fastapi-users handles the underlying JWT issuance and validation machinery; the custom
  role/tenant fields are added as SQLAlchemy columns and read back via a custom dependency.
