<!-- Owner: Mohammad -->

# Feature Specification: Tenant Model & Isolation

**Feature Branch**: `001-tenant-model-rls-provisioning`

**Created**: 2026-05-26

**Status**: Final

## User Scenarios & Testing

### User Story 1 — Tenant Provisioning (Priority: P1)

A Tenant Manager creates a new tenant account for a business customer. The tenant is
assigned a stable unique identifier that flows through every data store. The Tenant
Manager then generates a first-admin invite link for the business owner.

**Why this priority**: Every other slice (RAG, widget, guardrails) is blocked until at
least one tenant exists with a valid `tenant_id`. Provisioning is the root of the entire
multi-tenant system.

**Independent Test**: Run `scripts/seed_tenants.py` and confirm two tenants are created
with unique UUIDs. Query `SELECT id, slug FROM tenants` and verify both rows exist with
no shared `id`.

**Acceptance Scenarios**:

1. **Given** no tenant exists, **When** the Tenant Manager calls `POST /tenants`, **Then**
   a new Tenant row is created with a server-generated UUID `id`, a validated `slug`, and
   `is_active = true`.
2. **Given** a tenant exists, **When** a second `POST /tenants` with the same `slug` is
   submitted, **Then** the request is rejected with a conflict error and no row is created.
3. **Given** a tenant exists, **When** `POST /tenants/{id}/invite-admin` is called, **Then**
   a signed JWT invite token (15-min TTL) is returned and logged in `audit_log`.

---

### User Story 2 — Tenant Isolation via `tenant_id` (Priority: P1)

All tenant-scoped data — leads, CMS content, conversations, embeddings, widget config —
references a single `tenant_id` (UUID). Every read query is physically restricted to
rows matching the requesting tenant's ID. A tenant_admin can never read another tenant's
data even if they craft a direct database query.

**Why this priority**: Isolation is the graded constraint. Any breach means the project
fails. This story must be verified before any other slice ships data.

**Independent Test**: Create Tenant A and Tenant B. Insert one row into `leads` for each.
Authenticate as Tenant A's admin. Query `SELECT * FROM leads`. Confirm only Tenant A's
row is returned — Tenant B's row is invisible, not just filtered by application code.

**Acceptance Scenarios**:

1. **Given** the `app.tenant_id` session variable is set to Tenant A's UUID, **When**
   `SELECT * FROM leads` is executed, **Then** only rows where `tenant_id = Tenant A.id`
   are returned (RLS enforces this at the database level).
2. **Given** the `app.tenant_id` session variable is not set (empty string), **When**
   `SELECT * FROM leads` is executed, **Then** zero rows are returned (policy returns false
   for NULL context — Tenant Manager read prohibition).
3. **Given** a connection is reused from a pool after Tenant A's request, **When** a new
   request for Tenant B starts, **Then** the `app.tenant_id` value from the prior request
   is not present (the `finally` reset cleared it).

---

### User Story 3 — Tenant Suspension and Reactivation (Priority: P2)

A Tenant Manager can suspend a tenant (set `is_active = false`). Suspended tenants cannot
log in and their widget returns an inactive error. The Tenant Manager can reactivate the
tenant. Both actions are logged in `audit_log`.

**Why this priority**: Operational control over tenants is required before the first paid
customer. Billing failures, abuse, or non-payment require the ability to suspend.

**Independent Test**: Create a tenant, suspend it via `PATCH /tenants/{id}/suspend`,
attempt login as that tenant's admin — expect 403. Reactivate via
`PATCH /tenants/{id}/reactivate`, attempt login again — expect 200.

**Acceptance Scenarios**:

1. **Given** an active tenant, **When** Tenant Manager calls `PATCH /tenants/{id}/suspend`,
   **Then** `is_active` becomes `false` and an `audit_log` entry `suspend_tenant` is written.
2. **Given** a suspended tenant, **When** a `tenant_admin` attempts to authenticate,
   **Then** the request is rejected with a 403 (inactive tenant).
3. **Given** a suspended tenant, **When** Tenant Manager calls
   `PATCH /tenants/{id}/reactivate`, **Then** `is_active` becomes `true`.

---

### User Story 4 — Tenant Erasure (Priority: P2)

A Tenant Manager can permanently erase all data belonging to a tenant across every data
store: Postgres tables, pgvector embeddings, MinIO objects, Redis sessions, and the tenant
row itself. The erasure is audited but the audit entry survives (it contains no tenant
content).

**Why this priority**: GDPR/CCPA right-to-erasure is a legal requirement. The most
commonly missed store is the vector index — this must be explicit.

**Independent Test**: Run `scripts/delete_tenant.py <tenant_id>`. Confirm: (a) zero rows
remain in `leads`, `cms_content`, `conversations`, `embeddings`, `users` for that
`tenant_id`; (b) MinIO bucket `tenant-{id}` no longer exists; (c) Redis returns no keys
matching `session:tenant:{id}:*`; (d) one `erase_tenant` audit entry exists.

**Acceptance Scenarios**:

1. **Given** a tenant with data in all stores, **When** erasure is triggered, **Then** all
   nine deletion steps complete in order and each store deletion is confirmed.
2. **Given** an erasure interrupted after step 3, **When** erasure is re-triggered, **Then**
   the completed steps are skipped (idempotent) and remaining steps execute.
3. **Given** a Tenant Manager performing erasure, **When** any accidental SELECT is executed
   without `app.tenant_id` set, **Then** zero content rows are returned (read prohibition
   enforced structurally by RLS).

---

### Edge Cases

- What happens when `allowed_origins` is empty? Widget token requests are rejected with
  403 — no valid origin means the widget cannot be embedded anywhere.
- What happens when `slug` contains uppercase or special characters? Validation rejects it
  at input; only `^[a-z0-9-]{2,63}$` is accepted.
- What happens when `id` is provided in the `POST /tenants` body? The provided value is
  silently discarded; the server generates the UUID.
- What happens when erasure partially fails at MinIO? Each store step is logged before
  execution; re-run resumes from the first incomplete step.

## Requirements

### Functional Requirements

- **FR-001**: The platform MUST identify every tenant by a server-generated UUID that is
  stable across all stores and never reused after erasure.
- **FR-002**: Every tenant-scoped table MUST have `tenant_id UUID NOT NULL` referencing
  `tenants.id`, with a Postgres RLS policy that physically restricts rows to the active
  request's tenant context.
- **FR-003**: The `tenant_id` variable MUST be set in a per-transaction, connection-safe
  way so that connection pool reuse cannot leak one tenant's context into another request.
- **FR-004**: The `tenant_id` MUST always come from the verified JWT claim, never from
  the request body or query parameter.
- **FR-005**: A `slug` MUST be unique across all tenants, match `^[a-z0-9-]{2,63}$`, and
  be immutable after creation.
- **FR-006**: `allowed_origins` MUST be validated as proper origin strings
  (`scheme://host[:port]`) at write time; malformed entries MUST be rejected.
- **FR-007**: Tenant suspension MUST prevent all authentication for that tenant's users
  without deleting any data.
- **FR-008**: Full tenant erasure MUST remove data from all nine stores in a defined order,
  logging each completed step before proceeding to the next.
- **FR-009**: The Tenant Manager MUST be structurally prevented from reading tenant content
  via RLS (no `app.tenant_id` set → zero rows returned on any content table SELECT).
- **FR-010**: The vector similarity index MUST be explicitly included in the erasure path;
  embeddings are searchable independently of their source rows.

### Key Entities

- **Tenant**: A business customer of the platform. Identified by UUID `id`. Has a unique
  URL-safe `slug`, a list of `allowed_origins` for widget embedding, an `is_active` flag,
  and `created_at` timestamp.
- **AuditLogEntry**: An immutable record of every Tenant Manager action. References the
  actor (User), the target tenant (Tenant), and an action name from a fixed enumeration.
  Never updated or deleted.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A cross-tenant data query (Tenant A's admin querying Tenant B's leads)
  returns zero rows in 100% of test cases — verified by `test_rls.py`.
- **SC-002**: After a connection pool reuse simulation, the prior tenant's `app.tenant_id`
  is absent in 100% of sampled connections — verified by `test_rls.py`.
- **SC-003**: Full tenant erasure removes data from all nine stores and completes in under
  30 seconds for a tenant with up to 10,000 content rows.
- **SC-004**: Re-running erasure after a partial failure produces the same final state as
  a clean run — no orphaned rows, no duplicate audit entries.
- **SC-005**: Zero red-team security eval failures for cross-tenant isolation attacks
  (100% pass rate — never lowered).

## Assumptions

- `tenant_id` is a UUID v4 generated by the application layer (not the database `gen_random_uuid()`),
  so it is available before the INSERT and can be embedded in the JWT invite token.
- Tenant slugs are set at creation and never renamed; downstream systems (MinIO bucket names,
  Redis key prefixes) use `tenant_id` (UUID), not `slug`, to avoid rename cascades.
- The `allowed_origins` list is managed exclusively by the Tenant Admin via the admin UI;
  it is not writable from the public widget API.
- All eight tables requiring RLS are listed in `data-model.md`; any new tables added by
  teammates must be coordinated with Mohammad for RLS policy application.
- The `audit_log` table intentionally has no RLS — it contains only action metadata
  (no message content, no PII from visitors) and must be readable by the Tenant Manager
  for operational review.
