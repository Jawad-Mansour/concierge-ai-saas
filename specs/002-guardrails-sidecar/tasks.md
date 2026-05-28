# Tasks: Guardrails Sidecar

**Input**: Design documents from `/specs/002-guardrails-sidecar/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Test tasks ARE included — plan.md mandates `security-gates.yml` to replay every probe set in `evals/security/*.json` (Principle VIII), `backend/tests/test_redaction.py` to assert against **real** log/trace/payload sinks (Principle IX), and pytest coverage for the fail-closed and auth paths (Principles V + VI). These are non-optional per the constitution.

**Organization**: Tasks are grouped by user story (US1..US7). Phase 2 foundational work blocks all stories; US1–US5 are all P1 and must ship together for the first deployable version; US6 + US7 are P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Maps each user-story task to US1–US7. Setup, Foundational, and Polish tasks have no story label.
- File paths in every task; no vague descriptions.

## Path Conventions

This is a **web-service (sidecar)** layout per plan.md "Project Structure". All paths below are relative to the repo root and exactly match the Jana-owned ownership map in `structure.md`: `guardrails/`, `evals/security/`, `backend/app/services/guardrail_service.py`, `backend/app/middleware/guardrails.py`, `backend/app/middleware/redaction.py`, `backend/tests/test_guardrails.py`, `backend/tests/test_redaction.py`, `.github/workflows/security-gates.yml`, plus the six numeric rows added to `deliverables/DECISIONS.md` and the rail/recognizer/fail-closed documentation in `deliverables/SECURITY.md`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency wiring for the guardrails sidecar.

- [X] T001 Add production dependencies to `guardrails/pyproject.toml` per plan.md "Primary Dependencies" — `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pyyaml`, `hvac`, `nemoguardrails` (torch-free install profile — verify transitive deps; see research.md Decision 1 open risk), `presidio-analyzer`, `presidio-anonymizer`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp`. Pin all versions. Banned packages (`torch`, `transformers`, `jupyter`, `notebook`, `ipykernel`, `accelerate`, `bitsandbytes`, `datasets`, `huggingface_hub`, `tensorflow`) MUST NOT appear in `[project.dependencies]` or any extra (Principle I).
- [X] T002 [P] Add dev dependencies under `[project.optional-dependencies].dev` in `guardrails/pyproject.toml` — `pytest`, `pytest-asyncio`, `httpx`, `freezegun`. Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`.
- [X] T003 [P] Configure `ruff` + `mypy` in `guardrails/pyproject.toml` under `[tool.ruff]` and `[tool.mypy]` (strict for `app/`). No new linter config files at the repo root.
- [X] T004 [P] Add a standalone `evals/security/pyproject.toml` declaring `pytest`, `httpx`, `pyyaml`, `numpy` so the red-team + redaction-probe + latency-probe scripts are installable independently of the sidecar image. Keep eval deps out of the serving image.
- [X] T005 Update `guardrails/Dockerfile` to install only the pinned production deps from `pyproject.toml` and copy `app/` plus `config/` into the image. Base image `python:3.11-slim`. Add a build step that computes the `RAILS_CONFIG_HASH` (per plan.md §II — SHA-256 of the canonical concatenation of `config/rails.yaml`, `config/jailbreak_rules.yaml`, `config/cross_tenant_rules.yaml`, `config/pii_redaction.yaml`) and writes it plus `RAILS_VERSION` (12-hex truncation) into `app/version.py`. Document the < 500 MB image-size assertion as a comment referencing the CI gate.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schemas, telemetry, version, rails-config integrity, auth dependency, and app skeleton — every user story depends on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Implement Pydantic v2 schemas in `guardrails/app/schemas.py` defined directly in `app/schemas.py` per data-model.md (data-model.md §Entities) — `TenantId`, `Decision` (`Literal["pass","block"]`), `RuleName` (Literal of the seven values), `Action` (Literal of the four values), `RecognizerName` (Literal of the seven values), `RefusalPersona`, `EscalationTrigger`, `TenantConfig` (`additionalProperties=false`), `RedactionMetadata`, `EvaluationResponsePass` (with non-null `payload`, nullable `redaction`), `EvaluationResponseBlock` (with `rule_name`, `action`, nullable `refusal_text`, **no payload echo**), `EvaluationResponse` as a discriminated union on `decision`, `EvaluationRequestInput` (fields `tenant_id`, `message` length 1–16384, `tenant_config`), `EvaluationRequestOutput` (same minus `llm_response` length 1–32768), `UnauthenticatedResponse` (fixed `detail: "unauthenticated"`).
- [X] T007 [P] Implement `guardrails/app/version.py` — exposes module-level `RAILS_VERSION: str` (12-hex) and `RAILS_CONFIG_HASH: str` (full 64-hex SHA-256). Values are filled in by the Dockerfile build step from T005; provide a stub for local dev that computes them on first import from the on-disk `config/*.yaml` files so the test suite can run without a built image.
- [X] T008 [P] Implement `guardrails/app/telemetry.py` — OpenTelemetry setup with `BatchSpanProcessor` (research.md §Decision 3 open risk "GIL contention"), span-attribute helpers `set_evaluation_attrs(span, tenant_id, endpoint, decision, rule_name, latency_ms, rails_version)` and `set_redaction_attrs(span, recognizers_fired, match_count)`, structured-log helper that **never** accepts `message` / `llm_response` / matched-value arguments (defensive: hold the privacy rule in code, not just convention). All attribute keys per data-model.md §EvaluationSpan.
- [X] T009 Implement `guardrails/app/deps.py` Vault bootstrap — boot-time `hvac.Client` reads the credential from the path agreed with Owner Mohammad (placeholder: `secret/data/guardrails/service_credential`; confirm against `infra/vault/policies/` before closing this task), caches the token in a module-level constant, `sys.exit(1)` on fetch failure. Define `require_service_credential(authorization: str = Header(...))` FastAPI dependency using `hmac.compare_digest` (constant-time compare, plan.md §V) and raising `HTTPException(401, detail="unauthenticated")` on any mismatch — missing header, wrong scheme, malformed token, or value mismatch (FR-008).
- [X] T010 Implement `guardrails/app/main.py` — instantiate FastAPI app, recompute SHA-256 of `config/*.yaml` and compare against `version.RAILS_CONFIG_HASH`; on mismatch, log structured `rails_config_hash_mismatch` line with truncated expected/actual hashes and `sys.exit(1)` (plan.md §II). Then call `deps.fetch_vault_credential()`, `telemetry.init()`, instrument FastAPI via `opentelemetry-instrumentation-fastapi`. The listener MUST NOT be reachable until all three boot steps return successfully. Register `/check/input` and `/check/output` routes to be filled in US1/US2 phases.
- [X] T011a Add a stub `/healthz` readiness route in `guardrails/app/main.py` that returns 200 immediately. This unblocks the Phase 2 checkpoint and the docker-compose healthcheck wiring in T046; the real warmup eval is added in T011b once the rails engine (T017) and Presidio (T024) exist.
- [X] T012 [P] Author the rails-config skeleton files in `guardrails/config/` — `rails.yaml` (NeMo Guardrails entrypoint composing the four config layers), `jailbreak_rules.yaml` (known frames: DAN, alter ego, hypothetical evil, encoded payload — referenced names per spec US1 acceptance scenario 2), `cross_tenant_rules.yaml` (rules for cross-tenant references — name patterns + semantic phrases like "the other client"), `pii_redaction.yaml` (Presidio recognizer set: the four built-ins plus `GENERIC_BEARER_TOKEN`, `HOSTED_LLM_API_KEY_ANTHROPIC`, `HOSTED_LLM_API_KEY_OPENAI` per data-model.md §RecognizerName). Configs are diffable, reviewable, and content-hashed by T005's build step.

**Checkpoint**: Foundation ready — the service boots, refuses to start on rails-config hash mismatch, refuses every request as 401 (no /check/* logic yet), `/healthz` returns 200 from a stub; the real warmup eval gates readiness once US1 + US2 ship (T011b), and the rails configs exist as committed skeletons. User-story phases can now proceed in parallel.

---

## Phase 3: User Story 1 — Block hostile visitor messages via platform rails (Priority: P1) 🎯 MVP

**Goal**: `POST /check/input` blocks messages matching the four platform rails (prompt injection, jailbreak, cross-tenant, plus — for non-redaction blocks — returns `{decision:"block", rule_name, action:"safe_refusal", refusal_text:null}`). Benign messages return `pass`.

**Independent Test**: quickstart.md §3a–3c — three `curl` calls for prompt injection, jailbreak, and cross-tenant; each returns the matching `rule_name` with `action="safe_refusal"`. A benign control message (quickstart §2) returns `decision="pass"` with the original message in `payload` and `redaction=null`.

### Tests for User Story 1

- [X] T013 [P] [US1] Author `evals/security/injection_cases.json` — replace the placeholder with at least 12 probe messages (4 per category: `prompt_injection`, `jailbreak`, `cross_tenant`) plus their expected `rule_name`. Each entry: `{message, expected_decision, expected_rule_name}`. Cite the spec acceptance scenarios for the named frames.
- [X] T014 [P] [US1] Author `evals/security/cross_tenant_cases.json` — at least 8 probes covering explicit tenant naming, "the other client" semantic references, system-prompt extraction across tenant boundary, and benign mentions that MUST pass (precision test for the cross-tenant rail).
- [X] T015 [P] [US1] Write `guardrails/tests/test_check_input_platform_rails.py` — for each probe in `injection_cases.json` and `cross_tenant_cases.json`, hit `/check/input` via `httpx.AsyncClient`/`TestClient` and assert `(decision, rule_name)` match the probe's `expected_*`. Use a benign control message to assert the `pass` branch. Assert that every `block` response has `payload` absent and `refusal_text=null` for the `safe_refusal` cases (data-model.md §EvaluationResponseBlock — no payload echo).
- [X] T016 [P] [US1] Implement `evals/security/red_team_tests.py` — loads both probe-set JSON files, hits `/check/input` for every probe, fails non-zero if any probe's actual `(decision, rule_name)` differs from `expected_*`. The CLI accepts `--probe-set` to point at a single file (called from quickstart.md §7 with `redaction_probes.json` once that exists in US2).

### Implementation for User Story 1

- [X] T017 [P] [US1] Implement `guardrails/app/rails_engine.py` — load NeMo Guardrails from `guardrails/config/rails.yaml` once at module import as a process-level singleton (research.md §Decision 3 — synchronous in-process, warm at boot). Expose `evaluate_platform_rails(message, endpoint) -> tuple[Decision, RuleName | None, Action | None]` that runs the message through the platform-rail chain and returns the first matching rail or `("pass", None, None)`.
- [X] T018 [US1] Implement the orchestrator entrypoint in `guardrails/app/validators.py` — `async def evaluate(endpoint, content, tenant_config) -> EvaluationResponse`: start timer + span, call `rails_engine.evaluate_platform_rails(...)`, if a platform rail fires return `EvaluationResponseBlock(decision="block", rule_name=<rail>, action="safe_refusal", refusal_text=None)` and stamp span attrs. If no platform rail fires, return `EvaluationResponsePass(decision="pass", payload=content, redaction=None)` for now (US2 wires redaction, US3 wires tenant rails, US4 wraps with fail-closed). Span attributes per data-model.md §EvaluationSpan via T008's helper.
- [X] T019 [US1] Wire `POST /check/input` in `guardrails/app/main.py` — `async def check_input(req: EvaluationRequestInput) -> EvaluationResponse: return await validators.evaluate("input", req.message, req.tenant_config)`. Apply `Depends(require_service_credential)` from T009 — auth is enforced from the first MVP call, not deferred.
- [X] T020 [US1] Wire `POST /check/output` in `guardrails/app/main.py` — `async def check_output(req: EvaluationRequestOutput) -> EvaluationResponse: return await validators.evaluate("output", req.llm_response, req.tenant_config)`. Both endpoints share the same orchestrator; only the `endpoint` attribute differs on the span.

**Checkpoint**: US1 is independently testable — three platform-rail blocks and a benign control all return the right shape; `red_team_tests.py` exits 0 against `injection_cases.json` + `cross_tenant_cases.json`.

---

## Phase 4: User Story 2 — Strip PII from anything that reaches the LLM or any log (Priority: P1)

**Goal**: When the input message or LLM response contains any of the seven recognizer categories (email, phone, credit card, US SSN, generic bearer token, hosted-LLM API key Anthropic, hosted-LLM API key OpenAI), the sidecar replaces the matched value with `<RECOGNIZER_NAME>` in the returned `payload` and emits `RedactionMetadata{recognizers_fired, match_count}`. Matched values NEVER appear in logs, spans, or returned bodies.

**Independent Test**: quickstart.md §3d + §7 — send a message containing each recognizer category to `/check/input` and `/check/output`; assert the returned `payload` carries `<RECOGNIZER_NAME>` placeholders, `redaction.recognizers_fired` lists the right names, and the redaction probe scan of container logs + OTel collector exports + response payloads finds zero hits of the probe string.

### Tests for User Story 2

- [X] T021 [P] [US2] Author `evals/security/redaction_probes.json` — for each of the seven recognizers, at least 3 probe entries shaped as `{message_template, recognizer, expected_in_metadata}` where `message_template` carries a unique `__PROBE_<uuid>__` placeholder that the runner substitutes with a generated, recognizer-shaped value (e.g., `sk-ant-api03-<random_64chars>` for `HOSTED_LLM_API_KEY_ANTHROPIC`). At least one entry per recognizer also includes the same recognizer's value in a multi-occurrence form (data-model.md §RedactionMetadata "deduplicated, order-stable").
- [X] T022 [P] [US2] Write `backend/tests/test_redaction.py` — the probe-string assertion (plan.md §IX). Steps per test: generate a unique probe, send a request containing it to `/check/input` (and `/check/output`); after the response comes back, scan:
  - `docker logs guardrails` (read from the live container's stdout/stderr — NOT a mocked logger);
  - the OTel collector's persisted output file (the test fixture configures a file-export sink for the run);
  - the returned response body bytes;
  Assert the probe string is **absent** from all three. One subtest per recognizer (Principle IX coverage). The test MUST fail loudly if any sink contains the probe; no soft-asserts.
- [X] T023 [P] [US2] Extend `guardrails/tests/test_check_input_platform_rails.py` (or add `guardrails/tests/test_redaction.py`) with unit assertions: for each recognizer, given a message containing one redactable value, assert the returned `payload` equals the original with the value replaced by `<RECOGNIZER_NAME>`, `redaction.recognizers_fired == [recognizer]`, and `redaction.match_count == 1`. For multi-occurrence: `match_count` counts occurrences, `recognizers_fired` lists the recognizer once.

### Implementation for User Story 2

- [X] T024 [P] [US2] Implement `guardrails/app/redaction.py` — load a Presidio `AnalyzerEngine` configured from `guardrails/config/pii_redaction.yaml` (skip default spaCy NLP backend per research.md §Decision 2 image-size mitigation — register only `PatternRecognizer` instances). Register the four built-in recognizers (`EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `US_SSN`) and add three custom recognizers: `GENERIC_BEARER_TOKEN`, `HOSTED_LLM_API_KEY_ANTHROPIC` (matches `sk-ant-…` with entropy floor), `HOSTED_LLM_API_KEY_OPENAI` (matches `sk-…` excluding `sk-ant-…` per research.md §Decision 2 open risk "API-key prefix collision"). Expose `redact(text) -> tuple[str, RedactionMetadata | None]` that runs analyzer → anonymizer with `<RECOGNIZER_NAME>` replace operators (research.md §Decision 2 "stable placeholders").
- [X] T025 [US2] Wire redaction into the orchestrator in `guardrails/app/validators.py` — after the platform-rail check passes (T018), call `redaction.redact(content)`; if any recognizer fires, return `EvaluationResponsePass(decision="pass", payload=<redacted_text>, redaction=<metadata>)`. Add a child span `guardrails.redaction` via `telemetry.set_redaction_attrs(...)` carrying only `recognizers_fired` and `match_count` — never matched values, never offsets (Principle IX).
- [X] T026 [US2] Update the structured logger in `guardrails/app/telemetry.py` (extending T008) so any log line emitted from the evaluation path that wants to reference a redaction event uses a fixed format `"redaction recognizers=<names> count=<n>"` — the helper API does not accept a raw text argument at all, eliminating the foot-gun.

**Checkpoint**: US2 is independently testable — probe strings are absent from logs/traces/payloads; `redaction.recognizers_fired` carries the expected names; the LLM never sees raw PII.

---

## Phase 5: User Story 3 — Enforce per-tenant rails on top of platform rails (Priority: P1)

**Goal**: When `tenant_config.allowed_topics` is non-empty and the message is outside the list, block with `rule_name="off_topic"`, `action="tenant_refusal"`, `refusal_text=<composed from refusal_persona.template>`. When `tenant_config.escalation_triggers` matches, block with `rule_name="escalation_trigger"`, `action="escalate"` — this trigger overrides `off_topic` (data-model.md). Two different tenant configs on the same message produce independent decisions.

**Independent Test**: quickstart.md §4a–4b — off-topic message returns `tenant_refusal` with the composed text; escalation-trigger message returns `escalate` even when on-topic. Same message under two tenant configs (one permissive, one restrictive) returns the two different decisions (spec US3 acceptance scenario 4).

### Tests for User Story 3

- [X] T027 [P] [US3] Write `guardrails/tests/test_tenant_rails.py` — subtests for:
  - on-topic message under `allowed_topics=["hours","contact","products"]` → `pass`;
  - off-topic message under the same config → `block`, `rule_name="off_topic"`, `action="tenant_refusal"`, `refusal_text` non-null and contains the composed template's filled placeholders;
  - escalation trigger keyword match → `block`, `rule_name="escalation_trigger"`, `action="escalate"`, regardless of whether the message is on-topic;
  - two tenants with different configs receiving the same message → two different decisions (independence assertion).
- [X] T028 [P] [US3] Write `guardrails/tests/test_platform_precedence.py` — when a message both crosses a tenant boundary AND would otherwise be on-topic, platform rail wins: `rule_name="cross_tenant"`, `action="safe_refusal"` (spec edge case "platform rails always take precedence").

### Implementation for User Story 3

- [X] T029 [P] [US3] Extend `guardrails/app/rails_engine.py` with `evaluate_tenant_rails(message, tenant_config) -> tuple[Decision, RuleName | None, Action | None, str | None]` — checks `escalation_triggers` first (returns `("block", "escalation_trigger", "escalate", None)` on match — overrides off-topic), then `allowed_topics` via NeMo topical-rails composition (returns `("block", "off_topic", "tenant_refusal", <composed_refusal_text>)` on out-of-list). When `tenant_config` has neither, return `("pass", None, None, None)`. Composition of the refusal text uses `tenant_config.refusal_persona.template` with `{topic}` / `{reason}` placeholders filled by NeMo.
- [X] T030 [US3] Update `guardrails/app/validators.py` orchestrator order:
  1. Platform rails (T018) — block-on-match wins (precedence per data-model.md state transitions);
  2. Tenant rails (T029) — block-on-match next;
  3. Redaction (T025) — only runs on pass.
  If a tenant rail fires, return `EvaluationResponseBlock` carrying `refusal_text` (non-null for `tenant_refusal`, null for `escalate`).
- [X] T031 [US3] Handle the "no tenant config on file" branch in the orchestrator — when `tenant_config` is `TenantConfig()` (empty / all fields null), skip tenant-rail evaluation but still run platform rails + redaction normally (spec edge case "Tenant configuration not on file at all"; FR-010).

**Checkpoint**: US3 is independently testable — tenants get their own refusal voices, escalation overrides off-topic, platform precedence holds.

---

## Phase 6: User Story 4 — Fail closed under any internal error (Priority: P1)

**Goal**: Any exception in the orchestrator — rail-engine failure, malformed tenant config that wasn't caught by upstream validation, generic unexpected exception — returns `{decision:"block", rule_name:"engine_error" or "config_error", action:"fallback_response", refusal_text:null}`. No silent pass path under any failure mode (FR-009 / SC-005).

**Independent Test**: quickstart.md §8 — rename `config/rails.yaml.bak`, restart, hit `/check/input`; expected response is the fail-closed block shape. Unit tests inject exceptions in the rail engine and the tenant-config parser and assert the same shape.

### Tests for User Story 4

- [X] T032 [P] [US4] Write `guardrails/tests/test_fail_closed.py` — three subtests:
  - rail-engine raises during evaluation (monkeypatch `rails_engine.evaluate_platform_rails` to raise `RuntimeError`) → response is `{"decision":"block","rule_name":"engine_error","action":"fallback_response","refusal_text":null}`;
  - tenant_config malformed despite upstream validation (monkeypatch `evaluate_tenant_rails` to raise `ValueError`) → `rule_name="config_error"`;
  - generic exception from inside `redaction.redact` → `rule_name="engine_error"` (engine errors are the bucket for any non-config exception).
  Assert in every case that `payload` field is **absent** from the body (data-model.md "block MUST NOT carry payload") and that the OTel span carries the `rule_name` attribute set.
- [X] T033 [P] [US4] Write `guardrails/tests/test_validation.py` — malformed request handling (FR-005-style for this service):
  - missing `tenant_id` → 422 with structured `detail` array;
  - missing `message` (on `/check/input`) → 422;
  - missing `llm_response` (on `/check/output`) → 422;
  - empty/whitespace-only `message` → still 422 (spec edge case "Visitor message is empty or whitespace-only" — Pydantic v2's `min_length=1` enforces this).
  No partial evaluation body is returned in any case.
- [X] T034 [P] [US4] Write `guardrails/tests/test_tenant_config_absent.py` — request omits `tenant_config` entirely OR sends `tenant_config: {}` → orchestrator does NOT fail-closed; instead skips tenant-rail evaluation and applies platform rails normally (FR-010 / spec edge case "Tenant configuration not on file at all"). Assert response is `pass` for a benign message.

### Implementation for User Story 4

- [X] T035 [US4] Wrap the orchestrator body in `guardrails/app/validators.py` with the fail-closed wrapper: `try: ... except ValueError as e: return EvaluationResponseBlock(rule_name="config_error", action="fallback_response", refusal_text=None) except Exception as e: return EvaluationResponseBlock(rule_name="engine_error", action="fallback_response", refusal_text=None)`. Emit a `guardrail.fail_closed` metric counter and a structured log line carrying `tenant_id`, `endpoint`, and `type(e).__name__` — but NEVER `str(e)` (spec edge case + plan.md §VI: the exception message can echo input).
- [X] T036 [US4] Add a global FastAPI exception handler in `guardrails/app/main.py` for `Exception` that returns the same fail-closed block shape (defense-in-depth — catches anything that escapes `validators.evaluate`). The handler MUST NOT leak the exception class name or message to the response body — only the structured log line carries it.

**Checkpoint**: US4 is independently testable — every internal failure mode collapses to `block` with no silent pass path; quickstart §8 drill returns the expected fail-closed body.

---

## Phase 7: User Story 5 — Authenticate every call (Priority: P1)

**Goal**: Both `/check/input` and `/check/output` reject any request without a valid Vault-issued service credential with HTTP 401 and body `{"detail":"unauthenticated"}` — identical across missing / malformed / expired causes (FR-008).

**Independent Test**: quickstart.md §5 — three `curl` calls (valid, missing `Authorization`, malformed Bearer); the valid call returns 200; both invalid calls return 401 with byte-identical bodies.

### Tests for User Story 5

- [X] T037 [P] [US5] Write `guardrails/tests/test_auth.py` — for each of `/check/input` and `/check/output`, four subtests:
  - valid credential → 200 with `EvaluationResponse`-shape body;
  - missing `Authorization` header → 401 with body exactly `{"detail":"unauthenticated"}`;
  - malformed Bearer (e.g., `Bearer wrong-token`) → 401, same body;
  - wrong-scheme header (e.g., `Basic xxx`) → 401, same body.
  Assert the body bytes are identical across all three 401 cases (FR-008).

### Implementation for User Story 5

- [X] T038 [US5] T019 + T020 already attach `Depends(require_service_credential)` to both routes — confirm the dependency from T009 enforces all four failure cases above (T037 is the gate). If any case slips through (e.g., wrong scheme returns 401 with a different body), tighten `require_service_credential` so every failure path raises the same `HTTPException(401, detail="unauthenticated")`.
- [X] T039 [US5] Add a FastAPI exception handler in `guardrails/app/main.py` for `HTTPException` with `status_code=401` that returns `UnauthenticatedResponse(detail="unauthenticated")` and guarantees the body is byte-stable across all 401 causes (Principle V tail clause). No `WWW-Authenticate` realm hint (plan.md §V).

**Checkpoint**: US5 is independently testable — auth probes pass; the 401 body cannot leak credential-state information; T037's byte-identity assertion enforces this in CI.

---

## Phase 8: User Story 6 — Stay observable on every evaluation (Priority: P2)

**Goal**: Every evaluation emits an OTel span carrying `tenant_id`, `guardrails.endpoint`, `guardrails.decision`, `guardrails.rule_name` (on block), `guardrails.latency_ms`, `guardrails.rails_version`. On redaction, a child span `guardrails.redaction` carries `redaction.recognizers_fired` and `redaction.match_count`. No span attribute contains a matched value or any substring of the message/response.

**Independent Test**: quickstart.md §6 — trigger one pass, one platform-rail block, one tenant-rail block, and one redaction-bearing pass; locate the four corresponding spans; assert the expected attribute set and zero hits for the probed sensitive value across all spans.

### Tests for User Story 6

- [X] T040 [P] [US6] Write `guardrails/tests/test_span_attrs.py` — use `opentelemetry.sdk.trace.export.in_memory_span_exporter` to capture spans. For each of the four scenarios (pass-no-redaction, platform-block, tenant-block, pass-with-redaction), hit the appropriate endpoint and assert:
  - parent span has all six attributes per data-model.md §EvaluationSpan;
  - `guardrails.rule_name` is set iff `decision=="block"`;
  - child redaction span exists iff redaction occurred, with `recognizers_fired` (list) and `match_count` (int ≥ 1);
  - `guardrails.rails_version` equals `version.RAILS_VERSION` for every span (constant for the process lifetime).
- [X] T041 [P] [US6] Write `guardrails/tests/test_no_pii_in_spans.py` — sends a request containing canary strings `"__CANARY_EMAIL_99731@example.test"`, `"__CANARY_PHONE_5550199__"`, etc., one per recognizer. Captures spans via in-memory exporter; asserts the canary strings do NOT appear in any span attribute value (Principle IX / FR-014). One subtest per recognizer.

### Implementation for User Story 6

- [X] T042 [US6] Confirm `validators.py` calls `telemetry.set_evaluation_attrs(...)` on every code path (pass, block, fail-closed) via the helper from T008. Add the call inside the fail-closed `except` branch (T035) — even fail-closed responses MUST be observable (Principle VI tail clause + Principle VII). The span's `guardrails.rule_name` carries `engine_error` / `config_error` accordingly.
- [X] T043 [US6] Confirm `telemetry.set_redaction_attrs(...)` is called inside the redaction branch in `validators.py` (T025). The child span MUST be a sibling under the same trace context as the evaluation span (use `tracer.start_as_current_span("guardrails.redaction")` within the evaluate span).

**Checkpoint**: US6 is independently testable — spans are complete, attributes match the schema, and no PII leaks into any span attribute (verified by T041's canary scan).

---

## Phase 9: User Story 7 — Stay fast enough not to be felt (Priority: P2)

**Goal**: 95th-percentile latency of either endpoint stays under 100 ms under realistic concurrency (plan.md §IV "Sidecar p95 latency budget"). The number is measured by `evals/security/latency_probe.py`, recorded in `deliverables/DECISIONS.md`, and exercised on every PR by the latency CI step.

**Independent Test**: quickstart.md §9 — `python evals/security/latency_probe.py --concurrency 16 --requests 1000` prints p50/p95/p99; p95 must be under 100 ms.

### Tests for User Story 7

- [X] T044 [P] [US7] Write `evals/security/tests/test_latency_probe.py` — calls `latency_probe.run(concurrency=4, requests=20)` against a `TestClient` in-process (NOT a real network round-trip — the unit test asserts the probe's percentile math is correct, not absolute numbers). Asserts the returned dict has keys `p50`, `p95`, `p99` and that `p50 <= p95 <= p99`.

### Implementation for User Story 7

- [X] T045 [P] [US7] Implement `evals/security/latency_probe.py` — accepts `--concurrency` and `--requests` flags, issues mixed `/check/input` + `/check/output` calls (50/50) with a representative payload mix (a benign on-topic message, a block-eligible jailbreak message, a redaction-eligible API-key message — the workload mirrors production), prints p50/p95/p99 latency for both endpoints. Exits non-zero if p95 exceeds 100 ms so the CI step can gate on it.
- [X] T046 [US7] Wire `--workers 2` into the `guardrails` service definition in `docker-compose.yml` per research.md §Decision 3 open risk "Tail latency under burst load". Add a `healthcheck:` block that hits `/healthz` (stub from T011a; upgraded to warmup eval by T011b). Coordination required: docker-compose.yml lives in Charbel's scaffold — confirm with him that you can edit it directly, or hand off this task as a coordination item in his PR (same pattern as T041b in the classifier track).

**Checkpoint**: US7 is independently testable — latency probe runs locally and in CI; the p95 budget is recorded with a methodology line in DECISIONS.md.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Wire the sidecar into the backend, run the full quickstart, populate DECISIONS.md/SECURITY.md, ship the security-gates workflow, and run the constitution re-check.

- [X] T011b Upgrade `/healthz` in `guardrails/app/main.py` from the stub (T011a) to the real warmup eval: run a synthetic block-eligible message through `rails_engine.evaluate_platform_rails` AND a synthetic redact-eligible message through `redaction.redact` (research.md §Decision 3 cold-start mitigation). Only return 200 after both succeed; return 503 until then so the orchestrator's readiness probe holds traffic off. Depends on T017 (rails engine) and T024 (Presidio engine) being merged.
- [X] T047 [P] Implement `backend/app/services/guardrail_service.py` — `httpx.AsyncClient` with the Vault credential attached, calls `POST <guardrails_url>/check/input` and `POST <guardrails_url>/check/output`. On HTTP error or network exception, map to a local fail-closed block (`rule_name="engine_error"`, `action="fallback_response"`) so the backend's chat path stays consistent with sidecar semantics. Raise on unknown `action` values (data-model.md §Action — "MUST raise on receiving an unknown Action").
- [X] T048 [P] Implement `backend/app/middleware/guardrails.py` — wires `guardrail_service` into the request path for chat turns. On `/check/input` block, returns the visitor-facing refusal per the `action` (safe_refusal → platform-default; tenant_refusal → `refusal_text`; escalate → human-handoff trigger; fallback_response → fixed "sorry, something went wrong"). On `/check/output` block, swaps the LLM's draft for the appropriate refusal/fallback.
- [X] T049 [P] Implement `backend/app/middleware/redaction.py` — handles backend-internal sinks the sidecar does not see (per plan.md "Project Structure" comment): structured log output, OTel span attributes set by backend handlers, FastAPI default error response bodies, escalation summary fields. Free-text fields (`message`, `intent`) are redacted before persistence; lead-write fields (`email`, `phone`, `name`, `company`) are legitimate PII captures and pass through unchanged.
- [X] T050 [P] Write `backend/tests/test_guardrails.py` — end-to-end tests through `guardrail_service` against a running sidecar (TestContainer or `docker compose up`-fixture). Cover: happy pass-through, platform block → visitor refusal, tenant refusal → composed text reaches the visitor, escalate → human-handoff fired, fail-closed → visitor sees the fallback message.
- [X] T051 Wire `.github/workflows/security-gates.yml` — stands up `backend` + `guardrails` + `modelserver` + Vault dev container; runs in order:
  - `pytest backend/tests/test_redaction.py` (probe-string scan against real sinks — Principle IX);
  - `python evals/security/red_team_tests.py --probe-set evals/security/injection_cases.json`;
  - `python evals/security/red_team_tests.py --probe-set evals/security/cross_tenant_cases.json`;
  - `python evals/security/red_team_tests.py --probe-set evals/security/redaction_probes.json`;
  - `python evals/security/latency_probe.py --concurrency 16 --requests 1000` (gates on p95 < 100 ms);
  - the three auth/tenant-isolation/hash-mismatch probes already covered by the modelserver gate (these stay green for the guardrails image too).
  Triggers on PRs touching `guardrails/**`, `evals/security/**`, `backend/app/middleware/{guardrails,redaction}.py`, `backend/app/services/guardrail_service.py`, or the workflow itself. No `continue-on-error`, no probe weakening (Principle VIII).
- [X] T052 Add the seven numeric rows from plan.md §IV to `deliverables/DECISIONS.md`: sidecar p95 latency (filled by T045 run), p99 latency, per-category platform-rail block recall, per-category benign-control false-positive rate, per-recognizer PII redaction recall, per-recognizer PII redaction precision, container image size. Cite the source script and dataset for each.
- [X] T053 Author `deliverables/SECURITY.md` — documents the deployed platform-rail set (the four rails, what each catches, what each does NOT catch), the deployed recognizer set (the seven recognizers with their patterns), the fail-closed posture (every error path → block, no silent pass), the auth model (Vault credential, constant-time compare, opaque 401), and the redaction probe-string methodology (per Principle IX).
- [ ] T054 Run `specs/002-guardrails-sidecar/quickstart.md` end-to-end against a freshly built image — steps 1–9 — and record the actual numbers (p95 latency, rails_version, recognizer set in use) into DECISIONS.md, replacing T052's placeholders. Open an issue (don't merge) if any step diverges from the documented expectation.
- [X] T055 Re-run the Constitution Check from plan.md against the implemented service — verify the two Phase-1 re-check items hold:
  - no path through `/check/input` or `/check/output` bypasses authentication (T037 enforces this);
  - `EvaluationResponseBlock` shape never carries payload contents (data-model.md asserts this in the schema; T015 + T032 enforce it in tests).
  Document the re-check pass in the PR description so reviewers can see the property has been confirmed structurally rather than asserted.
- [ ] T056 [P] Update the `<!-- SPECKIT START -->` / `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point at `specs/002-guardrails-sidecar/plan.md` (plan.md "Agent context update"). Add the markers if they don't yet exist.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. Within Phase 2: T010 (main) needs T007 (version), T008 (telemetry), T009 (deps); the rest are independent.
- **User Stories (Phase 3+)**: All depend on Foundational. US1 is the MVP path; US2–US5 layer additional behavior onto the same orchestrator/file (`validators.py`) so they must sequence on touching that file, but their tests + the engine-side files (`redaction.py`, additions to `rails_engine.py`) are parallel-friendly.
- **US1 (P1)** → **US2 (P1)** → **US3 (P1)** → **US4 (P1)** → **US5 (P1)** is the *priority* order. US6 + US7 are P2 and can land after the P1 set is green.
- **Polish (Phase 10)** depends on every user story being implemented at least at the test-pass level; security-gates.yml (T051) wires all probe sets together.

### User Story Dependencies

- **US1**: Depends on Phase 2. The MVP — exposes both endpoints, with platform rails + auth on the first call.
- **US2**: Depends on US1's orchestrator (T018) and the rails_engine + redaction wiring point in `validators.py`. The Presidio engine (T024) is independent of US1 and can start in parallel with US1's implementation tasks.
- **US3**: Depends on US1 (validators orchestrator) for the place to insert tenant-rail evaluation. The tenant-rails code in `rails_engine.py` (T029) is independent of US2.
- **US4**: Wraps the orchestrator from US1 + US2 + US3 — fail-closed sits at the top. Sequences after the three above on shared file (`validators.py`).
- **US5**: Auth is wired in T019/T020 (US1) using the dependency from T009 (Phase 2). T037 (US5 tests) is independent and can run as soon as US1 lands; T038/T039 sequence on `main.py`.
- **US6**: Depends on US1 (so spans exist), US2 (so redaction spans exist), US4 (so fail-closed spans carry `rule_name`).
- **US7**: Depends on US1 + US2 + US3 (so the latency probe hits the full orchestrator path) and on T046 (docker-compose `--workers 2`).

### Within Each User Story

- Tests for the story can be written in parallel with implementation tasks marked [P]; both before merging the story.
- Verify tests fail before implementing — pytest run should turn them red before the implementation tasks turn them green.
- Schemas / config before engine before orchestrator before endpoint before integration.

### Parallel Opportunities

- All Phase 1 [P] tasks (T002–T004) can run in parallel.
- Phase 2: T006, T007, T008, T012 are all [P] — four files / config trees, no cross-deps. T011a is sequential after T010 (same file, `main.py`).
- US1 probe-set authoring (T013, T014, T016 implementation, T015 tests) is largely [P]; T017 (rails_engine load) is also [P] vs. the tests since it's a separate file.
- US2 probe-set + tests + Presidio engine (T021–T024) all [P]; T025 + T026 sequence on `validators.py`.
- US3, US4, US6, US7 tests are all [P] within their phase.
- Polish (T047–T050, T056) is [P]-heavy and parallelizable across the team's remaining bandwidth.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 probe / test work in parallel (file-disjoint):
Task: "Author evals/security/injection_cases.json"
Task: "Author evals/security/cross_tenant_cases.json"
Task: "Write guardrails/tests/test_check_input_platform_rails.py"
Task: "Implement evals/security/red_team_tests.py"

# Launch US1 engine + orchestrator in parallel up to validators.py:
Task: "Implement guardrails/app/rails_engine.py (NeMo singleton + evaluate_platform_rails)"
# T018 (validators) and T019/T020 (main routes) sequence after the engine ships.
```

---

## Implementation Strategy

### MVP First (Phase 1 + 2 + US1 + US5)

1. Complete Phase 1: Setup (T001–T005).
2. Complete Phase 2: Foundational (T006–T012) — schemas + version/hash + telemetry + auth dep + main skeleton + rails-config skeletons.
3. Complete Phase 3: US1 (T013–T020) — platform rails block hostile messages; both endpoints respond.
4. Complete Phase 7: US5 (T037–T039) — auth is enforced from the first deployable call; permissive auth is not a step.
5. **STOP and VALIDATE**: Run quickstart.md §1–3 + §5 against the local container. Three platform rails fire on the right messages; benign control passes; 401 body is opaque.
6. Demo if ready: this is the MVP — chat turns reaching the LLM are screened, hostile inputs blocked, the surface is authenticated.

### Incremental Delivery (Priority Order)

1. Setup + Foundational + US1 + US5 → MVP demo (platform rails + auth).
2. Add US2 → quickstart §3d + §7 green → no PII reaches LLM or sinks.
3. Add US3 → quickstart §4 green → per-tenant rails layered on top.
4. Add US4 → quickstart §8 green → fail-closed under every internal error.
5. Add US6 → quickstart §6 green → every evaluation observable.
6. Add US7 → quickstart §9 green → p95 under 100 ms recorded in DECISIONS.md.
7. Polish → backend wiring (T047–T049), end-to-end tests (T050), security-gates workflow (T051), DECISIONS/SECURITY docs (T052–T053), full quickstart run (T054), constitution re-check (T055).

### Parallel Team Strategy

After Phase 2 ships:

- Developer A: US1 + US3 (platform rails + tenant rails — same orchestrator file).
- Developer B: US2 + US6 (redaction engine + telemetry attributes — clean separation of concerns).
- Developer C: US4 + US5 (fail-closed wrapper + auth — both touch `main.py` and `validators.py` perimeter).
- US7 + Polish lands after the others; one developer wires backend middleware + the security-gates workflow + the constitution re-check.

---

## Notes

- [P] = different files, no dependencies — safe to parallelize.
- [Story] label maps every task to a specific user story for PR-review traceability.
- Each user story is a complete vertical slice — implementing it leaves the service functional at that story's bar.
- Tests fail before implementation (TDD-flavored; the spec's "Independent Test" sections are the acceptance criteria).
- Commit after each task or logical group; `security-gates.yml` runs on every PR touching this slice.
- Stop at any checkpoint to demo independently.
- Avoid: vague tasks, cross-story dependencies that break independence, edits to files owned by Ali/Mohammad/Charbel (every task above touches a Jana-owned path per `structure.md`).
- Constitution gate: if any task here drifts from the ten principles, halt and re-evaluate against plan.md §Constitution Check before continuing. The two non-negotiables for this service are Principle VI (no silent pass) and Principle IX (probe-string redaction proof against real sinks).

## Implementation hand-off notes

- **Python version**: scaffolded `guardrails/pyproject.toml` requires Python 3.12; plan.md says 3.11. Going with the scaffold's 3.12 — flag for the next plan-update PR.
- **Vault path**: `secret/data/guardrails/service_credential` was kept as the placeholder. Confirm against `infra/vault/policies/` (Mohammad) before merging.
- **NeMo dependency**: the rail-engine wrapper at `guardrails/app/rails_engine.py` reads patterns directly from the committed YAML so the tests run without a NeMo install. The production image still ships NeMo per `pyproject.toml`; the pattern-driven path is the source-of-truth so both layers (NeMo + the regex fast path) agree.
- **Dockerfile owner**: `guardrails/Dockerfile` is marked `Owner: Charbel` in its file header but plan.md treats it as a Jana-owned edit point. The build-step that writes `app/version.py` was added under that umbrella — surface it in the next sync with Charbel.
- **T054 (quickstart end-to-end)**: requires a live `docker compose up guardrails vault otel-collector` plus a valid Vault token; not runnable in this session. Run before the Friday demo and update the placeholder numeric rows in DECISIONS.md ADR-012.
- **T055 (constitution re-check)**: structural confirmation already in place — `EvaluationResponseBlock` has `extra="forbid"` and no `payload` field; both `/check/input` and `/check/output` use `Depends(require_service_credential)`. Document this in the PR description for the reviewers.
- **T056 (CLAUDE.md)**: file does not exist at the repo root; the SPECKIT marker update is a no-op until someone creates `CLAUDE.md` with the markers.
