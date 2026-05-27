<!--
Sync Impact Report
Version change: (template) → 1.0.0
Modified principles: N/A (initial ratification — all principles new)
Added sections: Core Principles (I–V), Technology Constraints, Development Workflow, Governance
Removed sections: N/A
Templates:
  ✅ .specify/memory/constitution.md — initial fill, all placeholders resolved
  ✅ .specify/templates/plan-template.md — Constitution Check gates populated
  ✅ .specify/templates/spec-template.md — no changes required (generic structure fits)
  ✅ .specify/templates/tasks-template.md — no changes required (generic structure fits)
Deferred TODOs: none
-->

# Concierge Constitution

## Core Principles

### I. Tenant Isolation (NON-NEGOTIABLE)

Every piece of data belonging to a tenant MUST be isolated from all other tenants at all times.
Isolation is enforced at three independent layers simultaneously — all three MUST be present:

- **Database (RLS)**: Every table MUST have a `tenant_id` column and a Postgres RLS policy.
  The `app.tenant_id` session variable MUST be set per request via a FastAPI dependency and
  MUST be reset in a `finally` block. Pooled connections persist this variable — a missing
  reset is a guaranteed cross-tenant data leak.
- **Repository layer**: Every query MUST explicitly `.filter(tenant_id == current_tenant_id)`.
  RLS is the safety net underneath; the repository filter is the first line of defense.
- **pgvector**: All vector similarity searches MUST include `filter={"tenant_id": current_tenant_id}`.
  Omitting this filter is the most common multi-tenant RAG data leak path.

The Tenant Manager role MUST use write/delete-only paths. Its session MUST NOT set `app.tenant_id`
to any tenant's ID — it can destroy tenant data but MUST never be able to read it.

### II. Spec-First Development

Every major component MUST have a `SPEC.md` under `specs/` written and team-agreed before any
implementation code is written. The spec is the contract. Implementation MUST conform to the spec.

Tool contracts (`rag_search`, `capture_lead`, `escalate`) MUST specify: input schema, output schema,
side effects, rate limits, and tenant-scoping rules before any implementation begins.

Changing a spec after implementation starts requires explicit team sign-off. "No vibe coding" —
every teammate MUST be able to explain any part of the system on demo day, not just their slice.

### III. Lean Containers — No Torch

Docker images MUST NOT include PyTorch, transformers, or any GPU-dependent library.

- LLM and embedding calls are hosted API calls (Anthropic API, compatible embeddings API).
- The DL classifier MUST be exported to ONNX and served via `onnxruntime` only.
- The classical classifier MUST be served via `scikit-learn + joblib` only.
- All application images MUST stay under ~500 MB.
- Training happens offline (Jupyter notebooks / Colab) and produces exported artifacts only.
  Training dependencies MUST NOT appear in any service `pyproject.toml`.

### IV. Evaluation Gates Are the Grade (NON-NEGOTIABLE)

All six CI gates defined in `eval_thresholds.yaml` MUST pass on every push. Thresholds MUST be
committed before implementation begins (placeholders on day one, tightened as real results land).
The `security.red_team_pass_rate` is a constitutional floor of `1.0` and MUST never be lowered.

Every architectural decision in `DESIGN.md` and `DECISIONS.md` MUST be backed by a measured number
from the golden sets or eval suites. "hit@5 went from 0.61 to 0.79 when I switched chunking" is
acceptable. "Semantic chunking is better" is not.

Model artifacts MUST be SHA-256 pinned in `modelserver/artifacts/model_card.md`. The model server
MUST refuse to boot if the loaded artifact hash does not match the card.

### V. Secrets via Vault — Never in Code or Request Bodies

No secret (API key, DB password, JWT signing key, service-to-service token) MUST ever appear in
code, in committed `.env` files, or in request bodies.

- All secrets are written to Vault by `infra/vault/seed.sh` at stack boot.
- Services MUST fetch credentials from Vault at runtime via `hvac`.
- The widget `tenant_id` MUST come from the verified JWT only — never from the request body.
  Accepting `tenant_id` in a request body is a one-line cross-tenant breach.
- CORS and CSP are defense-in-depth layers around the token. The signed per-widget JWT is the
  real authentication boundary. A `curl` call bypasses CORS entirely.

## Technology Constraints

**Stack**: Python ≥3.12 (backend, modelserver, guardrails, admin), React + TypeScript (widget),
Postgres with pgvector, Redis 7, MinIO, HashiCorp Vault 1.15, NeMo Guardrails sidecar (Jana),
Langfuse for tracing.

**Agent loop**: Bounded tool-calling loop with hard caps: max 5 tool calls and 2000 tokens per turn.
These caps are simultaneously cost controls and security controls — a malicious visitor MUST NOT
be able to run up LLM costs by forcing long tool chains.

**Prompts**: System prompts and persona templates MUST live in `prompts/` and be version-controlled.
Tenant persona is injected at runtime from config. Platform security instructions (injection defense,
jailbreak refusal, cross-tenant refusal) are locked at the platform layer and are NOT tenant-configurable.

**PII**: Emails, phone numbers, credit cards, and API keys MUST be redacted before any data reaches
logs, traces, or Redis session storage. A CI gate MUST verify that a fake API key sent in chat does
not appear unredacted in any of those stores.

**Guardrails**: Platform rails (injection detection, jailbreak detection, cross-tenant refusal, PII
redaction) run as a sidecar and MUST NOT be bypassable via tenant configuration. Tenant rails
(topic restrictions, persona, enabled tools) are configurable but MUST NOT weaken platform rails.

## Development Workflow

**Ownership**: Every file carries an `# Owner:` comment. Owners are responsible for their slice
end-to-end (API, service, repository, infra). `structure.md` is the authoritative ownership map.
Changes to a file outside one's slice require the owner's explicit consent.

**Branches**: Feature branches named `###-short-description`. PRs use `.github/PULL_REQUEST_TEMPLATE.md`.
CI MUST be green before merge.

**Stubs**: Placeholder files carry `# PLACEHOLDER` and return `"stub": True` in health responses.
A stub signals the file is not yet implemented. Stubs MUST be replaced — MUST NOT be built upon.

**Erasure path**: `scripts/delete_tenant.py` MUST purge all stores when triggered: Postgres tables,
pgvector embeddings, MinIO blobs, Redis sessions, and trigger an audit log entry. Missing any store
is a GDPR compliance failure.

**Cost attribution**: Every LLM and embedding call MUST be tagged with `tenant_id` and cost-logged.
Per-tenant rate limiting MUST be enforced so one noisy tenant cannot starve others.

## Governance

This constitution supersedes all other development practices within this repository. Any deviation
requires explicit team agreement and a constitution amendment before the deviation is merged.

**Amendments**: Propose via PR to `.specify/memory/constitution.md`. Requires sign-off from all
owners (Ali, Mohammad, Jana, Charbel). Update `LAST_AMENDED_DATE` and bump version:
- MAJOR: principle removal, redefinition, or reduction of the security floor.
- MINOR: new principle or material expansion of existing guidance.
- PATCH: clarification, wording fix, or non-semantic refinement.

**Compliance reviews**: Every PR review MUST verify compliance with Principle I (isolation) and
Principle V (secrets). The isolation-auditor subagent (if present in `.claude/`) SHOULD be run to
grep for queries missing tenant filters before merging any data-access changes.

**Security floor**: The `red_team_pass_rate: 1.0` threshold in `eval_thresholds.yaml` is a
constitutional floor. Lowering it below `1.0` is a MAJOR amendment and requires written justification.

**Version**: 1.0.0 | **Ratified**: 2026-05-26 | **Last Amended**: 2026-05-26
