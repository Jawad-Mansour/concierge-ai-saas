<!-- Owner: Shared -->

# Concierge — Architecture Decision Records

Each entry documents a non-obvious design choice, the alternatives considered, and why the chosen path was taken.

---

## ADR-001: Postgres RLS as the database-level isolation boundary

**Decision**: Every tenant-scoped table has `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` with policy `USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)`.

**Alternatives considered**:
- Separate database per tenant — operationally expensive at scale; PgBouncer and migrations become N-times harder.
- Schema-per-tenant — still one Postgres instance but N schemas; migration tooling complexity with no meaningful security gain over RLS.
- Application-only filtering — no structural guarantee; a missing `.filter()` in one query is a silent cross-tenant data leak.

**Why this**:
Three layered defences are stacked (RLS + repo `.filter()` + pgvector `where=`), so a bug in any single layer cannot cause a breach. RLS is enforced at the Postgres query executor — application code cannot bypass it. `FORCE RLS` ensures even the `postgres` superuser (used in Docker) is blocked, so tests running as superuser actually test the policy.

**NULLIF guard**: `current_setting` returns `''` (empty string) when the variable has been cleared via the `finally` reset. Casting `''` to UUID raises a Postgres error. `NULLIF(..., '')` converts `''` to SQL NULL first; a UUID equality against NULL evaluates to NULL (not true), returning zero rows. This is how the Tenant Manager read prohibition is structurally enforced.

---

## ADR-002: Three fixed roles, no configurable RBAC

**Decision**: Exactly three roles — `tenant_manager`, `tenant_admin`, `member`. No permissions table, no role-assignment UI.

**Alternatives considered**:
- Full RBAC with a `permissions` table and role-assignment endpoints — more flexible but introduces an authorization surface where misconfiguration causes privilege escalation.
- Two roles (platform + tenant) — loses the distinction between the platform operator and tenant's own admin; conflates concerns.

**Why this**:
Three named roles with fixed, enumerable capabilities can be verified by inspection and tested exhaustively. Adding a fourth role requires a code change and a PR review — that friction is intentional. The capability matrix is in `DESIGN.md §2`.

---

## ADR-003: Two separate JWT signing keys

**Decision**: Admin tokens (`tenant_admin`, `tenant_manager`) use `secret/concierge/auth_jwt.signing_key`. Widget visitor tokens (`member`) use a separate `secret/concierge/widget_jwt.signing_key`. TTLs differ: 60 min vs 15 min.

**Alternatives considered**:
- Single signing key — simpler, but a leaked widget token (public-facing) would allow impersonation of admin users.

**Why this**:
A compromised widget token (which is distributed to any browser that visits a tenant's site) cannot be used to call admin-only endpoints, even if the attacker knows to change the `role` claim — the signature wouldn't verify under the admin key. The two-key design makes the trust domains structurally separate.

---

## ADR-004: Invite-token-only admin registration

**Decision**: `POST /auth/register` requires an `invite_token` JWT. `tenant_id` and `role` come exclusively from the verified token — never from the request body.

**Alternatives considered**:
- Open registration with admin approval — complicates the provisioning flow without improving security.
- Accepting `tenant_id` from the body — a single-line cross-tenant breach: any user could register as an admin of any tenant by supplying an arbitrary UUID.

**Why this**:
The invite token is the proof-of-authorization issued by the Tenant Manager. The server verifies its signature and reads claims from it; any body-supplied `tenant_id` is silently ignored. This is tested explicitly in `test_provisioning.py::TestRegister::test_register_body_tenant_id_ignored`.

---

## ADR-005: Connection pool `finally` reset pattern

**Decision**: `tenant_context.py` FastAPI dependency sets `app.tenant_id` for the request and resets it to `''` in a `finally` block. `set_config` is called with `transaction_scope=true` (third argument) for defense-in-depth.

**Alternatives considered**:
- Relying solely on `set_config(..., true)` (transaction-scoped) — adequate for explicit transactions but ambiguous when SQLAlchemy auto-commits or when connections are reused after a transaction ends mid-request.
- Not resetting — pooled connections carry the previous session's `app.tenant_id` to the next request, guaranteed cross-tenant leak.

**Why this**:
Two safety nets: `set_config(..., true)` clears the value at transaction end; the `finally` block clears it at request end regardless of commit/rollback state. The reset uses `''`, not NULL, because `NULLIF` in the RLS policy converts `''` to NULL — direct UUID cast of NULL is valid, but direct UUID cast of `''` raises a Postgres error.

---

## ADR-006: Agent bounded loop (max 5 tool calls, 2000 tokens)

**Decision**: The LLM agent is hard-capped at 5 tool calls and 2000 output tokens per turn.

**Alternatives considered**:
- Unlimited tool calls — exposes the platform to prompt-injected infinite loops and unbounded API cost.
- Cap per session instead of per turn — harder to enforce; a single malicious turn could still exhaust budget.

**Why this**:
Cost control and injection resistance. The cap is set at the platform layer (not in the system prompt) so tenants cannot override it via persona config. If the cap is hit, the agent returns a graceful escalation response rather than an error.

---

## ADR-007: Classifier router before the LLM agent

**Decision**: Every incoming message is first routed by a lightweight intent classifier (ONNX/sklearn, no GPU). Only messages classified as "hard" or "ambiguous" reach the full tool-calling LLM.

**Alternatives considered**:
- LLM for all messages — 5–10× higher per-message cost; latency unacceptable for simple FAQ queries.
- Rule-based routing only — brittle; cannot generalize to novel phrasing.

**Why this**:
The vast majority of widget queries are FAQ-style (`rag_search`) or lead-capture. Routing these through a ~2 ms ONNX classifier instead of a 500 ms LLM call reduces per-message cost by an order of magnitude. The classifier eval gate (macro-F1 ≥ threshold) in CI prevents model drift from silently degrading routing quality.

---

## ADR-008: Tenant Manager read prohibition (structural, not procedural)

**Decision**: The Tenant Manager's DB session never sets `app.tenant_id`. RLS returns zero rows on any content table SELECT — not an error, just empty.

**Alternatives considered**:
- Application code checks `if role == tenant_manager: raise Forbidden` before any SELECT — procedural; a missing check is a silent breach.
- Separate DB user with no SELECT privileges — operationally complex; requires per-role DB credential management.

**Why this**:
Structural enforcement cannot be forgotten. The Tenant Manager erasure path uses `DELETE WHERE tenant_id = ?` with a literal UUID — it deletes blindly without reading content. An accidental SELECT returns empty, so even a bug that adds a SELECT to the erasure path reveals nothing.

---

## ADR-009: Bucket-per-tenant in MinIO

**Decision**: Each tenant gets one MinIO bucket named `tenant-{uuid}`.

**Alternatives considered**:
- Prefix-per-tenant in a shared bucket — simpler to set up but erasure requires a full prefix scan; cannot apply per-tenant IAM policies.

**Why this**:
Deleting a tenant's MinIO data is `remove_bucket(tenant-{uuid})` — one call, no scan, no risk of leaking another tenant's objects. Per-tenant buckets also allow future per-tenant access policies without code changes.

---

## ADR-011: Per-command RLS policies to separate SELECT from DELETE

**Decision**: Tenant-scoped tables carry separate RLS policies for SELECT (`tenant_isolation`) and DELETE (`erase_isolation`). The `users` table additionally has an `email_login_lookup` policy for the login flow.

**Alternatives considered**:
- Single `USING` policy (FOR ALL) — simpler, but any operation that needs to bypass the policy for DELETE would also bypass it for SELECT. This collapses the structural read prohibition.
- Set `app.tenant_id` during erasure — would allow DELETEs (USING matches) but also SELECTs (same match), violating the TM read prohibition.

**Why this**:
With a single policy, the Tenant Manager's erasure path has two bad options: (a) empty context → DELETE matches no rows (erasure is silently broken); (b) set `app.tenant_id` → DELETE works but so does SELECT (read prohibition violated). Per-command policies resolve this: the `erase_isolation` FOR DELETE policy checks `app.erase_target` (a separate GUC set only during erasure), while the `tenant_isolation` FOR SELECT policy still requires `app.tenant_id`. The TM's session never sets `app.tenant_id`, so reads are still structurally blocked.

The `email_login_lookup` policy solves an analogous problem for the login flow: we cannot set `app.tenant_id` before we know which user is logging in.

---

## ADR-010: Secrets in Vault, never in `.env` or code

**Decision**: All secrets (JWT keys, DB password, MinIO credentials, API keys, service-to-service tokens) live in Vault under `secret/concierge/*`. Services read them at runtime via `hvac`.

**Alternatives considered**:
- `.env` files committed to the repo — obvious security failure.
- `.env` files mounted as Docker secrets — better, but still plaintext on disk; no rotation, no audit log.

**Why this**:
Vault provides rotation, audit logging, and a single source of truth for all secrets. The `get-or-generate` pattern in `seed.sh` means signing keys are stable across restarts (not regenerated on each `docker compose up`). The backend's `_load_database_url()` function checks `DATABASE_URL` env var first — this allows CI to skip Vault without a running server.
