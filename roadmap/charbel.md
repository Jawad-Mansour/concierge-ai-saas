<!-- Owner: Charbel -->

# Roadmap — Charbel

**Slice:** Widget auth, admin UX, CI/CD, Docker.

Append-only. End-of-day notes go at the bottom under "Daily log."
Phases tick from top to bottom; finished items get `[x]` with the
PR link or commit SHA in the trailing parenthesis.

---

## Phase 0 — Repo scaffolding & process

- [x] Decide repo structure, ownership map (`structure.md`)
- [x] PR template, CODEOWNERS, issue templates (`.github/`)
- [x] Branch ruleset on `main` (require PR, 1 approval, block force-push, block delete)
- [x] First scaffold PR — 148 empty files with ownership headers
- [x] README.md + .gitignore
- [x] `.gitattributes` + `.vscode/settings.json` for cross-platform LF (PR A)

## Phase 1 — Docker stack

- [x] `docker-compose.yml` at root — 13 services, healthchecks, depends_on gating
- [x] Per-service Dockerfiles (backend, modelserver, guardrails, admin, widget, infra/postgres)
- [x] `pyproject.toml` per Python service (backend, modelserver, guardrails, admin)
- [x] Placeholder `main.py` per service with `"stub": True` in /health
- [x] `infra/vault/seed.sh` — KV v2 seeds under `secret/concierge/*`
- [x] `.env.example` with port mappings and placeholder secrets
- [x] Demo nginx hosts (`demo/host` on 8080, `demo/blocked-host` on 8090)
- [x] Validated end-to-end: 12 services healthy, vault-init exits 0
- [x] modelserver image under 500MB cap, no torch verified

## Phase 2 — Docker follow-ups

- [x] Fix `seed.sh` — get-or-create idempotency for `auth_jwt.signing_key`,
      `widget_jwt.signing_key`, `service_auth.token` so restart doesn't
      rotate keys mid-session
- [x] Verify idempotency: `vault kv get` before and after `restart vault-init`
      shows byte-identical signing keys
- [ ] Confirm `POSTGRES_PORT` override works for teammates with local Postgres

## Phase 2.1 — Unblock Mohammad (PR #14)

- [x] Fix backend/Dockerfile deps stage to read from pyproject.toml
      instead of hardcoded package names
- [x] Add pytest job to ci.yml (continue-on-error until real tests land)
- [x] Add widget_configs migration (001_widget_configs.sql) with
      widget_id UUID UNIQUE — required by POST /auth/widget-token
- [x] Replaced ghcr.io/astral-sh/uv copy with pip install uv==0.5.4
      in all Python Dockerfiles — removes ghcr.io network dependency.
      Adopted uv sync --frozen with lockfiles (Week 7 pattern).
- [x] Wrote real integration smoke tests (test_ci_smoke.py) —
      health endpoints for all 4 Python services + widget nginx
      healthz + blocked-host. Marked with pytestmark integration.
- [x] Wrote widget auth contract stubs (test_widget_auth.py) —
      6 skip-marked tests defining Phase 5 contract.
- [x] Removed continue-on-error from CI test job — skip stubs
      are SKIPPED not FAILED so CI stays green.
- [x] Added integration test step to smoke-test.yml — runs
      test_ci_smoke.py against the live stack.
- [x] Registered integration pytest mark in pyproject.toml to silence
      PytestUnknownMarkWarning
- [x] Converted 001_widget_configs.sql → proper Alembic migration
      002_widget_configs_columns.py (ALTER TABLE, not CREATE TABLE —
      Mohammad already created the stub in 001_baseline)
- [x] Fixed backend/Dockerfile — added COPY alembic.ini and
      COPY alembic/ to runtime stage so alembic upgrade head
      works inside the container
- [x] Fixed docker-compose.yml — added explicit
      VAULT_ADDR: http://vault:8200 override to backend,
      modelserver, guardrails, admin services. Root cause:
      .env has localhost:8200 for host CLI access which was
      bleeding into containers via the vault-env anchor.
- [x] Rebuilt postgres image after Mohammad filled init.sql —
      widget_configs stub now created correctly on fresh volume.
      Verified: \d widget_configs shows id, tenant_id, created_at
      with RLS policies active.
- [x] Full stack validated: 12/12 services healthy after all fixes.

## Phase 2.2 — Unblock Jana: feat/classifier-implementation

- [x] Checked out Jana's branch and got her OK to push fixes
- [x] Rebased onto main (already up to date)
- [x] Ran ruff --fix from backend venv against modelserver/
      (ruff not in modelserver dev deps, had to use backend venv)
- [x] Auto-fixed: UP041 (asyncio.TimeoutError → TimeoutError),
      SIM300 (yoda condition), I001 (import ordering),
      F401 (unused import)
- [x] Manual noqa suppressions added for E501 (intentionally long
      lines in model_loader.py, test_hash_mismatch_boot.py,
      evaluate_models.py, train_dl.ipynb) and E402 (structural
      module-level import in evaluate_models.py)
- [x] ruff check ../modelserver → All checks passed
- [x] Diagnosed modelserver unhealthy: pkg_resources missing —
      opentelemetry-instrumentation-fastapi==0.48b0 uses
      pkg_resources which was removed in Python 3.12
- [x] Fixed: bumped opentelemetry-sdk/instrumentation/exporter
      to >=1.29.0 / >=0.50b0, added setuptools>=69.0,
      wrapped FastAPIInstrumentor import in try/except
- [x] Regenerated modelserver/uv.lock after dep changes
- [x] Diagnosed modelserver still unhealthy after opentelemetry fix:
      artifact_missing — classifier.joblib not in repo (gitignored,
      Jana hasn't trained final model yet). model_card.md confirms
      placeholder SHA. This is expected on an incomplete branch.
- [x] Decision: do not add DEV_MODE stub — modelserver is
      intentionally incomplete. Smoke test will pass once Jana
      commits the trained artifact and updates model_card.md SHA.
- [x] Pushed lint + opentelemetry fixes to feat/classifier-implementation
- [x] Wrote model card in correct YAML frontmatter format that the
      loader parser expects (not markdown prose)
- [x] Copied real classifier.onnx (238KB) from training/candidates/ml_v1/
      to artifacts/ — placeholder 56-byte text file replaced
- [x] Updated model_card.md SHA to match new artifact:
      56ba47ae3de32da8...
- [x] Fixed modelserver/Dockerfile — added locales + locale-gen
      en_US.UTF-8 to both deps and runtime stages for ONNX
      StringNormalizer (requires en_US.UTF-8 C locale)
- [x] Fixed VAULT_KV_PATH in modelserver/app/deps.py — was pointing
      to modelserver/service_credential (never seeded), now points
      to concierge/service_auth (what seed.sh actually writes)
- [x] Updated test_ci_smoke.py test_modelserver_health — Jana's real
      health endpoint returns model_hash not service field
- [x] Validated: 7/7 integration tests pass with full stack running

## Phase 2.3 — Fix CI on fix-tests branch (Jana's guardrails)

- [x] evals/security/pyproject.toml: added PyJWT>=2.8
      (fixes: No module named 'jwt' in security gates CI)
- [x] guardrails/pyproject.toml: added setuptools>=69.0
      (fixes: pkg_resources availability for opentelemetry)
- [x] guardrails/app/main.py: wrapped FastAPIInstrumentor import
      in try/except, guarded instrument_app with _OTEL_AVAILABLE
      (fixes: ModuleNotFoundError: No module named 'opentelemetry')
- [x] guardrails/app/deps.py: VAULT_KV_PATH fixed from
      guardrails/service_credential to concierge/service_auth
      (same root cause as modelserver fix — path never seeded)
- [x] guardrails container: healthy on /healthz after fixes
- [x] 90 passed, 13 skipped, 0 failed locally

## What's left for Jana on this branch (updated)
- test_provisioning.py and test_rls.py errors are Mohammad's tests
  connecting to postgres hostname — needs conftest fix or integration
  marker. Not blocking Jana's branch merge.
- Mohammad's test_tenant_isolation.py also fails same way.
- Smoke test should now pass on CI since modelserver is healthy.

## Phase 3 — CI pipeline skeleton

Goal: pipeline green before there's anything real to gate. Owners
plug their gates in as their work lands.

- [x] `.github/workflows/ci.yml` — checkout, set up uv, lint (ruff), type-check (mypy or pyright), build all images
- [x] `.github/workflows/smoke-test.yml` — `docker compose up -d`, wait for health, `docker compose down -v`
- [x] `.github/workflows/evals.yml` — runs the four eval suites; reads thresholds from `eval_thresholds.yaml`
- [x] `eval_thresholds.yaml` — placeholder numbers so CI has something to gate from day 1
- [ ] Verify CI runs on PR open and on push to feature branches
- [ ] Confirm branch ruleset requires `ci`, `smoke-test`, `evals`, `security-gates` to pass before merge

## Phase 4 — Widget Frontend (DONE)

- [x] Vite + React + TypeScript scaffolding (package.json, vite.config.ts, tsconfig.json)
- [x] Floating bubble widget (fixed bottom-right, click to open/close)
- [x] Chat panel: header with status, message area, input box
- [x] Everforest Hard Dark theme throughout
- [x] Message bubbles: user (green, right), assistant (dark, left), error (red)
- [x] Typing indicator (animated dots)
- [x] Auto-scroll to latest message
- [x] Enter to send, Shift+Enter for newline
- [x] Token exchange on mount via auth.ts (POST /widget/token)
- [x] Chat via api.ts (POST /chat with Bearer token)
- [x] loader.js: injects iframe into host page
- [x] Backend widget_js.py updated to serve real loader
- [x] Bundle: 47.6 KB gzipped (under 100 KB target)
- [x] Demo validated: widget loads on localhost:8080, blocked on localhost:8090

## Security fixes (chat.py + auth_service.py)

- [x] get_chat_user dependency: accepts both widget_jwt and auth_jwt tokens
- [x] auth_service.py: verify_sub=False for widget tokens (sub is null by design)
- [x] chat.py: tenant_id from JWT claims not request body (brief compliance)

## Phase 5 — Widget auth (the hard part)

Goal: a `curl` with a copied `widget_id` from a server with no browser
gets rejected. CORS is defense-in-depth, not the boundary.

- [x] `specs/widget_auth_SPEC.md` — write the contract BEFORE the code
- [x] `widget_auth_service.py` — exchanges `widget_id` + origin for a signed JWT
      (15-min TTL, signed with `secret/concierge/widget_jwt`)
- [x] `api/widget.py` — POST `/widget/token` endpoint
- [x] `widget_repo.py` — pre-auth lookup with RLS bypass (app.widget_lookup)
- [x] Migration 003 — widget_id_lookup RLS policy on widget_configs
- [x] `tests/test_widget_auth.py` — origin spoof, expired token, unknown widget
- [x] 4/4 widget auth integration tests passing
- [ ] `auth.ts` in widget — loader exchanges widget_id for token, attaches to every request
- [ ] Server-side origin validation in `tenant_context` middleware:
      reject if origin doesn't match tenant's `allowed_origins`
- [x] CSP `frame-ancestors` header set per tenant
- [x] CORS allowlist driven by DB (NOT env) — CORSMiddleware added,
      real origin enforcement is server-side in widget_auth_service
- [x] GET /widget.js endpoint — stub loader served from backend
- [x] demo/host/index.html updated with real script tag
- [x] demo/blocked-host/blocked.html updated with script tag
- [x] Browser validated: localhost:8080 shows [Concierge] widget.js loaded
- [x] Browser validated: localhost:8090 shows CSP violation in DevTools:
      "Loading the script violates Content Security Policy directive:
      script-src 'none'"

## Phase 6 — Admin UX (Streamlit)

## Backend APIs (done)
- [x] GET /admin/widget-config — returns tenant widget config (404 if none)
- [x] PUT /admin/widget-config — create or update widget config
- [x] GET /admin/widget-config/embed-snippet — returns embed script tag
- [x] Role-gated: tenant_admin only, uses get_tenant_db RLS dependency

- [x] `streamlit_app.py` — login form, session persistence via URL token,
      sidebar nav, logout
- [x] `pages/widget_config.py` — current config display, edit form with
      live color picker, embed snippet, widget preview iframe,
      test origin validation
- [x] `pages/tenant_settings.py` — JWT decode, role/tenant_id/expiry,
      full UUID display
- [ ] `pages/guardrails_config.py` — tenant rails (topics, persona, refusal tone) — coordinate with Jana
- [ ] `pages/leads_dashboard.py` — coordinate with Ali
- [x] Live update without restart (st.rerun() after save)
- [x] Auth: real login form with JWT, session persists across refresh

## Phase 7 — Friday demo polish

- [ ] Update `deliverables/RUNBOOK.md` §6 with the demo script
- [ ] Rehearse the 12-minute demo end-to-end
- [ ] Allowed-origin proof on `localhost:8080`
- [ ] Blocked-origin proof on `localhost:8090` (frame-ancestors CSP violation in DevTools)
- [ ] Raw curl from `evil.com` origin returns 403
- [ ] Tag `v0.1.0-week8` after final merge

---

## Daily log

### Mon 2026-05-25

- Repo transferred from Jawad to my account. Set up branch ruleset on `main`:
  require PR, 1 approval (set to 0 temporarily until teammates invited),
  required status checks (placeholder), block force-push, block delete.
- Filled PR template and CODEOWNERS based on `structure.md` ownership map.
- Scaffolded 148 empty files with ownership headers via Claude Code agent.
  Renamed `prompts/*.txt` → `prompts/*.py` (storing prompts as Python
  modules) and updated `structure.md` to match.
- Shipped PR A: `.gitattributes` + `.vscode/settings.json`. Normalizes
  LF for all text files; .bat/.cmd stay CRLF. Protects Windows teammates
  from `bad interpreter: /bin/sh^M` errors.
- Shipped PR B: full Docker stack — 13 services, all healthy after agent
  caught and fixed 4 cross-environment issues (Alpine localhost→IPv6,
  python:slim has no wget, Langfuse Next.js binding, nemoguardrails
  needs g++). Image sizes verified: modelserver 410MB (under 500MB cap),
  no torch.
- Known issue carried to tomorrow: seed.sh isn't idempotent on signing
  keys. Filed under Phase 2.

### Tue 2026-05-26

- CI skeleton landed: ci.yml (lint + build jobs), smoke-test.yml
  (12-service health poll, 5-min timeout), evals.yml (threshold
  reader, placeholder gates), security-gates.yml (Jana's stub).
- eval_thresholds.yaml seeded: all gates at 0.0 except security
  at 1.0 (injection/cross-tenant must always pass 100%).
- ruff added to backend/pyproject.toml dev deps with [tool.ruff]
  excludes for widget/src, demo/, node_modules.
- Known: branch ruleset status check names need human verification
  on GitHub after this PR merges.

### Wed 2026-05-27

- Unblocked Mohammad's PR #14: fixed backend/Dockerfile to install
  deps from pyproject.toml dynamically (hardcoded list broke when
  owners added real deps), added pytest job to ci.yml, added
  widget_configs migration with RLS and widget_id UNIQUE constraint.
- Wrote real integration smoke tests and widget auth contract stubs.
  Removed continue-on-error from CI. Integration tests now run in
  smoke-test workflow against the live stack.
- Registered integration mark in pyproject.toml.
- Phase 2 done: seed.sh get-or-create idempotency for auth_jwt,
  widget_jwt, service_auth signing keys. Verified: vault-init
  restart produces byte-identical keys. ANTHROPIC_API_KEY comment
  clarified in .env.example — real key from Charbel, forwarded
  to Vault by vault-init, never read from .env directly by services.

### Thu 2026-05-28

- Fixed widget_configs migration — deleted conflicting raw SQL,
  replaced with Alembic 002 that ALTER TABLEs the stub Mohammad
  created.
- Fixed VAULT_ADDR bleeding from .env into containers (localhost
  vs vault:8200). Added alembic.ini + alembic/ to backend Dockerfile.
  Rebuilt postgres image — widget_configs stub confirmed in fresh DB.
  Full stack 12/12 healthy.
- Worked on Jana's feat/classifier-implementation branch with her OK.
  Fixed all lint errors (ruff noqa suppressions + auto-fixes). Fixed
  opentelemetry pkg_resources crash (Python 3.12 incompatibility) by
  bumping to >=1.29.0. Modelserver still unhealthy — expected, artifact
  missing because Jana hasn't trained final model yet. Pushed fixes,
  documented what Jana needs to do to finish the branch.
- Continued Jana's classifier branch: fixed model card format, locale
  in Dockerfile, Vault path mismatch in deps.py, smoke test assertion.
  7/7 integration tests passing with real artifact loaded. Branch ready
  to push — Mohammad's DB tests still failing but that's his conftest
  to fix.
- Widget auth backend complete: POST /widget/token, origin validation,
  JWT signing via Mohammad's auth_service.issue_widget_token(). RLS bypass
  migration 003 for pre-auth widget_id lookup. 4/4 tests pass.
- Admin backend: 3 widget config endpoints, all passing. GET/PUT/embed-snippet.
  RLS via get_tenant_db, role check, UUID cast fix for psycopg2.
- CSP + CORS wired. widget.js stub endpoint live. Demo pages updated.
  Browser proof: allowed host loads widget.js, blocked host shows CSP
  violation in DevTools console. Friday demo ready for this piece.

### Fri 2026-05-29

- Admin UI complete: login, widget config CRUD, tenant settings,
  session persistence on refresh, Everforest Hard Dark theme,
  widget preview iframe. All pages working.
- Widget frontend complete. React widget with Everforest theme,
  floating bubble, chat UI, token exchange. Full flow working on
  localhost:8080. Blocked on localhost:8090 CSP violation confirmed.
  Security fixes: get_chat_user dual-key auth, verify_sub fix,
  tenant_id from JWT.
- Fixed Jana's fix-tests branch: PyJWT in evals/security,
  setuptools in guardrails, opentelemetry try/except in main.py,
  Vault path fix in deps.py. Guardrails healthy. 90/0 tests.
