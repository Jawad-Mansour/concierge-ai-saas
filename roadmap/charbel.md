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

## Phase 2.4 — Fix CI on fix-tests (continued) + ship to main

- [x] backend/pyproject.toml: moved httpx from [dependency-groups] dev
      to [project] dependencies — classifier_client imports it at module
      level, so it's runtime, not test-only.
- [x] backend/uv.lock: regenerated against corrected pyproject.
- [x] backend/Dockerfile: untouched — `--no-dev` flag is correct now.
- [x] .github/workflows/security-gates.yml: replaced ad-hoc
      `pip install psycopg2-binary` with `cd backend && uv sync --frozen`
      so all backend runtime deps land for the redaction test. Added
      job-level + step-level GUARDRAILS_SERVICE_CREDENTIAL=test-token.
- [x] .github/workflows/smoke-test.yml: corrected guardrails health URL
      to /healthz (matches Jana's contract).
- [x] docker-compose.yml: added GUARDRAILS_SERVICE_CREDENTIAL pass-through
      to guardrails service with :- default — local dev unchanged, CI
      gets the override.
- [x] backend/tests/test_ci_smoke.py: test_guardrails_health updated for
      /healthz + new response shape (rails_version, no service field).
- [x] backend/tests/test_redaction.py: fixed _generate_probe so PHONE,
      SSN, CC probes match Presidio recognizers (digit-only segments,
      Luhn-valid PAN).
- [x] All 7 CI checks green on fix-tests.
- [x] PR opened to merge fix-tests → main.

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

## Phase 6.1 — Guardrails config: backend + chat-path wiring

- [x] Bootstrap gap: scripts/seed_platform.py creates the platform
      tenant_manager via direct psycopg2 INSERT. Mohammad's
      seed_tenants.py assumed this user existed but nothing created
      it — fresh stacks 401'd on first provisioning call.
- [x] Alembic infrastructure fix: backend/Dockerfile widens build
      context to repo root so infra/postgres/migrations is COPYed
      into the image. backend/entrypoint.sh bootstraps alembic_version
      to 003 (init.sql baseline), then runs `alembic upgrade head`
      before exec uvicorn. Workarounds documented in entrypoint.sh
      comments: psycopg2 single-connection stamp (alembic 1.18
      two-connection deadlock), version files copied to /tmp to
      avoid alembic's overly-broad .py regex picking up env.py,
      script_location patched to absolute paths.
- [x] 004_guardrails_configs.py migration: tenant_id-keyed table
      with RLS (tenant_isolation, tenant_write, tenant_update,
      erase_isolation; FORCE row level security). Columns mirror
      sidecar's TenantConfig schema.
- [x] backend/app/repositories/guardrails_repo.py: get_for_tenant
      with inline app.tenant_id set+reset (widget_repo pattern).
- [x] backend/app/api/admin.py: GET/PUT /admin/guardrails-config,
      tenant_admin-gated, Pydantic model mirrors sidecar contract.
- [x] backend/app/api/chat.py: tenant_config=None placeholders
      replaced with guardrails_repo.get_for_tenant(db, tenant_id).
      Tenant rails now reach the sidecar on every chat turn.
- [x] End-to-end validated: PUT escalation_trigger keyword "manager"
      → chat "I want to speak to a manager" → response
      {"decision": "escalate", "message": "I will flag this for
      human follow-up."}. Full chain green.

Mohammad shipped `widget_configs` and `guardrails_configs` in `init.sql` as
stubs (`id`, `tenant_id`, `created_at` only) with a comment telling Charbel
to add the rest. Phase 6.1 closes that gap end-to-end: schema, repo,
backend endpoints, admin page, infrastructure fixes that surfaced along
the way.

### Infrastructure fixes (whole-team unblock)

- [x] `scripts/seed_platform.py` — bootstrap the platform `tenant_manager`
      (`manager@concierge.internal`) via direct psycopg2 INSERT.
      `seed_tenants.py` assumes this user exists but nothing was creating
      it — fresh stacks 401'd on the first provisioning call. Idempotent.
- [x] `backend/Dockerfile` — widened build context to repo root so
      `infra/postgres/migrations/` is COPYed into the image. Compose updated
      with `build: {context: ., dockerfile: backend/Dockerfile}`.
- [x] `backend/entrypoint.sh` — new file. Bootstraps `alembic_version`
      to 003 (the init.sql baseline) via psycopg2 single-connection stamp
      (alembic 1.18 two-connection stamp deadlocks under our setup).
      Copies migrations to `/tmp/alembic_versions/` (alembic's `.*\.py`
      regex was picking up `env.py` and crashing). Patches `script_location`
      to absolute paths. Runs `alembic upgrade head` before exec'ing
      uvicorn. Alembic was never actually running before this — init.sql
      was the only schema source. Now migrations 004 and 005 run on every
      backend boot.
### Migrations (Charbel's tables)

- [x] `infra/postgres/migrations/004_guardrails_configs.py` — new table:
      `tenant_id UUID` PK with FK to tenants ON DELETE CASCADE,
      `allowed_topics TEXT[]`, `refusal_persona JSONB`,
      `escalation_triggers JSONB`, `created_at` + `updated_at`.
      RLS policies: `tenant_isolation` (SELECT), `tenant_write` (INSERT),
      `tenant_update` (UPDATE), `erase_isolation` (DELETE).
      `FORCE ROW LEVEL SECURITY` so the table owner doesn't bypass.
- [x] `infra/postgres/migrations/005_widget_config_columns.py` —
      adds the columns Mohammad stubbed: `widget_id UUID UNIQUE` (the
      public identifier in the embed script), `allowed_origins TEXT[]`,
      `theme JSONB`, `greeting TEXT`, `enabled_tools TEXT[]`, `updated_at`.
      All with sensible defaults so existing rows survive the migration.
      Also adds the two missing RLS policies `tenant_write` and
      `tenant_update` that 001/002/003 never installed — admin PUT
      upserts would have failed under FORCE RLS even on installs where
      002/003 ran. Idempotent `CREATE POLICY` via DO/EXCEPTION block.
### Backend (FastAPI)

- [x] `backend/app/repositories/guardrails_repo.py` — `get_for_tenant`
      reads the row using the same inline `app.tenant_id` set/reset
      pattern as `widget_repo`. Returns `None` when no config exists.
- [x] `backend/app/api/admin.py` — three new endpoints, all
      `tenant_admin`-gated via `get_tenant_db`:
        - `GET  /admin/guardrails-config` — returns the tenant's config.
        - `PUT  /admin/guardrails-config` — upsert, Pydantic body mirrors
          the sidecar's `TenantConfig` schema exactly (extra="forbid"
          on the sidecar side so we can't drift).
        - `POST /admin/guardrails-config/test` — proxy. Loads the
          caller's stored config via `guardrails_repo`, forwards to the
          sidecar through the existing `app.state.guardrail_client`
          (reuses `screen_input`'s call shape, no new HTTP client, no
          re-fetch of the service credential). Returns the sidecar's
          raw `GuardrailDecision` JSON. 503 if `guardrail_client` is
          `None`.
- [x] `backend/app/api/chat.py` — replaced the `tenant_config=None`
      placeholders on lines 157 and 184 with
      `guardrails_repo.get_for_tenant(db, tenant_id) or {}`. Added
      `db: Session = Depends(get_db)` to the signature. Tenant rails
      now reach the sidecar on every chat turn — they were dead before.
### Admin UI (Streamlit)

- [x] `admin/pages/guardrails_config.py` — replaces the
      `_coming_soon_guardrails` stub. Three sections:
        - **Current config** — read-only display of allowed_topics,
          refusal_persona (voice + template), escalation triggers, with
          sensible captions for empty/null fields.
        - **Edit config** — allowed_topics textarea (one per line),
          voice + template inputs with live `.format(topic=..., reason=...)`
          preview that catches `KeyError`/`IndexError`/`ValueError` and
          shows an inline error on malformed templates. Dynamic
          escalation_triggers list backed by `st.session_state["gc_triggers"]`
          with selectbox kind / text_input value / × remove button per
          row, plus an "+ Add trigger" button. Save assembles the
          payload with `None` for empty sections (matches the sidecar's
          `Optional` schema fields).
        - **Test this config** — text input + Run check button POSTs
          to `/admin/guardrails-config/test`. Renders the response with
          colour: green container for `decision: pass`, red container
          for `decision: block` with `rule_name` highlighted.
- [x] Persistent banner feedback on Save — both `widget_config.py` and
      `guardrails_config.py` use a `session_state` flash pattern
      (`wc_flash` / `gc_flash`) that renders the success/error message
      at the TOP of the next render. Replaces the silent
      `st.success → st.rerun` pattern that wiped feedback before the
      user saw it. Banner persists until the user interacts again.
- [x] `admin/streamlit_app.py` — guardrails entry moved from "Coming
      soon" to "Configuration" with `:material/shield:` icon. Removed
      the misleading "Toggle theme: ☰ → Settings" caption (current
      Streamlit version has no Settings entry in the hamburger menu).
### End-to-end verified

PUT `escalation_trigger` keyword `"manager"` via admin UI →
chat `"I want to speak to a manager"` from widget visitor →
backend loads tenant config from DB → forwards to sidecar →
sidecar matches the trigger → returns `decision=block, action=escalate` →
chat handler short-circuits with `{"decision": "escalate", "message":
"I will flag this for human follow-up."}`. The full chain fires before
the LLM stub layer is even reached.

Test panel produces identical sidecar responses to the live chat path.

Pre-demo dress rehearsal surfaced four real bugs across the stack.
Three were on Charbel's slice and got fixed; one was on Ali's slice
and got patched cooperatively to unblock the demo.

### Bugs found and fixed

- [x] `demo/host/public/index.html` — hardcoded `data-widget-id`
      mismatched Acme's real widget_id after fresh seed. Swapped
      manually; demo-host required `docker compose build --no-cache`
      because the cached layer kept the old value.
- [x] `backend/app/api/widget_js.py` — the `/widget.js` loader read
      `data-widget-id` from the script tag correctly but didn't pass
      it into the iframe. The iframe src was hardcoded to
      `http://localhost:8081/`. Result: the widget container loaded
      its own bundle (with its own hardcoded widget_id in App.tsx)
      and ignored the embedding page entirely. Fixed: loader now
      appends `?widget_id=<encoded>` to the iframe URL.
- [x] `widget/src/App.tsx` — React widget had a hardcoded constant
      `const WIDGET_ID = '042016b1-...'`. Replaced with
      `new URLSearchParams(window.location.search).get('widget_id')`.
      The widget now mounts with whatever widget_id the parent page
      passes via the iframe URL. `widget/src/auth.ts` was already
      parameterized correctly — no changes needed there.
- [x] `docker-compose.yml` — backend container had no
      `ANTHROPIC_API_KEY` in its environment, despite the host having
      it in `.env`. Mohammad's pattern routes secrets via Vault, but
      `AnthropicAgentPlanner` uses `os.getenv()` directly. Added
      `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` env passthrough so
      the agent planner can authenticate. Acceptable demo-time
      shortcut; the cleaner fix is to read from Vault in the planner
      (followup for after Friday).

### Cross-slice fix (coordinated with Ali)

- [x] `backend/app/services/agent_service.py` — `AnthropicAgentPlanner`
      was crashing two ways: (a) defaulted to `claude-3-5-haiku-latest`
      which was retired Feb 19, 2026; (b) used plain JSON-in-text
      prompting, but newer Claude models wrap responses in prose so
      `json.loads()` crashes. Switched to Anthropic tool-use API with
      a `plan_action` tool schema — Claude returns structured JSON
      natively in `content[].input`, no parsing required. Updated
      test fixture in `test_agent_tools.py` to match the new response
      shape. Default model bumped to `claude-haiku-4-5-20251001`.

### End-to-end verified at demo dress rehearsal

- [x] Two tenants seeded (acme-coffee, brew-bar). Each has separate
      widget config, guardrails config, allowed origins, JWTs.
- [x] Tenant admin sees only their own tenant's data (Phase 2 cross-
      tenant isolation check passed manually).
- [x] Widget loads on `localhost:8080` (allowed host), blocked on
      `localhost:8090` (CSP violation in DevTools console).
- [x] All three live widget messages produce correct behavior:
      - "tell me about your coffee" → real Claude response, stays on
        topic, passes output rail.
      - "I want to speak to a manager" → escalation_trigger fires
        pre-LLM, response: "I will flag this for human follow-up."
      - "What is the weather today?" → off_topic rule fires pre-LLM,
        response uses the tenant's persona template:
        "I can only help with coffee, espresso, beans. That falls
         outside what I can answer here."
- [x] Defense-in-depth: even when the agent (or its stub) returns
      off-topic content, the output rail catches it. Same allowed_topics
      policy guards both input and output paths.

## Phase 6.3 — Real LLM end-to-end (Fri 2026-05-29, late night)

After the dress rehearsal at 11pm, the team agreed to fix the agent
LLM path so the chat reply is grounded in tenant content rather than
falling through to stubs. Three coupled bugs surfaced and got fixed.

### Bugs found and fixed

- [x] `AnthropicAgentPlanner` defaulted to `claude-3-5-haiku-latest`
      (retired Feb 19, 2026, returns 404). Bumped default to
      `claude-haiku-4-5-20251001`.
- [x] `AnthropicAgentPlanner` used plain JSON-in-text prompting.
      Newer Claude models wrap structured output in prose, so
      `json.loads()` crashed. Switched to Anthropic tool-use API
      with a `plan_action` tool schema — Claude returns structured
      JSON natively in `content[].input`, no parsing.
- [x] `AnthropicAgentPlanner._user_prompt` didn't include tool call
      results. So when Claude picked `rag_search` then tried to
      compose `final_response`, it had no content to reference and
      produced generic replies that failed `screen_output`. Fixed:
      tool results (RAG `answer_context`, lead/escalation status)
      now appended to the user prompt before the second iteration.
- [x] `AgentService.run` crashed with 500 when a tool's own
      validation failed (e.g. `capture_lead` called without email
      or phone). Wrapped tool calls in defensive try/except:
      validation failures are now reported as tool-result feedback
      so the planner can recover gracefully, ask the visitor for
      missing info, or pick a different tool.
- [x] `InMemoryEmbeddingRepository` in `chat.py` had one hardcoded
      chunk with `tenant_id="demo-tenant"` — no real tenant ever
      matched. Replaced with per-tenant seed (two coffee chunks for
      acme-coffee, two tea chunks for brew-bar) keyed by real
      tenant UUIDs read from the DB at startup. Falls back to the
      original demo chunk if DB lookup fails.
- [x] `docker-compose.yml` — passed `ANTHROPIC_API_KEY` and
      `ANTHROPIC_MODEL` through to backend container.
      `AnthropicAgentPlanner` reads from `os.getenv`. Mohammad's
      Vault pattern still holds the canonical secret; the env
      passthrough is a demo-time shortcut, noted as a followup.

### Verified end-to-end

- pytest 42/42 green (test_agent_tools + test_chat)
- acme-coffee live widget flow:
    - "tell me about your coffee" → real Claude response mentioning
      espresso/Ethiopia/Colombia from the seeded chunks
    - "tell me about your beans" → real Claude response mentioning
      medium-roast/cold brew/French press
    - "I want to speak to a manager" → escalation pre-LLM
    - "What is the weather today?" → off_topic refusal pre-LLM
- brew-bar live widget flow:
    - "tell me about your tea" → tea-specific response (jasmine,
      oolong, chai, earl grey). No coffee content. Cross-tenant
      isolation confirmed at the content layer.
- Test cases that previously crashed with 500 now return 200 with
  graceful planner recovery.

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
- Spent the morning unwrapping fix-tests. Root cause of yesterday's
  smoke failure: httpx in wrong pyproject section (dev group, not
  runtime). Backend Dockerfile correctly excludes dev → no httpx →
  classifier_client crashes on import → backend never boots. Same
  pyproject misconfiguration broke security-gates redaction test
  (bcrypt missing from CI install set).
- Fixed httpx + reworked security-gates to use uv sync against the
  backend project. Then a cascade of smaller things: wrong health URL
  in smoke (`/health` vs `/healthz`), credential mismatch between
  test client and guardrails container (added env pass-through),
  invalid probe formats in Jana's redaction test (hex chars where
  digits required). 7/7 green. PR open.
- Built guardrails config: migration 004 with RLS, repo, admin
  endpoints (GET/PUT), wired chat.py to load tenant config from DB
  on every turn. Closed two infra gaps along the way: alembic was
  never actually running at backend startup (init.sql was the
  only schema source), and seed_tenants.py needed a bootstrap
  tenant_manager that nothing created. End-to-end demo working:
  admin edits config in DB → chat behavior changes live.
- Morning: investigated yesterday's CI failures on the fix-tests branch.
  Root cause: httpx in [dependency-groups] dev instead of [project]
  dependencies — backend Dockerfile uses `uv sync --no-dev` so httpx
  was missing when classifier_client.py imported it. Fixed
  backend/pyproject.toml + regenerated uv.lock. Same misconfig broke
  security-gates redaction test (bcrypt missing from CI install set).
  Fixed security-gates.yml to use `uv sync --frozen` instead of ad-hoc
  pip. Added GUARDRAILS_SERVICE_CREDENTIAL env to the right step.
  Fixed smoke-test localhost:8002/health → /healthz. Updated
  test_ci_smoke and test_redaction probes (PHONE/SSN/CC had bad chars;
  CC needed Luhn-valid). All 7 CI checks green, merged to main.

- Afternoon: started feature/guardrails-config-ui.
  Built migration 004 (guardrails_configs + RLS) using Mohammad's
  pattern with FORCE row level security. Repo + admin endpoints
  (GET/PUT/test) tenant_admin-gated. Wired chat.py to load tenant
  config from DB on every turn — tenant rails were dead before.
  Hit two infra gaps: alembic was never running at backend boot
  (init.sql was the only schema source), and seed_tenants.py needed
  a platform tenant_manager that nothing created. Built entrypoint.sh
  to bootstrap alembic_version and run upgrade head; wrote
  seed_platform.py for the manager bootstrap. Alembic now runs on
  every boot — whole-team unblock for future migrations.

- Late afternoon: discovered widget-config was 500'ing. Mohammad's
  init.sql had widget_configs as a stub with a literal `-- Charbel:
  add columns` comment — the schema my endpoints assumed never
  existed. Wrote migration 005 adding widget_id, allowed_origins,
  theme, greeting, enabled_tools, updated_at, plus the missing
  tenant_write and tenant_update RLS policies. Verified widget auth
  still round-trips with the new auto-generated widget_id column.

- Evening: built admin/pages/guardrails_config.py (current config,
  edit form with live template preview, test panel that proxies to
  the sidecar). End-to-end verified — PUT keyword 'manager' → chat
  'I want to speak to a manager' → response decision=escalate. Demo
  story for tenant rails is real and live.

- Polish pass: persistent banner pattern (session_state flash) on
  both widget_config and guardrails_config — replaces the silent
  st.toast/st.success+st.rerun that users couldn't see. Fixed the
  template preview to substitute both {topic} and {reason}. Empty
  payload sections now send None instead of [] to match the sidecar's
  Optional schema. Removed misleading theme toggle caption.
```
