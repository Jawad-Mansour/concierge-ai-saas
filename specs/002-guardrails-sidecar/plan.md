# Implementation Plan: Guardrails Sidecar

**Branch**: `002-guardrails-sidecar` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-guardrails-sidecar/spec.md`

## Summary

The guardrails sidecar is a stateless FastAPI service that screens every chat turn that touches the LLM. Two endpoints — one for the incoming visitor message, one for the LLM's draft response — apply a fixed set of **platform rails** (prompt-injection refusal, jailbreak detection, cross-tenant data refusal, PII redaction) plus the requesting tenant's configured **tenant rails** (allowed topics, refusal persona/tone, escalation triggers). Every call returns either `pass` (possibly with redacted payload) or `block` (with `rule_name` and a closed-vocabulary `action`). Internal errors collapse to `block` with `rule_name="engine_error"` and `action="fallback_response"` — fail-closed is the rule. Vault-issued service credential required on every request. Per-evaluation OpenTelemetry span carries tenant, endpoint, decision, rule, latency, and rails ruleset version; redaction recognizer names are recorded but matched values are never. p95 evaluation latency under 100ms.

The implementation uses **NeMo Guardrails** as the rail engine for the platform-rail logic, **Microsoft Presidio** (analyzer + anonymizer) with custom recognizers for PII redaction (including project-specific recognizers for hosted-LLM API key prefixes), and **OpenTelemetry SDK** for tracing. Vault credential is fetched at boot via `hvac` and validated on every request via a FastAPI dependency. Tenant configuration is supplied by the backend on each call and treated as well-formed (validation is upstream in the admin app).

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: FastAPI (HTTP surface), NeMo Guardrails (rails engine for prompt-injection / jailbreak / cross-tenant rails), Microsoft Presidio analyzer + anonymizer (PII detection and redaction), `hvac` (Vault client at boot), `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi` (tracing), `pydantic` v2 (request/response schemas), `pyyaml` (rails config loading), `uvicorn` (ASGI server).

**Excluded by Principle I**: `torch`, `transformers`, `jupyter`, `notebook`, `ipykernel`, `accelerate`, `bitsandbytes`, `datasets`, `huggingface_hub`, `tensorflow`. Presidio's default NLP backend (`spacy` with `en_core_web_sm`) is acceptable in principle but adds image weight — verify final image stays under 500 MB. If it does not, swap to Presidio's pattern-only mode (no spaCy) and rely on regex recognizers only.

**Storage**: None. The sidecar is stateless. Tenant configuration is supplied in the request body on every call; the rails ruleset and recognizer set are baked into the deployed image. No database, no cache, no on-disk scratch space.

**Testing**: `pytest` + `httpx.AsyncClient` against a TestClient instance of the FastAPI app. Red-team probe sets (`evals/security/injection_cases.json`, `evals/security/cross_tenant_cases.json`) are replayed in CI by `security-gates.yml`. Redaction probe-string tests (Principle IX) live in `backend/tests/test_redaction.py` and assert absence of unique probe strings in the actual log files, trace exports, and downstream payloads — not in mocked sinks.Redaction probe strings are defined in evals/security/redaction_probes.json and consumed only by backend/tests/test_redaction.py. The CI workflow security-gates.yml invokes pytest against this file; there is no separate redaction runner.

**Target Platform**: Linux container, deployed via `docker-compose.yml` next to `backend`, `modelserver`, and the admin app. Built from `guardrails/Dockerfile`.

**Project Type**: web-service (sidecar). Internal-only — not exposed to visitors directly; reachable from `backend` over the docker-compose network.

**Performance Goals**: p95 evaluation latency under **100 ms** per call (both `/check/input` and `/check/output`), measured under realistic concurrency that matches expected production chat-turn rate. p99 under 200 ms. Cold-start under 5 s so a container restart does not noticeably stall the chat path.

**Constraints**:
- Container image total transitive size under **500 MB** (Principle I).
- Fail-closed on any internal exception — no silent pass path under any failure mode (Principle VI).
- No PII (matched values) in any log line, trace span, or response that leaves the sidecar (Principle IX).
- Vault credential MUST be fetched at boot and validated on every request; service MUST refuse to start if the credential cannot be fetched (Principle V).
- Rails ruleset version is a deployed-image attribute; recorded on every span (Principle VII).

**Scale/Scope**: Every chat turn that reaches the LLM produces exactly two sidecar calls (one input, one output). For the slice's expected load (4-person demo project), this is at most a few requests per second at peak, but the sidecar is built so a single instance can absorb low-hundreds-rps spikes without breaching the p95 target.

## Constitution Check

The Concierge Models / Security / Guardrails slice constitution (`.specify/memory/constitution.md`, v1.0.0) has ten principles. Each is evaluated below. **All ten gates pass** for this design.

### I. Lean Serving Containers — **PASS**

- `guardrails/pyproject.toml` will list only the production dependencies named in Technical Context. None of the banned packages (`torch`, `transformers`, `jupyter`, `notebook`, `ipykernel`, `accelerate`, `bitsandbytes`, `datasets`, `huggingface_hub`, `tensorflow`) appear.
- `guardrails/Dockerfile` builds from `python:3.11-slim`, installs only the pinned dependencies, and copies the `app/` and `config/` trees. No training tools.
- CI image-size job (part of Charbel's `ci.yml`) MUST be green for the `guardrails` image; the recorded size goes in the PR description.
- **Open risk**: Presidio + spaCy `en_core_web_sm` can push image size near the 500 MB ceiling. **Mitigation**: measure first; if over budget, drop spaCy and use Presidio's pattern-only mode (the platform-rail recognizers we need — email, phone, credit card, SSN, generic bearer token, hosted-LLM API key prefixes — are all regex-recognizable without an NLP backend).

### II. Artifact Integrity — The sidecar loads no model files (.onnx, .pkl, .joblib, tokenizers), but the rails configuration files under guardrails/config/*.yaml are behavior-defining artifacts: changing them changes what messages pass or block. They get the same integrity treatment as a model artifact. - A Docker build step computes the SHA-256 hash of the canonical concatenation of config/rails.yaml, config/jailbreak_rules.yaml, config/cross_tenant_rules.yaml, and config/pii_redaction.yaml, and writes it into app/version.py as RAILS_CONFIG_HASH alongside RAILS_VERSION. - At boot, app/main.py recomputes the hash from the on-disk config files and compares against RAILS_CONFIG_HASH. On mismatch, the service logs the expected and actual hashes and exits non-zero. The sidecar refuses to serve a single request against an unverified config set. - RAILS_CONFIG_HASH is recorded in guardrails/RAILS_CARD.md along with the build date and the git SHA that produced the configs. If a future revision grows a learned classifier model alongside the rails configs, the same verification path extends to it.

The sidecar loads no model artifacts (`.onnx`, `.pkl`, `.joblib`, tokenizers). The rails configuration files under `guardrails/config/*.yaml` are code-equivalent (committed to git, reviewed as code) and the rails-ruleset version recorded on each span is derived from their committed content hash at build time. No boot-time SHA-256 verification is required because there is nothing fetched separately.

If a future revision of the sidecar grows a model artifact (e.g., a learned jailbreak classifier), this principle applies in full and the boot path must be updated to verify hashes against a `model_card.md`.

### III. Three-Model Bake-Off — **N/A for this service**

No intent classifier is shipped from this service. The intent classifier lives in `modelserver/` and is governed by its own spec (`specs/001-classifier-service/spec.md`).

### IV. Every Decision Backed by a Number — **PASS, with deliverables**

The following numeric decisions for this service MUST land in `deliverables/DECISIONS.md` with a measurement methodology, a source data set, and a link to the eval script that produced the number:

| Decision | Number | Source |
|----------|--------|--------|
| Sidecar p95 latency budget | 100 ms (both endpoints) | Measured by `evals/security/latency_probe.py` against a TestClient run at expected concurrency |
| Sidecar p99 latency budget | 200 ms (both endpoints) | Measured by `evals/security/latency_probe.py` against a TestClient run at expected concurrency |
| Platform-rail block recall on red-team probe set | ≥ recorded threshold per probe category | Measured by `evals/security/red_team_tests.py` against `evals/security/injection_cases.json` and `evals/security/cross_tenant_cases.json` |
| Platform-rail false-positive rate on benign-control set | ≤ recorded threshold | Measured by `evals/security/red_team_tests.py` against a committed benign control set |
| PII redaction recall (per recognizer) | ≥ recorded threshold | Measured by `evals/security/redaction_probes.py` against a committed labeled set |
| PII redaction precision (per recognizer) | ≥ recorded threshold | Same |
| Container image size | < 500 MB | CI `image-size` job for the `guardrails` image |

Qualitative claims do not appear in the DECISIONS row. "Good enough" is not a number.

### V. Service-to-Service Auth Is Mandatory — **PASS**

- Vault KV path — TBD with Owner Mohammad. If the fetch fails, the service raises and uvicorn exits non-zero; a structured log line names the missing path.
- A FastAPI dependency `require_service_credential(authorization: str = Header(...))` runs on every request to both `/check/input` and `/check/output`. The dependency compares against the boot-loaded credential in constant time and raises `HTTPException(status_code=401)` with a fixed body — no information about why the credential failed. (No `WWW-Authenticate` realm hint either.)Constant-time comparison should specify hmac.compare_digest so the implementer doesn't roll their own.
- Network reachability over docker-compose is **not** treated as authentication. The dependency runs even on calls from `backend`.

### VI. Fail-Closed Defaults — **PASS**

- `validators.py` wraps every rail evaluation in a `try` whose `except` returns `EvaluationResponse(decision="block", rule_name="engine_error", action="fallback_response")` and emits a `guardrail.fail_closed` metric counter plus a structured log line. The metric and log line carry `tenant_id`, `endpoint`, and the exception class name (but never the exception message — which can echo input).
- Tenant-config-fetch errors (when the rails layer attempts to consume `tenant_config` and the structure is unexpected — defensive only; per Principle X, validation lives in the admin app) produce `rule_name="config_error"`, same `action="fallback_response"`.
- Tenant-config-absent (caller did not supply tenant rails for that tenant at all) is **not** an error: it is the "no tenant rails configured" case and platform rails still apply. This is the only branch that distinguishes "config not present" from "config malformed", and the test suite exercises both.
- Spec FR-009 captured this requirement; SC-005 captures its observable property in production. Every fail-closed return path emits a counter so fail-closed events are observable, not silent (Principle VI tail clause).

### VII. Tracing From Commit One — **PASS**

- `opentelemetry-instrumentation-fastapi` instruments every request automatically. The handler body adds attributes: `tenant_id`, `guardrails.endpoint` ("input" or "output"), `guardrails.decision` ("pass" or "block"), `guardrails.rule_name` (when blocked), `guardrails.latency_ms`, `guardrails.rails_version`.
- On redaction, a child span `guardrails.redaction` carries `redaction.recognizers_fired` (a list of recognizer names) and `redaction.match_count` (a count). It does **not** carry the matched values, the redacted ranges, or any substring of the original text.


### VIII. Security CI Gate Is Non-Negotiable — **PASS**

- `.github/workflows/security-gates.yml` (Jana-owned) MUST stand up the `guardrails` container alongside `backend` and replay every probe in `evals/security/*.json`. This already aligns with the constitution.
- Day-1 probe placeholders exist in `evals/security/injection_cases.json` and `evals/security/cross_tenant_cases.json`. This plan adds, in tasks: a third probe file `evals/security/redaction_probes.json` that injects probe strings into requests and asserts they do not appear in the sidecar's log file, trace export, or returned payload (Principle IX's mechanism applied to this service).
- No probe weakening, no `continue-on-error`, no deletion is permitted on PRs touching this slice.

### IX. Redaction Is Provable, Not Asserted — **PASS**

- The redaction probe suite injects a unique random string (e.g., `__PROBE_<uuid>__`) into a request payload, then **after** the request completes scans:
  - the actual sidecar container log file (`docker logs guardrails`),
  - the actual OTel trace export (e.g., the OTLP collector's persisted output for the test run),
  - the returned response payload received by the backend test client.
- The assertion is that the probe string **does not appear** in any of these. No mocked logger, no mocked tracer, no assertion-on-return-value-only.
- Tests live in `backend/tests/test_redaction.py` (Jana-owned per `structure.md`); they run in `security-gates.yml`.
- The probe set covers every recognizer: email, phone, credit card, SSN, generic bearer token, `sk-ant-…` (Anthropic API key), `sk-…` (OpenAI API key).

### X. Spec Before Code — **PASS**

- `specs/002-guardrails-sidecar/spec.md` exists (this feature). The implementation plan in this file is its companion.
- All implementation work lands in files Jana owns per `structure.md`: `guardrails/`, `evals/security/`, `.github/workflows/security-gates.yml`. No edits to files owned by Ali, Mohammad, or Charbel.

### Gate result

All ten gates pass. The Complexity Tracking section below is empty — no constitution violation needs a justification.

## Project Structure

### Documentation (this feature)

```text
specs/002-guardrails-sidecar/
├── spec.md                          # Feature specification (already written)
├── plan.md                          # This file (/speckit-plan output)
├── research.md                      # Phase 0 output — rail-engine choice, recognizer choice, latency strategy
├── data-model.md                    # Phase 1 output — request/response entities and internal vocab
├── quickstart.md                    # Phase 1 output — how to bring the sidecar up locally
├── checklists/
│   └── requirements.md              # /speckit-specify output
└── tasks.md                         # Phase 2 output — /speckit-tasks (NOT created by /speckit-plan)
```

### Source Code (repository root)

The sidecar lives under `guardrails/` per `structure.md`. The layout below mirrors that ownership map exactly; nothing here moves files between owners.

```text
guardrails/
├── Dockerfile                          # python:3.11-slim, no torch/transformers (Principle I)
├── pyproject.toml                      # FastAPI, NeMo Guardrails, Presidio, OTel, hvac, pydantic v2
├── app/
│   ├── main.py                         # FastAPI app, Vault boot fetch, OTel setup, route registration
│   ├── validators.py                   # Rail evaluation orchestrator: platform rails + tenant rails, fail-closed wrapper
│   ├── deps.py                         # FastAPI deps: require_service_credential, get_rails_engine, get_redactor
│   ├── rails_engine.py                 # NeMo Guardrails wrapper: prompt-injection, jailbreak, cross-tenant rules
│   ├── redaction.py                    # Presidio analyzer+anonymizer with custom recognizers (sk-ant-, sk-)
│   ├── schemas.py                      # Pydantic v2 models: EvaluationRequest (input/output), EvaluationResponse, TenantConfig
│   ├── telemetry.py                    # OTel span attribute helpers; redaction-safe logging helper
│   ├── version.py                      # rails_version constant — built from config/ content hash at build time
│   └── __init__.py
└── config/
    ├── rails.yaml                      # NeMo rails composition entrypoint
    ├── jailbreak_rules.yaml            # Known jailbreak frames (DAN, alter ego, hypothetical evil, encoded payload)
    ├── cross_tenant_rules.yaml         # Cross-tenant reference detection rules
    └── pii_redaction.yaml              # Presidio recognizer set, including custom recognizers

backend/
└── app/
    ├── services/
    │   └── guardrail_service.py        # (Jana-owned) HTTP client for the sidecar; called from middleware
    ├── middleware/
    │   ├── guardrails.py               # (Jana-owned) wires guardrail_service into the request path on chat turns
    │   └── redaction.py                # (Jana-owned) — handles backend-internal sinks the sidecar does not see:
                                        #   structured log output, OTel span attributes set by backend handlers,
                                        #   FastAPI default error response bodies, and escalation summary fields.
                                        #   Lead-write fields (email, phone, name, company) are legitimate PII
                                        #   captures and pass through unchanged; free-text fields (message, intent)
                                        #   are redacted before persistence.
    └── tests/
        ├── test_guardrails.py          # (Jana-owned) end-to-end tests through guardrail_service
        └── test_redaction.py           # (Jana-owned) probe-string tests against real log + trace + payload sinks

evals/
└── security/
    ├── red_team_tests.py               # (Jana-owned) runs injection + cross-tenant probes; called by CI gate
    ├── injection_cases.json            # (Jana-owned) prompt-injection probe set, with expected outcomes
    ├── cross_tenant_cases.json         # (Jana-owned) cross-tenant probe set, with expected outcomes
    ├── redaction_probes.json           # NEW (this feature) — unique probe strings + recognizer expectations
    └── latency_probe.py                # NEW (this feature) — p95 measurement script for DECISIONS.md row

.github/
└── workflows/
    └── security-gates.yml              # (Jana-owned) stands up backend + guardrails + modelserver, runs all probes

deliverables/
├── DECISIONS.md                        # MUST gain the six numeric rows listed in Principle IV section
└── SECURITY.md                         # MUST document the rail set, recognizer set, and fail-closed posture
```

**Structure Decision**: This is **Option 2: Web application** in the plan-template's vocabulary, but with a more specific shape — a **multi-service backend** where the sidecar is a separate FastAPI service called over the internal Docker network by another FastAPI service (`backend`). There is no frontend in this feature. The guardrails sidecar is one of three Python services Jana owns (the other two being the model server, governed by spec 001, and the backend middleware modules under `backend/app/middleware/`, governed at unit-of-change granularity inside `backend/`).

## Complexity Tracking

> Filled only when Constitution Check has unjustified violations.

**Empty.** No constitution violation requires a justification. The image-size risk (Presidio + spaCy approaching 500 MB) is a measurable engineering risk, not a constitution exemption — if the measurement exceeds the budget, the mitigation in §I is to drop spaCy, which keeps Principle I satisfied without amendment.

## Phase 0 — Outline & Research

Output: research.md — documents the closed implementation decisions
for this service, their rationale, the alternatives that were
considered and rejected, and the open risks each decision leaves.

Three decisions, all closed in the spec, are documented in
research.md:

### Decision 1: Rail engine — NeMo Guardrails

Decision: Use NeMo Guardrails as the rail engine for the platform
rails.

Rationale: NeMo is built for the exact problem this sidecar solves
— programmable conversation and topic rails covering prompt
injection refusal, jailbreak detection, and topical control. It is
vendor-neutral on the underlying LLM, so the project's choice of
hosted LLM is independent of the rail layer. Its config-as-YAML
model fits the rails-version hash mechanism required by Principle
II. The architecture mirrors a real production guardrails
deployment.

Alternatives considered and rejected:
- Handwritten LLM-based classifier for each rail category.
  Rejected because it requires building and maintaining a jailbreak
  and injection corpus from scratch — work that does not pay back
  on a 5-day timeline and that NeMo already does.
- Pure regex / pattern matching. Rejected because it cannot catch
  paraphrased jailbreaks or semantic cross-tenant references
  (e.g., "the other client" rather than naming a tenant). Regex
  remains a complement to NeMo for trivial cases, not a
  replacement.

Open risks: NeMo's transitive dependency graph is heavy and pushes
the container image toward the 500 MB ceiling (Principle I).
Mitigated by measuring container size on Day 1 of implementation;
if over budget, evaluate NeMo's extras system to install only the
rail types this project uses.

### Decision 2: PII recognizer — Microsoft Presidio

Decision: Use Microsoft Presidio (analyzer + anonymizer) as the
PII detection and redaction engine. Add custom recognizers for
hosted-LLM API key prefixes (sk-ant-, sk-) and a generic bearer
token recognizer.

Rationale: Presidio is purpose-built for PII detection across the
recognizer set this project needs (email, phone, credit card, SSN,
generic bearer token). Its plugin model supports adding
project-specific recognizers without forking the engine.
Anonymizer operators produce stable placeholders (e.g., <EMAIL>,
<PHONE>, <API_KEY_ANTHROPIC>) which lets downstream telemetry
record what type of value was redacted without recording the value
itself — directly enabling Principle IX.

Alternatives considered and rejected:
- Handwritten regex bank. Rejected because the maintenance burden
  grows with every new recognizer, and Presidio already provides
  validated patterns for the common types. Worth keeping for the
  project-specific custom recognizers (sk-ant-, sk-, bearer tokens),
  but not as the whole engine.
- LLM-based detection (calling a hosted LLM to flag PII). Rejected
  because it adds an external API call to the hot path of every
  chat turn, doubles the latency budget, and creates an external
  dependency on a content-safety surface the team does not control.

Open risks: Presidio's default NLP backend uses spaCy with
en_core_web_sm, which adds roughly 50 MB to the container image.
Mitigated by measuring on Day 1; if over the 500 MB ceiling, drop
spaCy and run Presidio in pattern-only mode. The recognizers this
project actually uses (email, phone, credit card, SSN, bearer
token, API key prefixes) are all regex-recognizable without an NLP
backend, so pattern-only mode is a viable fallback. Recognizers
that would require spaCy (PERSON, LOCATION) are not in the project
recognizer set, so dropping spaCy does not narrow coverage.

### Decision 3: Latency strategy — synchronous in-process evaluation

Decision: Run rail evaluation synchronously in the request
handler, in-process with FastAPI.

Rationale: The p95 latency budget is 100 ms per endpoint. NeMo's
rail evaluation for the rule sets in scope runs in single-digit to
low-tens of milliseconds in-process; the same for Presidio in
pattern-only or small-model mode. There is no headroom for the
latency of a queue hop or a process-pool task dispatch. Fail-closed
behavior is also simpler synchronously — every exception is caught
in the handler and converted to a block decision in the same
response, with no queued-message limbo.

Alternatives considered and rejected:
- Async queue (Celery / Redis Streams) with the backend awaiting a
  result. Rejected because the per-call hop adds 5–20 ms easily,
  halves the p95 budget, and complicates the fail-closed path
  (what is the block decision when the queue is unavailable?).
- Process-pool offload to keep the FastAPI event loop free.
  Rejected because the rail-evaluation calls are themselves
  I/O-light and CPU-light at the per-call scale; there is no
  event-loop starvation to solve. The pool only adds dispatch
  overhead.

Open risks: A burst of concurrent chat turns serializes through
the worker pool of the uvicorn process. Mitigated by running with
the default multi-worker uvicorn configuration in production; if a
single worker becomes a hotspot under realistic concurrency
(measured by evals/security/latency_probe.py), the response is to
add workers, not to move to an async architecture.

There are no NEEDS CLARIFICATION markers in the spec — Phase 0's
research output is short and confirmatory rather than exploratory.

## Phase 1 — Design & Contracts

Prerequisites: `research.md` complete.

Outputs:
- [`data-model.md`](./data-model.md) — Pydantic-style descriptions of `EvaluationRequest (Input)`, `EvaluationRequest (Output)`, `EvaluationResponse`, `TenantConfig`, plus the closed-vocabulary value sets for `decision`, `rule_name`, and `action`, plus the redaction `Recognizer` set.

- [`quickstart.md`](./quickstart.md) — bring the sidecar up locally next to backend + modelserver, hit both endpoints with a valid credential and an invalid credential, observe the spans in the local OTel collector, and run the redaction probe smoke test.
- Pydantic v2 models in `app/schemas.py` are the only source of truth for request/response contracts. FastAPI exposes the schema as OpenAPI at `/openapi.json` automatically; if a YAML file is ever needed for external consumers, it is generated from the running service in a CI step, not maintained as a parallel source.


The Pydantic schemas are derived **directly** from the spec's User Stories 1–7 (block actions, redaction behavior, tenant rails, fail-closed, authentication, observability, latency) and FR-001–FR-015. No new behavior is invented in Phase 1.

### Agent context update

After Phase 1 artifacts land, the plan reference inside the `<!-- SPECKIT START -->` / `<!-- SPECKIT END -->` markers in the root `CLAUDE.md` is updated to point at `specs/002-guardrails-sidecar/plan.md`. (If the markers do not yet exist in `CLAUDE.md`, they are added.)

### Re-evaluation of Constitution Check

After Phase 1 artifacts land, the Constitution Check above is re-run. Two specific things to verify in the re-check:
- The contract schemas do not introduce a path through `/check/input` or `/check/output` that bypasses authentication (Principle V) or that returns a useful body to an unauthenticated caller (Principle V tail).
- The data-model's `EvaluationResponse.block` shape does not carry payload contents on a `block` decision — only `rule_name` and `action`. Returning the original input on a block would defeat the purpose of fail-closed (Principle VI) and could leak under the redaction principle (Principle IX) if the input contained PII. The contracts must enforce this.

Both verifications are written into the Pydantic schemas themselves — a discriminated union between `EvaluationResponsePass { payload }` and `EvaluationResponseBlock { rule_name, action }` — so the re-check is a structural review of the schema rather than a separate audit.

