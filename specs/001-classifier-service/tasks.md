# Tasks: Classifier Service

**Input**: Design documents from `/specs/001-classifier-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Test tasks ARE included — the spec and plan require pytest coverage (timeout, auth-opaque-401, tenant-agnostic, hash-mismatch boot drill, malformed-request 422), the held-out macro-F1 evaluation, and the `security-gates.yml` + `evals.yml` CI probes. Constitution Principles VI, VIII, and X make these non-optional.

**Organization**: Tasks are grouped by user story (US1..US6) so each story can be implemented, demoed, and tested independently. Setup + Foundational tasks (Phases 1–2) gate all stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6). Setup, Foundational, and Polish tasks have no story label.
- File paths in every task; no vague descriptions.

## Path Conventions

This is a **web-service** layout per `plan.md` "Project Structure". All paths below are relative to the repository root and exactly match the ownership map in `structure.md` — every task touches a Jana-owned file (`modelserver/`, `evals/classifier/`, `backend/app/services/classifier_client.py`, `.github/workflows/security-gates.yml`, plus the four-metric rows added to `deliverables/DECISIONS.md` and `deliverables/EVALS.md`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency wiring for the classifier service.

- [X] T001 Add production dependencies to `modelserver/pyproject.toml` per plan.md "Primary Dependencies" — `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `hvac`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp`. Pin all versions. Banned packages (`torch`, `transformers`, `jupyter`, `notebook`, `ipykernel`, `accelerate`, `bitsandbytes`, `datasets`, `huggingface_hub`, `tensorflow`) MUST NOT appear in either `[project.dependencies]` or any extra (Principle I).
- [X] T002 [P] Add dev dependencies under `[project.optional-dependencies].dev` in `modelserver/pyproject.toml` — `pytest`, `pytest-asyncio`, `httpx`, `freezegun` — for unit/integration tests. Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`.
- [X] T003 [P] Configure `ruff` + `mypy` in `modelserver/pyproject.toml` under `[tool.ruff]` and `[tool.mypy]` (strict for `app/`). No new linter config files at the repo root.
- [X] T004 [P] Add a standalone `evals/classifier/pyproject.toml` declaring `scikit-learn`, the chosen runtime (`onnxruntime` or `joblib`), `pytest`, and `numpy`. The eval scripts are installable independently so the CI macro-F1 gate does not need to install the full modelserver stack. Keep eval deps out of the serving image.
- [X] T005 Update `modelserver/Dockerfile` to install only the pinned production deps from `pyproject.toml`, copy `app/` and `artifacts/` into the image, and explicitly NOT copy `training/` (Principle I, plan.md "Structure"). Base image `python:3.12-slim` (scaffold uses 3.12; plan.md still says 3.11 — noted, follow-up to align plan). Document the < 500 MB image-size assertion as a comment referencing the CI gate.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schemas, model-loader, telemetry, and app skeleton — every user story depends on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Implement Pydantic v2 schemas in `modelserver/app/schemas.py` — `IntentClass` (Literal of the five values), `PredictRequest`, `PredictResponse` (model_hash pattern `^[0-9a-f]{12}$` per data-model.md & shared-schemas.yaml — tasks.md's 64-hex was a typo against the authoritative contracts; recorded here as a follow-up to reconcile), `UnauthenticatedResponse`.
- [X] T007 [P] Define `InferenceBackend` Protocol in `modelserver/app/inference.py` — and the three concrete backends (OnnxBackend, SklearnBackend, HostedLlmBackend) folded in here so US1 implementations land in one file (T017–T019 share this file already).
- [X] T008 [P] Implement `modelserver/app/version.py`.
- [X] T009 Implement `modelserver/app/model_loader.py` (key:value parser inside `---` front-matter; logs `model_hash_verified` / `model_hash_mismatch`; `sys.exit(1)` on every failure mode).
- [X] T010 Implement `modelserver/app/telemetry.py` — `set_prediction_attrs` + `structured_log` (defensively strips `message=` kwargs).
- [X] T011 Implement Vault credential bootstrap in `modelserver/app/deps.py` (Vault path `secret/data/modelserver/service_credential` — left as the placeholder, TBD against Mohammad's `infra/vault/policies/` before integration). `MODELSERVER_SERVICE_CREDENTIAL` env override for tests/dev.
- [X] T012 Wire `modelserver/app/main.py` — `create_app()` does load → vault → telemetry init → instrument FastAPI → register `/predict` and `/health`. The 401 exception handler is folded in here (T025 too) so the body shape is byte-stable from the first commit.
- [X] T013 Placeholder `modelserver/artifacts/model_card.md` with the seven required fields (sha256 placeholder = all zeros; will be replaced when the bake-off ships an artifact).

**Checkpoint**: Foundation ready — the service can boot to "ready" with a known artifact, reject all requests with 401 (no /predict logic yet), and emit empty spans. User-story phases can now proceed in parallel.

---

## Phase 3: User Story 1 — Route a routine visitor message (Priority: P1) 🎯 MVP

**Goal**: `POST /predict` returns one of five `IntentClass` values plus `confidence` in [0, 1] for a typical visitor message, deterministically for a given `(message, model_version)`, in well under the chat-turn latency budget.

**Independent Test**: `quickstart.md` steps 1–3 — start the service with a known artifact, hit `/predict` with one representative message per class plus the ambiguous `"hey"` case; assert each response carries a class from the five-set, confidence in [0, 1], and `model_hash` matches `model_card.md`. Repeat each call and assert byte-identical responses (determinism).

### Tests for User Story 1

- [X] T014 [P] [US1] `modelserver/tests/test_predict_happy_path.py` + `tests/fixtures/predict_examples.json` (4 representative examples; one row per class). `model_hash` pattern is `^[0-9a-f]{12}$` per the authoritative shared-schemas.yaml.
- [X] T015 [P] [US1] `modelserver/tests/test_predict_determinism.py` — byte-identical bodies via `resp.content` comparison.
- [X] T016 [P] [US1] `modelserver/tests/test_unknown_threshold.py` — forces UNKNOWN, preserves raw 0.05.

### Implementation for User Story 1

- [X] T017 [US1] `OnnxBackend` in `modelserver/app/inference.py` — single-threaded `ort.InferenceSession`, identity-or-softmax depending on output range.
- [X] T018 [US1] `SklearnBackend` in `modelserver/app/inference.py` — `joblib.load` + `predict_proba`; falls back to pipeline's own `classes_` order.
- [X] T019 [US1] `HostedLlmBackend` in `modelserver/app/inference.py` — constructor wired (prompt + identifier); `.predict` raises NotImplementedError until candidate C is selected (orchestrator's fail-closed path engages on accidental selection).
- [X] T020 [US1] Boot-time backend selection lives in `model_loader.load()` (returns the picked backend on `LoadedArtifact`); `main.py` stamps `app.state.backend` + `app.state.unknown_threshold` from that.
- [X] T021 [US1] Orchestrator in `modelserver/app/classifier.py`. Note: the fail-closed try/except (T032) is wired *here* rather than added later — there was no design reason to ship a US1-only version that re-raises on timeout, and shipping US4's branch in the same change keeps the spec's "Real auth from the first commit of the endpoint" property mirrored ("real fail-closed from the first commit") consistent with Principle VI.
- [X] T022 [US1] `POST /predict` wired in `modelserver/app/main.py` with `Depends(require_service_credential)`. Auth is active from the first commit.

**Checkpoint**: US1 is independently testable — happy-path predictions return well-formed responses, determinism holds, and the threshold-based UNKNOWN forcing works. Real auth is active from the first commit of the endpoint.

---

## Phase 4: User Story 2 — Authenticate every prediction call (Priority: P1)

**Goal**: Every `/predict` call without a valid Vault-issued service credential is rejected with HTTP 401 and a body that does not distinguish missing / expired / malformed credentials.

**Independent Test**: quickstart.md step 5 — three `curl` calls (valid, missing `Authorization`, malformed Bearer); only the valid call returns 200; the two invalid calls return 401 with identical body `{"detail":"unauthenticated"}`.

### Tests for User Story 2

- [X] T023 [P] [US2] `modelserver/tests/test_auth.py` — valid/missing/malformed/wrong-scheme + byte-identical 401 body assertion.

### Implementation for User Story 2

- [X] T024 [US2] `require_service_credential` covers missing header, wrong scheme, and mismatch — all routed through one `_unauthenticated()` HTTPException so failure modes are indistinguishable.
- [X] T025 [US2] `_401_opaque` handler in `modelserver/app/main.py` returns `UnauthenticatedResponse().model_dump()` for every 401, guaranteeing byte-identical bodies.

**Checkpoint**: US2 is independently testable — auth probes pass; the 401 body cannot leak credential-state information.

---

## Phase 5: User Story 3 — Stay observable and traceable (Priority: P2)

**Goal**: Every prediction emits an OTel span carrying `tenant_id`, `classifier.predicted_class`, `classifier.confidence`, `classifier.latency_ms`, `classifier.model_hash`, and `classifier.degraded` (data-model.md §EvaluationSpan).

**Independent Test**: quickstart.md step 6 — issue one prediction, inspect the collector logs, assert the span carries all six attributes and a fresh prediction under a different deployed `model_hash` yields a different `classifier.model_hash` value. `grep` for the literal message text in collector output → expect zero hits.

### Tests for User Story 3

- [X] T026 [P] [US3] `modelserver/tests/test_span_attrs.py` — InMemorySpanExporter captures the classifier span and asserts all six EvaluationSpan attrs (model_hash matches `^[0-9a-f]{12}$` per the contract).
- [X] T027 [P] [US3] `modelserver/tests/test_no_message_in_logs.py` — canary message `CANARY_REDACT_CHECK_99731` must not appear in any log record OR any span attribute.

### Implementation for User Story 3

- [X] T028 [US3] `classifier.classify` calls `telemetry.set_prediction_attrs(...)` on the current span before returning, setting all six EvaluationSpan attributes (including `tenant_id_missing` when `tenant_id is None`).

**Checkpoint**: US3 is independently testable — spans are complete, no message text leaks into logs/spans, model_hash on the span lets any prediction be traced back to a specific artifact (SC-004).

---

## Phase 6: User Story 4 — Fail loudly at boot, gracefully under load (Priority: P2)

**Goal**: (a) On boot, a model-card / artifact hash mismatch (or load error) causes the service to exit non-zero before the listener opens. (b) On any single inference timeout / exception, the response is `(UNKNOWN, 0.0)` with `classifier.degraded=true` on the span.

**Independent Test**: quickstart.md steps 7–8 — (a) replace the artifact with one whose hash doesn't match the card; restart; assert `docker compose ps` shows the container in restart-loop and logs carry a `model_hash_mismatch` line; (b) set `INFERENCE_TIMEOUT_MS=1`, hit `/predict`, assert response is `{"predicted_class":"UNKNOWN","confidence":0.0,"model_hash":"..."}` and span carries `classifier.degraded=true`.

### Tests for User Story 4

- [X] T029 [P] [US4] `modelserver/tests/test_timeout.py` — SlowBackend (>timeout) + RaisingBackend; both produce `(UNKNOWN, 0.0)` and a span with `classifier.degraded=true`.
- [X] T030 [P] [US4] `modelserver/tests/test_validation.py` — parametrized over empty/whitespace/missing-tenant/missing-message; asserts no partial body.
- [X] T031 [P] [US4] `modelserver/tests/test_hash_mismatch_boot.py` — calls `model_loader.load(...)` directly against a `tmp_path` artifact dir; covers happy path, mismatch, missing artifact, truncated file, missing card fields, and extension-type mismatch. Subprocess-driven boot is captured via the SystemExit path (the loader calls `sys.exit(1)`).

### Implementation for User Story 4

- [X] T032 [US4] `classifier.classify` already wraps the `wait_for` in separate `TimeoutError` / general-Exception branches; both set `classifier.degraded=true` and emit the `classifier.timeout` / `classifier.engine_error` events.
- [X] T033 [US4] `PredictRequest.message` carries `min_length=1` + a `field_validator` that rejects whitespace-only strings.

**Checkpoint**: US4 is independently testable — failure modes are visible, never silent; the chat pipeline never stalls on a slow inference.

---

## Phase 7: User Story 5 — Hold a quality bar on every change (Priority: P2)

**Goal**: Every change to `modelserver/` or `modelserver/artifacts/` triggers a held-out macro-F1 evaluation; PR is blocked if F1 falls below `eval_thresholds.yaml`.

**Independent Test**: spec.md US5 — open a PR touching `modelserver/`; assert the eval job runs in CI, prints macro-F1, and the gate fails iff the score is below the threshold.

### Tests for User Story 5

- [X] T034 [P] [US5] `evals/classifier/tests/test_eval_classifier.py` — 4-row hand-computed reference; asserts macro-F1 = 0.7333… within 1e-6.

### Implementation for User Story 5

- [X] T035 [P] [US5] `evals/classifier/eval_classifier.py` — loads via `model_loader.load`, runs over `datasets/test.jsonl`, prints macro-F1 + per-class report as JSON, prints dataset git SHA, exits non-zero on threshold breach.
- [X] T036 [P] [US5] `modelserver/training/evaluate_models.py` — bake-off harness; writes the four-metric table to `deliverables/EVALS.md`. Candidate C is gated on `RUN_CANDIDATE_C` env so an accidental run doesn't bill the hosted provider.
- [X] T037 [P] [US5] `modelserver/training/prepare_data.ipynb` — strip/dedup/stratified-split scaffold; reads `data/raw_merged.csv` (TBD path noted at top), writes the six cleaned splits + `cleaning_metadata.json`.
- [X] T038 [P] [US5] `modelserver/training/train_ml.ipynb` — fits LogReg + GradientBoosting via sklearn Pipeline + TF-IDF, picks the better by val macro-F1, writes `classifier.joblib`, prints SHA-256 for the card.
- [X] T039 [P] [US5] `modelserver/training/train_dl.ipynb` — TinyCNN (hashed char-n-gram → linear → relu → linear) over the strict splits; writes `classifier_dl.pt`.
- [X] T040 [US5] `modelserver/training/export_onnx.py` — exports TinyCNN to ONNX (opset 17), runs a max-abs-diff check vs the torch reference, exits non-zero if drift > 1e-5; prints SHA-256 of the exported file.
- [X] T041a [US5] `evals/classifier/eval_classifier.py` + `evals/classifier/eval_thresholds.yaml` (Jana-side).
- [ ] T041b [US5] **[Coordination — Charbel]** — not included in this Jana commit; Charbel wires the trigger in his PR (per the task's instruction).
- [X] T042 [US5] DECISIONS.md ADR-007.a adds the nine numeric rows + the bake-off summary pointer.
- [X] T043 [US5] EVALS.md "Bake-off Table (Principle III)" subsection — three-row table shape with TBD numbers filled by `evaluate_models.py`.

**Checkpoint**: US5 is independently testable — eval gate runs on PRs (Charbel's T041b), the bake-off table exists, DECISIONS.md has the nine numeric rows.

---

## Phase 8: User Story 6 — Ship one model across every tenant (Priority: P3)

**Goal**: A single artifact serves every tenant; `tenant_id` never reaches `backend.predict(...)`; two requests with the same message and different `tenant_id` return byte-identical `(class, confidence)`.

**Independent Test**: quickstart.md step 4 — send the same message under `tenant-acme` and `tenant-globex`, assert `diff` is empty.

### Tests for User Story 6

- [X] T044 [P] [US6] `modelserver/tests/test_tenant_agnostic.py` — deterministic StubBackend; asserts `r1.json() == r2.json()` across two tenant_ids.

### Implementation for User Story 6

- [X] T045 [US6] Audit comment added at the `tenant_id` extraction site in `classifier.classify`. `inference.py` backends never receive `tenant_id` — the protocol's signature enforces it structurally (`predict(self, message: str)`).
- [X] T046 [US6] `.github/workflows/security-gates.yml` runs the auth, tenant-agnostic, and hash-mismatch probes via pytest. No `continue-on-error`; failure on any probe blocks the build.

**Checkpoint**: All six user stories are independently functional and the security-gate workflow enforces the spec's hard guarantees on every PR.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Wire the classifier into the backend, add the latency/coldstart probes referenced in DECISIONS.md, run the full quickstart, and ship.

- [X] T047 [P] `backend/app/services/classifier_client.py` — `ClassifierClient` with async httpx; maps timeout/non-200 to `(UNKNOWN, 0.0, degraded=True)`. Propagates classifier-side degraded responses via the `degraded` flag.
- [X] T048 [P] `backend/tests/test_classifier_client.py` — httpx MockTransport covers happy path, ReadTimeout, 401, 500, and a classifier-side degraded response.
- [X] T049 [P] `evals/classifier/latency_probe.py` — `--requests` / `--concurrency`; prints p50/p95/p99/mean/max.
- [X] T050 [P] `evals/classifier/coldstart_probe.py` — `docker compose rm` + `up` + poll /health; prints cold_start_s.
- [X] T051 [P] `docker-compose.yml` — added read-only mount of `./modelserver/artifacts` (defense-in-depth). OTel collector not added — left as a coordination item for Charbel (his scaffold; would mix Jana edits with Charbel's CI/CD slice).
- [ ] T052 — quickstart end-to-end run requires a live docker stack and the actual model artifact; not runnable in this session. Hand-off note: run before the Friday demo and update the placeholder rows in DECISIONS.md / EVALS.md with measured numbers.
- [X] T053 Constitution re-check (structural): (1) `PredictResponse` schema has `extra="forbid"` and no `message` field — no echo possible; (2) `classifier.classify` returns `confidence=0.0` only on the `TimeoutError` / general-`Exception` branches; the threshold-forced UNKNOWN path preserves the raw `confidence`; (3) `model_hash` is unconditionally stamped from `version.get_model_hash()` on every `PredictResponse`, including the degraded one.
- [ ] T054 [P] CLAUDE.md does not exist at the repo root — marker update is a no-op. Hand-off: create CLAUDE.md with the SPECKIT markers when first added.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories.
- **User Stories (Phase 3+)**: All depend on Foundational. Within Phase 2, T009 (model_loader) → T012 (main wiring) is the only cross-task dep; the schemas (T006), protocol (T007), version (T008), telemetry (T010), deps (T011) can all run in parallel.
- **US1 (P1)** → **US2 (P1)** → **US3 (P2)** → **US4 (P2)** → **US5 (P2)** → **US6 (P3)** is the *priority* order. Stories themselves are independent (no story imports another's code beyond Foundational); a parallel team can ship them concurrently after Phase 2.
- **Polish (Phase 9)** depends on every user-story phase: classifier_client (T047) needs US1 + US2 working; quickstart run (T052) exercises all six stories.

### User Story Dependencies

- **US1**: Depends on Phase 2 (schemas, model_loader, main skeleton).
- **US2**: Depends on Phase 2 (deps.py) + T022 (the `/predict` route exists). US2 adds the test coverage and the exception handler for the auth dependency that already exists in T022.
- **US3**: Depends on Phase 2 (telemetry) + T022 (so a request can produce a span).
- **US4**: Depends on US1 (a real `classifier.classify` function to wrap) + Phase 2 (model_loader for the hash-mismatch test).
- **US5**: Independent of US1–US4 implementation; only depends on `model_loader` (T009) so the eval script can load the artifact the same way the service does.
- **US6**: Depends on US1 (an actual `/predict` to probe) + US2 (auth is needed to make the security-gate probes representative).

### Within Each User Story

- Tests for the story can be written in parallel with implementation tasks marked [P]; both before merging the story.
- Verify tests fail before implementing — pytest run should turn them red before the implementation tasks turn them green.
- Models / schemas / protocols before orchestrator before endpoint before integration.

### Parallel Opportunities

- All Phase 1 [P] tasks (T002–T004) can run in parallel.
- Phase 2: T006, T007, T008, T010, T011 are all [P] — five files, no cross-deps.
- US1 tests (T014–T016) are [P] across three files; US1 backend implementations (T017, T018) are sequential since they share `inference.py`.
- US3 tests (T026, T027), US4 tests (T029–T031), US5 implementation (T035–T040), Polish (T047–T051, T054) are all [P]-heavy and can be parallelized across team members.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests in parallel (file-disjoint):
Task: "Write happy-path test in modelserver/tests/test_predict_happy_path.py"
Task: "Write determinism test in modelserver/tests/test_predict_determinism.py"
Task: "Write unknown-threshold test in modelserver/tests/test_unknown_threshold.py"

# T017 then T018 sequentially — both edit inference.py:
Task: "Implement OnnxBackend in modelserver/app/inference.py"
Task: "Implement SklearnBackend in modelserver/app/inference.py (sequential after T017)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T005).
2. Complete Phase 2: Foundational (T006–T013) — schemas + model_loader + telemetry + main skeleton.
3. Complete Phase 3: User Story 1 (T014–T022) — orchestrator + the first backend (ONNX or Sklearn, whichever the bake-off names; T019/HostedLlmBackend can be skipped until C is on the table).
4. **STOP and VALIDATE**: Run quickstart.md steps 1–3 against the local container. Hit `/predict` with each class example; confirm well-formed responses and determinism.
5. Demo if ready: this is the MVP — the chat pipeline can now route traffic; auth is enforced from the first commit (US2 adds the test coverage and exception handler).

### Incremental Delivery (Priority Order)

1. Setup + Foundational → foundation ready.
2. Add US1 → quickstart 1–3 green → MVP demo.
3. Add US2 → quickstart 5 green → auth coverage proven.
4. Add US3 → quickstart 6 green → operationally observable.
5. Add US4 → quickstart 7–8 green → safe under failure.
6. Add US5 → CI gate active → safe to evolve.
7. Add US6 → quickstart 4 green → multi-tenant safe.
8. Polish → classifier_client wired into backend, latency/coldstart numbers recorded in DECISIONS.md, full quickstart run on a release-candidate image.

### Parallel Team Strategy

After Phase 2 ships:

- Developer A: US1 + US4 (timeout-fallback fits naturally on top of the orchestrator).
- Developer B: US2 + US3 (auth and telemetry are independent infrastructure surfaces).
- Developer C: US5 (the training notebooks + bake-off harness can run completely in parallel with the serving work).
- US6 + Polish (T047–T054) lands after the others; one developer wires the backend client + the quickstart + the constitution re-check.

---

## Notes

- [P] = different files, no dependencies — safe to parallelize.
- [Story] label maps every task to a specific user story for traceability through the PR review.
- Each user story is a complete vertical slice — implementing it leaves the service functional at that story's bar.
- Tests fail before implementation (TDD-flavored; the spec's "Independent Test" sections are the acceptance criteria).
- Commit after each task or logical group; the security-gates and evals CI workflows run on every PR.
- Stop at any checkpoint to demo independently.
- Avoid: vague tasks, cross-story dependencies that break independence, edits to files owned by Ali/Mohammad/Charbel (every task above touches a Jana-owned path per `structure.md`).
- Constitution gate: if any task here drifts from the ten principles, halt and re-evaluate against `plan.md` §Constitution Check before continuing.
