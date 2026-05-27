# Implementation Plan: Classifier Service

**Branch**: `001-classifier-service` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-classifier-service/spec.md`

## Summary

The classifier service is a lean FastAPI process that exposes one endpoint — `POST /predict` — returning one of five intent classes (`SPAM`, `FAQ`, `CONTACT_LEAD`, `HARD_QUESTION`, `UNKNOWN`) plus a `confidence` in [0, 1]. The backend's router calls it on every visitor message and uses the prediction to keep the bulk of traffic off the LLM agent path. Vault-issued service credential is required on every request. Per-call OpenTelemetry span carries `tenant_id`, `predicted_class`, `confidence`, `latency_ms`, and the SHA-256 of the loaded model artifact. p95 latency under 50 ms for short messages.

The shipped model is selected from three candidates trained offline in Colab and benched on a common held-out set: (a) a **classical sklearn baseline** (TF-IDF + LogReg or GradientBoosting), (b) a **small deep model exported to ONNX**, and (c) an **LLM zero-shot baseline** via a hosted API with a frozen prompt. The choice is committed to `deliverables/DECISIONS.md` with the four-metric comparison required by Principle III (accuracy, p95 latency, artifact size, per-1k-request cost). The shipped artifact is a single file — `modelserver/artifacts/classifier.onnx` (for the deep candidate) or `modelserver/artifacts/classifier.joblib` (for the classical candidate) — pinned by SHA-256 in `modelserver/artifacts/model_card.md`. At boot, the service computes the artifact's SHA-256 and refuses to start if it does not match the model card. A held-out macro-F1 evaluation runs in CI on every PR touching `modelserver/` or `artifacts/` and blocks merges below the recorded threshold.

Inference runs **in-process synchronously** via `onnxruntime` (for ONNX artifacts) or `joblib.load(...)` + a sklearn pipeline (for joblib artifacts). A per-call hard timeout of 200 ms is enforced; if inference exceeds it, the response is `predicted_class=UNKNOWN`, `confidence=0.0`, the call is logged as a timeout, and the span is marked as a degraded prediction (Principle VI + spec FR-009).

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: FastAPI (HTTP surface), `onnxruntime` (ONNX inference) **or** `scikit-learn` + `joblib` (classical inference) — whichever the DECISIONS.md bake-off selects; onnxruntime (if the bake-off winner is the ONNX deep model) or scikit-learn + joblib (if the winner is the classical pipeline) — selected by the DECISIONS.md bake-off and committed to the Dockerfile before image build. The two runtimes never ship together; the image installs only the winner's runtime. Plus `hvac` (Vault client at boot), `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi` (tracing), `pydantic` v2 (request/response schemas), `uvicorn` (ASGI server). For LLM-zero-shot if chosen: the hosted LLM provider's official SDK (e.g., `anthropic` or `openai`) — but selection of this candidate has additional latency/cost implications recorded in DECISIONS.md.

**Excluded by Principle I**: `torch`, `transformers`, `jupyter`, `notebook`, `ipykernel`, `accelerate`, `bitsandbytes`, `datasets`, `huggingface_hub`, `tensorflow`. These live in the Colab training notebooks under `modelserver/training/`, never inside the serving container. The serving image's job is **inference only** against an offline-trained artifact.

**Storage**: None at runtime. The model artifact lives on the container filesystem (copied in at image build), loaded once at boot, held in memory. No database, no cache. Vault credential is fetched once at boot and held in memory.

**Testing**: `pytest` + `httpx.AsyncClient` against a TestClient instance of the FastAPI app, plus a separate `evals/classifier/eval_classifier.py` that computes macro-F1 against the committed held-out set in `evals/classifier/datasets/`. CI gate (`evals.yml` for the F1 gate, `security-gates.yml` for the auth + tenant-isolation checks) wires these into every PR touching `modelserver/` or `artifacts/`.

**Target Platform**: Linux container, deployed via `docker-compose.yml` alongside `backend`, `guardrails`, etc. Built from `modelserver/Dockerfile`.

**Project Type**: web-service. Internal-only — reachable from `backend` over the docker-compose network; never exposed to visitors or other tenants.

**Performance Goals**: p95 latency under **50 ms** for typical visitor messages (broadly, under ~500 chars), measured under realistic concurrency. p99 under 100 ms. Hard per-call timeout 200 ms — above that the call returns the `UNKNOWN`/`0.0` fallback (FR-009). Cold-start under 5 s so a container restart does not noticeably stall the chat path.

**Constraints**:
- Container image total transitive size under **500 MB** (Principle I).
- Model artifact SHA-256 MUST match `model_card.md` at boot or the service exits non-zero (Principle II / spec FR-008).
- Three-model bake-off committed to `DECISIONS.md` before the artifact ships (Principle III / spec assumption + FR-014).
- Vault credential validated on every request; 401 body opaque (Principle V / FR-004).
- Fail-closed on inference timeout, deserialization error, or unexpected exception — return `UNKNOWN`/`0.0`, never a "best-guess" label (Principle VI / FR-009).
- Tenant-agnostic prediction: the same `(message, model_version)` returns the same `(class, confidence)` regardless of `tenant_id` (FR-006 / SC-008).
- p95 latency a recorded number in DECISIONS.md, measured by a committed eval script (Principle IV).

**Scale/Scope**: Every incoming visitor message produces exactly one `/predict` call. For the slice's expected load this is a few rps at peak; the service is built so a single instance can absorb low-hundreds-rps spikes without breaching the p95 target.

## Constitution Check

The Concierge Models / Security / Guardrails slice constitution (`.specify/memory/constitution.md`, v1.0.0) has ten principles. Each is evaluated below. **All ten gates pass** for this design.

### I. Lean Serving Containers — **PASS**

- `modelserver/pyproject.toml` lists only production dependencies: FastAPI, uvicorn, pydantic v2, hvac, opentelemetry-sdk/-instrumentation-fastapi, and one of {`onnxruntime`} or {`scikit-learn`, `joblib`, `numpy`, `scipy`} — depending on which bake-off candidate is selected. None of the banned packages appear.
- `modelserver/Dockerfile` builds from `python:3.11-slim`, installs only the pinned dependencies, and copies the `app/` and `artifacts/` trees. The Colab training notebooks under `modelserver/training/` are **not** copied into the image — they are training-time artifacts checked into git for reviewability, but never installed in the serving container.
- CI image-size job (Charbel's `ci.yml`) MUST be green for the `modelserver` image; the recorded size goes in the PR description.
- **Image-size note**: `onnxruntime` is small (~30 MB wheel). `scikit-learn` + `scipy` + `numpy` is larger but still well within 500 MB. The LLM-zero-shot candidate adds only the provider SDK — small — but its operational cost is recorded in the bake-off (Principle III).

### II. Artifact Integrity — **PASS**

- One artifact ships at a time: `modelserver/artifacts/classifier.onnx` **or** `modelserver/artifacts/classifier.joblib`. Both extensions are committed under `modelserver/artifacts/` (or for very large files, referenced from `artifacts/.manifest` resolving to a content-addressed store — recorded per slice convention).
- `modelserver/artifacts/model_card.md` records the SHA-256, the training data revision, the training script revision, and the intended task (5-class intent classification). The model card lives next to the artifact in the same directory (constitution principle II requirement).
- `modelserver/app/model_loader.py` MUST:
  1. Read the expected SHA-256 from `model_card.md` at process startup.
  2. Compute the SHA-256 of the loaded file on disk.
  3. If the hashes do not match — or if the file is missing/corrupt — log a structured `model_hash_mismatch` line with the expected and actual hashes (truncated, never the full bytes), and call `sys.exit(1)`.
  4. Only after the hash matches, load the artifact into memory.
- The boot path MUST set the listening port **after** model load + hash verification succeed; failure means uvicorn never accepts traffic and the orchestrator restarts the container visibly (spec FR-008 / SC-006).
- For the LLM-zero-shot candidate: the "artifact" is a frozen prompt template + a pinned model identifier (e.g., `claude-sonnet-4-6`). The model card records the SHA-256 of the prompt file and the exact model identifier. There is no on-disk inference artifact in this case; the boot path verifies the prompt-file hash matches the card and exits non-zero on mismatch. The provider's model identifier is treated as part of the artifact — changing it requires a new card and a new DECISIONS.md row.

### III. Three-Model Bake-Off Before Serving — **PASS**

- All three candidates are trained and evaluated under `modelserver/training/`:
  - `train_ml.ipynb` — classical baseline (sklearn pipeline with TF-IDF features + LogReg and GradientBoosting; the better of the two is the classical candidate).
  - `train_dl.ipynb` — small deep model (compact transformer or 1D-CNN, depending on what fits the latency budget after ONNX export) exported via `export_onnx.py`.
  - `evaluate_models.py` — also evaluates the LLM-zero-shot baseline by hitting a hosted API with a frozen prompt and a frozen model identifier.
- `evaluate_models.py` produces the four-metric table required by Principle III: macro-F1 on the held-out set, p95 latency under the service load profile, on-disk artifact size, and per-1k-request operational cost. The script writes the table into `deliverables/EVALS.md` and the chosen winner + justification into `deliverables/DECISIONS.md`.
- The shipping PR MUST link to the DECISIONS.md row that contains the four-metric comparison, link to `evaluate_models.py` as the eval script, and name the test-set revision (commit SHA of `evals/classifier/datasets/`).

### IV. Every Decision Backed by a Number — **PASS, with deliverables**

The following numeric decisions MUST land in `deliverables/DECISIONS.md` with a measurement methodology and a link to the eval script:

| Decision | Number | Source |
|----------|--------|--------|
| Held-out macro-F1 of deployed model | ≥ `eval_thresholds.yaml` threshold | `evals/classifier/eval_classifier.py` against `evals/classifier/datasets/` |
| Per-class precision/recall of deployed model | recorded per class | Same |
| p95 latency budget | 50 ms (typical messages) | `evals/classifier/latency_probe.py` against a TestClient at expected concurrency |
| p99 latency budget | 100 ms (typical messages) | `evals/classifier/latency_probe.py` against a TestClient at expected concurrency |
| Cold-start budget | < 5 s | `evals/classifier/coldstart_probe.py` (NEW — added in this feature) |
| Inference hard timeout | 200 ms | Configured constant in `app/main.py`, exercised by `tests/test_timeout.py` |
| Confidence threshold for UNKNOWN escalation | recorded value | If the chosen model's confidence falls below the threshold, the response is `UNKNOWN`/`0.0`; the threshold is bake-off-derived (FR-014) |
| Bake-off winner justification | recorded | `evaluate_models.py` produces the four-metric table; DECISIONS.md row links it (Principle III) |
| Container image size | < 500 MB | CI `image-size` job for `modelserver` |

"Good enough" is not a number. Qualitative claims do not appear in DECISIONS.md.

### V. Service-to-Service Auth Is Mandatory — **PASS**

- Vault KV path — TBD with Owner Mohammad. Placeholder: `secret/data/modelserver/service_credential` pending his Vault bootstrap commit. Vault credential fetched at boot in `modelserver/app/main.py` via `hvac` reading that path. Fetch failure → log + `sys.exit(1)`.
- A FastAPI dependency `require_service_credential(authorization: str = Header(...))` runs on every `/predict` request. Constant-time compare against the boot-loaded credential; on mismatch raise `HTTPException(status_code=401)` with a fixed body — no information about why the credential failed (FR-004).
- Network reachability over docker-compose is **not** treated as authentication.
- The backend's `backend/app/services/classifier_client.py` (Jana-owned per `structure.md`) attaches the credential via its Vault client on every outbound call.

### VI. Fail-Closed Defaults — **PASS**

- Inference is wrapped in a hard-timeout context (e.g., `asyncio.wait_for(inference_call, timeout=0.200)`). On timeout, exception, deserialization error, or any unexpected internal error, the response is **always** `predicted_class="UNKNOWN"`, `confidence=0.0`.
- "Never the last successful value, never a default best-guess label" — explicitly per the constitution (clause VI for the classifier). The fail-closed branch sets a `classifier.degraded=true` span attribute and emits a `classifier.timeout` / `classifier.engine_error` metric counter so the events are observable, not silent.
- The classifier's UNKNOWN-from-timeout response is structurally identical to UNKNOWN-from-low-confidence except for the `confidence` value: `0.0` is reserved for the timeout-degraded path (spec edge case: "Confidence reported as exactly zero — reserved for the timeout-degraded path"). The orchestrator on the backend side relies on this: confidence > 0 means a "real" UNKNOWN, confidence == 0 means a degraded one.

### VII. Tracing From Commit One — **PASS**

- `opentelemetry-instrumentation-fastapi` instruments every request. The handler body adds span attributes:
  - `tenant_id` (required in `PredictRequest`; absent requests are rejected with 422 before the handler runs, so no span is created for missing-tenant calls).
  - `classifier.predicted_class` (one of the five class names).
  - `classifier.confidence` (float in [0, 1]).
  - `classifier.latency_ms` (float).
  - `classifier.model_hash` (the SHA-256 of the loaded artifact, recorded at boot; constant for the process lifetime; baked into `app/version.py` from the model card at container build time — or computed at boot and cached).
  - `classifier.degraded` (bool — set true only on the timeout-fallback path).
- The model hash on the span is what makes a production prediction reproducible to a specific artifact version (Principle VII / FR-011 / SC-004).

### VIII. Security CI Gate Is Non-Negotiable — **PASS**

- `.github/workflows/security-gates.yml` runs on every PR touching `modelserver/`, `artifacts/`, or `backend/app/services/classifier_client.py`. The gate stands up the `modelserver` container with the test-set artifact and replays:
  - **Auth probes** — calls without credentials, with malformed credentials, with expired credentials; asserts identical 401 bodies (FR-004).
  - **Tenant-agnostic probe** — sends the same message twice with two different `tenant_id` values; asserts identical `(class, confidence)` (SC-008).
  - **Hash-mismatch probe** — swaps the artifact with a known-bad hash; asserts the service refuses to start (FR-008 / Principle II).
- `.github/workflows/evals.yml` (Charbel-owned but referenced here for the gate map) runs `evals/classifier/eval_classifier.py` and fails the build if macro-F1 falls below `eval_thresholds.yaml`. This is the **evaluation gate** (FR-012 / SC-003).
- No probe weakening, no `continue-on-error`, no deletion.

### IX. Redaction Is Provable, Not Asserted — **N/A at this layer**

The classifier does not log message content (the spec says so explicitly: out of scope for PII redaction, which is the backend's redaction middleware + the guardrails sidecar's job). To preserve this property, the classifier MUST:
- **Never** include the visitor's message text in a log line. The handler logs only the structural facts (tenant_id, predicted_class, confidence, latency_ms, model_hash) — not the input string.
- **Never** include the visitor's message text in a span attribute. The `classifier.input.preview` style of debug attribute is forbidden.
- **Never** persist the input. The classifier holds it on the stack for the duration of one request and lets it be garbage-collected after the response is returned.

If at some future point we add explicit redaction inside the classifier (e.g., for some inference-time debugging), Principle IX applies in full and probe-string tests against the actual log/trace/Redis sinks become mandatory. For the v1 shipped here, the design's "never log content" stance keeps the principle from becoming relevant.

### X. Spec Before Code — **PASS**

- `specs/001-classifier-service/spec.md` exists (this feature). This plan is its companion.
- All implementation work lands in Jana-owned files: `modelserver/`, `evals/classifier/`, `backend/app/services/classifier_client.py`, `.github/workflows/security-gates.yml`. No edits to files owned by Ali, Mohammad, or Charbel.

### Gate result

All ten gates pass. The Complexity Tracking section below is empty — no constitution violation needs a justification.

## Project Structure

### Documentation (this feature)

```text
specs/001-classifier-service/
├── spec.md                          # Feature specification (already written)
├── plan.md                          # This file (/speckit-plan output)
├── research.md                      # Phase 0 output — bake-off framing, runtime choice, latency strategy
├── data-model.md                    # Phase 1 output — request/response entities and class vocabulary
├── quickstart.md                    # Phase 1 output — how to bring the classifier up locally
├── checklists/
│   └── requirements.md              # /speckit-specify output
└── tasks.md                         # Phase 2 output — /speckit-tasks (NOT created by /speckit-plan)
```

### Source Code (repository root)

The classifier service lives under `modelserver/` per `structure.md`. The layout below mirrors that ownership map exactly; nothing here moves files between owners.

```text
modelserver/
├── Dockerfile                          # python:3.11-slim, no torch/transformers (Principle I)
├── pyproject.toml                      # FastAPI, uvicorn, pydantic v2, hvac, OTel, {onnxruntime} or {sklearn, joblib}
├── app/
│   ├── main.py                         # FastAPI app, Vault boot fetch, OTel setup, route registration
│   ├── classifier.py                   # Orchestrator: validate input → run inference → wrap timeouts → format response
│   ├── inference.py                    # Backend-specific inference: ONNX path or sklearn-pipeline path; tenant-agnostic
│   ├── model_loader.py                 # Hash-verifies artifact against model_card.md, loads into memory, exits non-zero on mismatch
│   ├── schemas.py                      # Pydantic v2: PredictRequest, PredictResponse, IntentClass enum
│   ├── deps.py                         # FastAPI deps: require_service_credential, get_inference_engine
│   ├── telemetry.py                    # OTel span attribute helpers; structured logging helper (never logs message text)
│   ├── version.py                      # model_hash constant — set at boot from loaded artifact
│   └── __init__.py
│
├── artifacts/
│   ├── classifier.onnx                 # IFF ONNX winner — committed (or content-addressed via artifacts/.manifest)
│   ├── classifier.joblib               # IFF classical winner — committed (or via manifest)
│   └── model_card.md                   # SHA-256, training data revision, training script revision, intended task
│
└── training/                           # NOT copied into the serving image (Principle I)
    ├── train_ml.ipynb                  # Classical baseline (sklearn + TF-IDF)
    ├── train_dl.ipynb                  # Small deep model (training only; ONNX export below)
    ├── export_onnx.py                  # PyTorch/Keras → ONNX export, with sanity-check vs. training-time outputs
    ├── evaluate_models.py              # Runs all three candidates against held-out set → DECISIONS table
    └── datasets/
        ├── train.jsonl                 # Training data — reference only; serving image doesn't include it
        └── README.md                   # Labeling guide, class definitions, dataset revision history

backend/
└── app/
    ├── services/
    │   └── classifier_client.py        # (Jana-owned) HTTP client for the classifier; called from router_service
    └── tests/
        └── test_classifier_client.py   # (Jana-owned) client-side tests (timeout, retry, fail-closed mapping)

evals/
└── classifier/
    ├── eval_classifier.py              # (Jana-owned) macro-F1 against held-out set; called by evals.yml CI gate
    ├── latency_probe.py                # NEW (this feature) — p95 measurement script for DECISIONS.md row
    └── datasets/
        └── test.jsonl                  # Held-out set; the macro-F1 gate runs against this

.github/
└── workflows/
    ├── security-gates.yml              # (Jana-owned) auth + tenant-agnostic + hash-mismatch probes
    └── evals.yml                       # (Charbel-owned in name, references this slice's eval) — macro-F1 gate

eval_thresholds.yaml                    # (Charbel-owned) — holds the held-out macro-F1 threshold for the F1 gate

deliverables/
├── DECISIONS.md                        # MUST gain the seven numeric rows listed in Principle IV section
└── EVALS.md                            # MUST hold the bake-off four-metric table (Principle III)
```

**Structure Decision**: This is **Option 2: Web application** in the plan-template's vocabulary, with the same multi-service-backend shape as the sidecar (spec 002) — a separate FastAPI service called over the internal Docker network by the backend. There is no frontend in this feature.

## Complexity Tracking

> Filled only when Constitution Check has unjustified violations.

**Empty.** No constitution violation requires a justification. The only design risk worth flagging — that the bake-off may select the LLM-zero-shot candidate, which has external-API operational risk on every chat turn — is captured as a DECISIONS.md row (the per-1k-request cost number) under Principle III. The selection is the team's, not the spec's; whichever candidate wins, all ten principles still hold.

## Phase 0 — Outline & Research

Output: [`research.md`](./research.md) — written by this plan.

Three decisions need numeric or design grounding before Phase 1 contracts are stable; each becomes a section of `research.md`:

1. **Bake-off framing** — how to structure the comparison between classical / small-deep-ONNX / LLM-zero-shot so the four-metric DECISIONS.md row is reproducible. Drivers: Principle III (the four metrics), Principle IV (every claim a number), Principle X (spec-before-code constrains what we can defer).
2. **Inference runtime choice** — `onnxruntime` for ONNX vs. `joblib.load(...)` + sklearn pipeline for classical, with a clean dispatch in `inference.py` that does not branch in the hot path. Drivers: latency budget (50 ms p95), Principle I (image size), Principle VI (fail-closed semantics on inference errors).
3. **Confidence threshold for the UNKNOWN escalation** — how to derive the threshold from the held-out set so that messages the model can't confidently place fall into `UNKNOWN` rather than a low-confidence "best guess". Drivers: spec User Story 1 acceptance scenario 5 ("the response is the explicit unknown class rather than a low-confidence guess"), Principle IV.

For each decision, `research.md` records: the decision, the rationale tied to constitution principles or spec requirements, the alternatives considered and why they were rejected, the open risks the decision leaves on the table.

There are no `NEEDS CLARIFICATION` markers in the spec — Phase 0 is shorter than usual.

## Phase 1 — Design & Contracts

Prerequisites: `research.md` complete.

Outputs:
- [`data-model.md`](./data-model.md) — Pydantic-style descriptions of `PredictRequest`, `PredictResponse`, the closed `IntentClass` vocabulary, the `model_hash` invariant, and the timeout-degraded response shape.
- [`quickstart.md`](./quickstart.md) — bring the classifier up locally next to the backend, hit `/predict` with a valid credential and an invalid credential, observe the spans (including `classifier.model_hash`), trigger the timeout-degraded path, and confirm tenant-agnostic behavior with two different `tenant_id`s.
- Pydantic v2 models in `app/schemas.py` are the only source of truth for request/response contracts. FastAPI exposes the schema as OpenAPI at `/openapi.json` automatically; if a YAML file is ever needed for external consumers, it is generated from the running service in a CI step, not maintained as a parallel source.

The Pydantic schemas are derived **directly** from the spec's User Stories 1–6 (route, auth, observe, fail loud / fail graceful, eval gate, tenant-agnostic) and FR-001..FR-014. No new behavior is invented in Phase 1.

### Agent context update

After Phase 1 artifacts land, the plan reference inside the `<!-- SPECKIT START -->` / `<!-- SPECKIT END -->` markers in `CLAUDE.md` is updated to point at `specs/001-classifier-service/plan.md`.

### Re-evaluation of Constitution Check

After Phase 1 artifacts land, the Constitution Check above is re-run. Three specific things to verify in the re-check:

- The `PredictResponse` schema does not let the classifier return a payload that includes the original `message` text or any substring of it. The response body carries `predicted_class`, `confidence`, and `model_hash` only. (Principle IX-relevant, even though redaction isn't this service's job — the classifier must not become a sink for content it shouldn't be storing.)
- The contract for `200 timeout-degraded` is structurally indistinguishable from a regular `200 UNKNOWN` response **except** that `confidence` is exactly `0.0`. The contract MUST document this reserved meaning so the backend can rely on it (spec edge case "Confidence reported as exactly zero").
- `model_hash` MUST be required on every response — including the timeout-degraded one — so SC-004 ("100% of authenticated prediction calls are reproducible to a specific model artifact") holds without exception.

All three properties are written into the Pydantic schemas themselves (`required` lists + an explicit comment on the 0.0 confidence reservation), so the re-check is a structural review of the schema rather than a separate audit.
