<!-- Owner: Jana -->

# Roadmap — Jana

**Slice:** Models, security & guardrails.

Append-only. End-of-day notes go at the bottom under "Daily log."
Phases tick from top to bottom; finished items get `[x]` with the
PR link or commit SHA in the trailing parenthesis.

---

## Phase 0 — Specs & constitution (Day 1 morning)

- [ ] Write slice constitution via `/speckit.constitution`
- [x] Write classifier service spec via `/speckit.specify`
- [x] Write guardrails sidecar spec via `/speckit.specify`
- [ ] Review specs with at least one other owner before any code lands

## Phase 1 — Skeleton & tracing (Day 1)

Goal: the backend can call both services over authenticated HTTP before
any real logic exists. Tracing is live from this commit — not added later.

- [x] `modelserver/` — FastAPI app with `/health` (stub) and `/predict` (stub returning UNKNOWN)
- [x] `guardrails/` — FastAPI app with `/health` (stub), `/check/input` (stub pass), `/check/output` (stub pass)
- [x] `hvac` wired into both services — fetch service credential from Vault at boot, refuse to start without it
- [ ] `backend/app/services/tracing_service.py` — OpenTelemetry setup, tenant_id on every span
- [ ] `backend/app/utils/logging.py` — structured logging, no PII in log lines by default
- [ ] `backend/app/utils/metrics.py` — request counters and latency histograms
- [x] `backend/app/services/classifier_client.py` — HTTP client stub (calls `/predict`, returns UNKNOWN until real model lands)
- [x] `backend/app/middleware/guardrails.py` — middleware stub (calls sidecar, passes through until real rails land)
- [x] `.github/workflows/security-gates.yml` — pipeline skeleton with 2–3 stub probes; gate exists from Day 1
- [x] `evals/security/injection_cases.json` — 3 placeholder injection probes
- [x] `evals/security/cross_tenant_cases.json` — 3 placeholder cross-tenant probes
- [ ] Verify: `docker compose up` shows both new services healthy alongside the rest of the stack
- [ ] Verify: a call to `/predict` without a Vault credential returns 401, not a prediction

## Phase 2 — Classifier: train, bake-off, export (Day 2 morning/afternoon)

Goal: one model artifact committed to the repo, hash pinned in model card,
model server serving real predictions.

- [x] `modelserver/training/train_ml.ipynb` — classical baseline: TF-IDF + LogReg and GradientBoosting, macro-F1 on held-out set
- [x] `modelserver/training/train_dl.ipynb` — small DL model (BiLSTM or compact transformer), same held-out set
- [ ] LLM zero-shot baseline in `evaluate_models.py` — structured output via hosted API, same held-out set
- [x] `modelserver/training/evaluate_models.py` — comparison table: macro-F1, per-class F1, p95 latency, artifact size, cost estimate
- [x] `modelserver/training/export_onnx.py` — export DL winner to ONNX (if DL wins); classical winner serialised via joblib otherwise
- [x] `modelserver/artifacts/model_card.md` — SHA-256 of shipped artifact, training date, dataset version, threshold used, decision justification
- [ ] `modelserver/artifacts/classifier.onnx` or `classifier.joblib` — the shipped artifact
- [x] `modelserver/app/model_loader.py` — load artifact at boot, verify SHA-256 against model card, exit non-zero on mismatch
- [x] `modelserver/app/classifier.py` — inference logic: predict class + confidence, enforce hard timeout, return UNKNOWN on timeout
- [x] `modelserver/app/inference.py` — request parsing, tenant_id extraction, OTel span emission
- [x] `modelserver/app/schemas.py` — Pydantic request/response schemas (tenant_id, message, predicted_class, confidence)
- [x] Replace stub `/predict` with real inference; add timeout-degraded path
- [x] `DECISIONS.md` — model bake-off section: three candidates, three numbers (F1 / latency / size), one decision, one defence
- [ ] Verify: classifier image still under 500MB, no torch in final image

## Phase 3 — Redaction middleware (Day 2 afternoon)

Goal: a pasted API key never appears in any downstream surface. Proven
by reading real log files and real trace exports, not by mocking.

- [x] `backend/app/middleware/redaction.py` — Presidio analyser + anonymiser, custom recognisers for `sk-ant-`, `sk-`, bearer tokens
- [ ] spaCy model download (`en_core_web_sm`) wired into backend Dockerfile build step
- [ ] `backend/app/services/redaction_service.py` — redaction logic callable from middleware and from tests
- [x] `backend/tests/test_redaction.py` — each recogniser tested; fake API key probe verified absent from log file, trace export, and Redis dump after a request
- [x] `SECURITY.md` — redaction section: recogniser list, provable-not-asserted guarantee, test evidence

## Phase 4 — Guardrails sidecar: real rails (Day 3)

Goal: platform rails active on every evaluation, tenant rails wired from
config, fail-closed on any internal error.

- [x] `guardrails/config/rails.yaml` — NeMo Colang base config
- [x] `guardrails/config/jailbreak_rules.yaml` — known jailbreak patterns (alter ego, DAN, encoded payloads, hypothetical framings)
- [x] `guardrails/config/cross_tenant_rules.yaml` — cross-tenant reference detection
- [x] `guardrails/config/pii_redaction.yaml` — PII patterns mirroring backend recognisers
- [x] `guardrails/app/validators.py` — tenant rail enforcement: allowed topics, persona/refusal tone, escalation triggers
- [x] `guardrails/app/main.py` — replace stubs with real evaluation; fail-closed on engine error; tenant-config-absent path still runs platform rails
- [x] `backend/app/services/guardrail_service.py` — replace stub with real HTTP calls to sidecar, handle block actions
- [x] `backend/app/middleware/guardrails.py` — replace stub with live guardrail_service calls on every chat turn
- [x] `backend/tests/test_guardrails.py` — one test per platform rail category (injection, jailbreak, cross-tenant, PII); tenant rail tests (on-topic pass, off-topic block, escalation trigger); fail-closed test (engine error → block, config-absent → platform rails only)
- [ ] `admin/pages/guardrails_config.py` — tenant rails config page (coordinate with Charbel; he owns the page shell, Jana owns the schema and validation logic)
- [x] `SECURITY.md` — guardrails section: platform rail list, tenant rail config schema, fail-closed guarantee, service-credential story

## Phase 5 — Security CI gate: grow probe sets, isolation tests (Day 4)

Goal: the security gate is real, not symbolic. Every probe that should
fail does fail, and that proof is in CI on every PR.

- [x] `evals/security/injection_cases.json` — grow to ≥15 injection probes covering known patterns
- [x] `evals/security/cross_tenant_cases.json` — grow to ≥15 cross-tenant probes covering reference, extraction, and system-prompt leak attempts
- [x] `evals/security/red_team_tests.py` — test runner: sends each probe, asserts block decision, reports which probes passed unexpectedly
- [ ] `backend/tests/test_tenant_isolation.py` — end-to-end two-tenant scenarios (with Mohammad): Tenant A request must not return Tenant B data through any of Jana's surfaces (classifier, guardrails, redaction logs, traces)
- [x] `.github/workflows/security-gates.yml` — replace stubs with real probe runner; gate blocks merge on any unexpected pass
- [x] `evals/classifier/eval_classifier.py` — macro-F1 evaluation on held-out set
- [x] `evals/classifier/datasets/` — commit held-out labelled dataset
- [ ] `.github/workflows/evals.yml` (coordinate with Charbel) — classifier eval gate wired in, threshold read from `eval_thresholds.yaml`
- [ ] `scripts/delete_tenant.py` (with Mohammad) — verify Jana-owned surfaces (embeddings, session traces, redaction logs, security probe logs) are fully purged on tenant deletion
- [x] `SECURITY.md` — threat model complete: trust boundaries, attack surface, red-team coverage, deletion guarantees

## Phase 6 — Polish & demo (Day 5)

- [ ] All CI gates green: security-gates, evals (classifier F1), smoke-test
- [ ] `DECISIONS.md` — model choice section final: F1 / latency / artifact size / cost table, one-paragraph defence
- [ ] `modelserver/artifacts/model_card.md` — final: SHA-256, dataset version, threshold, training date
- [ ] `SECURITY.md` — final: all sections complete, no TBD markers
- [ ] `RUNBOOK.md` — Jana's section: how to rotate service credentials, how to redeploy a new model artifact, how to add a new guardrail probe
- [ ] Rehearse demo answer for: *"How do you prove Tenant A cannot see Tenant B's data?"* — your probes in `red_team_tests.py` are the proof; know the numbers

---

## Daily log

### Tue 2026-05-26

- [pending]
