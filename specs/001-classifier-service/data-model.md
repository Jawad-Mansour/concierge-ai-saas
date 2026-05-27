# Phase 1 — Data Model: Classifier Service

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Contracts**: [`contracts/`](./contracts/)

This document describes the data entities the classifier accepts, returns, and operates on internally. All entities cross the HTTP boundary as JSON; the canonical implementations are Pydantic v2 models in `modelserver/app/schemas.py`. The `IntentClass` enum is a `Literal` so the closed five-class vocabulary is enforced at type-check time and adding a class is a typed, reviewable code change.

## Entities

### `PredictRequest`

Sent by the backend to `POST /predict` for every incoming visitor message.

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `tenant_id` | string | yes | non-empty, length ≤ 64, `[A-Za-z0-9_-]+` | Opaque to the model; used only for tracing and rate-limiting attribution (spec FR-006, Principle VII). MUST NOT influence the prediction. |
| `message` | string | yes | length ≤ 16 KiB | The visitor's incoming message. The latency target applies to "typical" messages (broadly under ~500 chars); longer messages still get a prediction but may exceed the typical-message budget (spec edge case "extremely long message text"). |

**Validation behavior**: A request missing `tenant_id`, missing `message`, or with `message` that is empty/whitespace-only is rejected at FastAPI's Pydantic validation layer with HTTP 422 (spec FR-005 / edge case "Empty or whitespace-only message text"). The `tenant_id_missing=true` span attribute is set when `tenant_id` is absent, per Principle VII.

The request body MUST NOT carry inference hints, model-version pins, or any other client-controlled steering — the classifier is tenant-agnostic and version-pinned to the deployed artifact.

### `PredictResponse`

Returned to the backend. Always HTTP 200 unless the request failed authentication (401) or validation (422).

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `predicted_class` | `IntentClass` | yes | one of the five values | The model's chosen class (or the UNKNOWN fallback). |
| `confidence` | float | yes | 0.0 ≤ confidence ≤ 1.0 | See "Confidence values" below for the reserved meaning of `0.0`. |
| `model_hash` | string | yes | 12-character lowercase hex | Truncated SHA-256 of the loaded model artifact. Constant for the process lifetime. Lets any production prediction be traced back to a specific artifact (spec FR-011 / SC-004). |

**Critical structural property**: `PredictResponse` MUST NOT carry the original message, any substring of it, or any debug "input preview" field. The response is reduced to the three structural facts above. This keeps the classifier from becoming an unintended sink for content it shouldn't be storing (Principle IX-style hygiene, even though redaction itself is out of scope here).

### `IntentClass`

```
Literal["SPAM", "FAQ", "ACCOUNT_OPS", "HARD_QUESTION", "UNKNOWN"]
```

The five-class vocabulary is closed. Adding or removing a class is a model-version change handled through the same evaluation-gated rollout path as any other model update (spec Assumptions, "The five intent classes are stable for the lifetime of the deployed model"). The `Literal` type ensures any new class appears as a typed code diff with a corresponding artifact change.

| Value | Router action | Notes |
|-------|---------------|-------|
| `SPAM` | drop silently | Junk to be dropped without a response. |
| `FAQ` | answer from CMS without LLM | The CMS lookup is the backend's job; the classifier just labels the message as "the kind of thing CMS can answer". |
| `ACCOUNT_OPS` | capture lead | Visitor signaling interest or sharing contact details. |
| `HARD_QUESTION` | escalate to LLM agent | Ambiguous, multi-part, or requires reasoning across sources. |
| `UNKNOWN` | escalate to LLM agent (fallback) | The explicit "don't guess" answer. Two sub-cases distinguished by `confidence` (below). |

### Confidence values

The `confidence` field is in [0.0, 1.0] and is interpreted by the backend as follows:

- **`confidence == 0.0`** is **reserved** for the timeout-degraded path. The classifier returns `(IntentClass.UNKNOWN, 0.0)` if and only if inference exceeded the hard 200 ms timeout, the model raised, or any unexpected internal exception occurred (spec edge case "Confidence reported as exactly zero — reserved for the timeout-degraded path"; spec FR-009; Principle VI). The corresponding span has `classifier.degraded=true`.
- **`confidence > 0.0` with `predicted_class == IntentClass.UNKNOWN`** means the model evaluated normally but `max(predict_proba)` fell below the UNKNOWN-escalation threshold (see `research.md` Decision 3). The router still escalates, but the operator can tell from the trace that the model worked, it just couldn't commit.
- **`confidence > 0.0` with any other class** is a normal confident classification.

The backend's `classifier_client.py` MUST preserve this distinction in whatever log/metric it emits — collapsing `0.0` into "any UNKNOWN" would erase the timeout-vs-low-confidence signal.

### `ModelHash`

A 12-character lowercase hex truncation of the SHA-256 of the loaded model artifact. Computed once at boot in `modelserver/app/model_loader.py`, after the artifact's full SHA-256 has been verified against `model_card.md`. Stored in `modelserver/app/version.py` and read by `telemetry.py` when setting span attributes.

Length 12 (48 bits) is chosen because collisions on the artifact-space we ship are astronomically unlikely and the truncated form is easier to read in trace UIs than the full 64-character hash. The full SHA-256 still appears in `model_card.md` and in the boot-time log line; only the truncated form is on the wire.

## Internal-only entities

### `InferenceBackend` (protocol)

Defined in `modelserver/app/inference.py`. Not a wire entity; it is the seam that lets the bake-off winner be swapped without touching the orchestrator.

```python
class InferenceBackend(Protocol):
    """A single-step, tenant-agnostic predictor."""
    def predict(self, message: str) -> tuple[IntentClass, float]: ...
```

Implementations:

| Implementation | Used for | Source of `confidence` |
|----------------|----------|-------------------------|
| `OnnxBackend` | `classifier.onnx` artifacts | `softmax`-normalized logits from the ONNX session's output tensor; `argmax` → class, `max(softmax)` → confidence |
| `SklearnBackend` | `classifier.joblib` artifacts | `pipeline.predict_proba(...)` row; `argmax` → class, `max(...)` → confidence |
| `HostedLlmBackend` | LLM-zero-shot candidate (if it wins the bake-off) | Provider's structured-output JSON if available; otherwise the harness derives a confidence from logprobs |

Selection happens once at boot from `model_card.md`'s declared artifact type. The orchestrator never branches on backend type in the hot path.

### `EvaluationSpan`

The OpenTelemetry span emitted for each prediction. Not a wire entity; just the set of attributes the implementation must set:

| Attribute | Type | Source |
|-----------|------|--------|
| `tenant_id` | string | Request body. |
| `tenant_id_missing` | bool | True iff request had no `tenant_id` — anomaly path. |
| `classifier.predicted_class` | string | One of the five class names. |
| `classifier.confidence` | float | The returned confidence (including `0.0` for degraded). |
| `classifier.latency_ms` | float | Wall-clock around the orchestrator's `predict` call. |
| `classifier.model_hash` | string | The 12-character `ModelHash`. |
| `classifier.degraded` | bool | True only on the timeout-fallback path. |

No span attribute carries a substring of `message` (research.md cross-cutting confirmation).

### `ModelCard`

The contents of `modelserver/artifacts/model_card.md`. Not a wire entity; it is the source of truth for the boot-time hash verification (Principle II / spec FR-007 / FR-008).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `artifact_filename` | string | yes | Relative to `modelserver/artifacts/`. One of `classifier.onnx`, `classifier.joblib`, `classifier_prompt.txt`. |
| `artifact_type` | `Literal["onnx", "joblib", "hosted_llm_prompt"]` | yes | Drives backend selection. |
| `sha256` | string (64 hex chars) | yes | Full SHA-256 of the artifact file. |
| `training_data_revision` | string | yes | Commit SHA (or content-addressed identifier) of the dataset used to train. |
| `training_script_revision` | string | yes | Commit SHA of the training notebook + export script. |
| `intended_task` | string | yes | Fixed: "5-class intent classification (SPAM/FAQ/ACCOUNT_OPS/HARD_QUESTION/UNKNOWN)". |
| `unknown_threshold` | float | yes | The UNKNOWN-escalation threshold (research.md Decision 3). |
| `hosted_model_identifier` | string \| null | conditional | Required iff `artifact_type=="hosted_llm_prompt"` — the pinned hosted-model identifier (e.g., `claude-sonnet-4-6`). |
| `notes` | string | no | Free text for operator context. |

`model_loader.py` MUST refuse to start if any required field is missing, if `sha256` doesn't match the on-disk file, or — for the hosted-LLM case — if `hosted_model_identifier` is absent.

## State transitions

The classifier is **stateless across requests**. The only persistent state is:
- The active `InferenceBackend` instance (loaded once at boot, immutable for the process lifetime).
- The boot-loaded service credential.
- The `ModelHash` constant.

A single prediction's internal state transitions are:

```
   ┌─────────────────────────┐
   │   request arrives       │
   └─────────────┬───────────┘
                 │
                 ▼
   ┌─────────────────────────┐
   │ auth check (Principle V)│──── invalid ────► 401 (opaque)
   └─────────────┬───────────┘
                 │ valid
                 ▼
   ┌─────────────────────────┐
   │ schema validate         │──── invalid ────► 422 (structured)
   └─────────────┬───────────┘
                 │ well-formed
                 ▼
   ┌─────────────────────────┐
   │ start timer + span      │
   └─────────────┬───────────┘
                 │
                 ▼
   ┌─────────────────────────┐
   │ asyncio.wait_for(       │
   │   backend.predict,      │
   │   timeout=0.200         │
   │ )                       │
   │                         │── timeout / exception
   │                         │──► (UNKNOWN, 0.0), degraded=true,
   │                         │     classifier.timeout counter++
   │                         │
   │  normal return ─────────┼──► (class, p)
   └─────────────┬───────────┘
                 │
                 ▼
   ┌─────────────────────────┐
   │ apply UNKNOWN threshold │
   │  if class != UNKNOWN    │
   │  and p < threshold:     │
   │    class = UNKNOWN      │
   │    (confidence kept     │
   │     as raw p, > 0)      │
   └─────────────┬───────────┘
                 │
                 ▼
   ┌─────────────────────────┐
   │ stop timer, finish span │
   │ return PredictResponse  │
   └─────────────────────────┘
```

The wait_for / except wrapper catches **every** path through `backend.predict(...)`. There is no "log and continue with cached prediction" branch; there is no "default best-guess" branch. Only `(class, p>0)` or `(UNKNOWN, 0.0)`.

## Boot-time state transitions

```
   ┌──────────────────────────────┐
   │ uvicorn starts process       │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ read model_card.md           │
   │  parse required fields       │
   │  any field missing? → exit 1 │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ compute SHA-256 of artifact  │
   │  on disk                     │
   │  mismatch? → log + exit 1    │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ instantiate InferenceBackend │
   │  by artifact_type            │
   │  load artifact into memory   │
   │  any load error? → exit 1    │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ fetch service credential     │
   │  from Vault via hvac         │
   │  fetch fail? → log + exit 1  │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ warm-up: synthetic predict() │
   │  fail? → log + exit 1        │
   └─────────────┬────────────────┘
                 │
                 ▼
   ┌──────────────────────────────┐
   │ start uvicorn listener,      │
   │ readiness probe flips green  │
   └──────────────────────────────┘
```

The listener does **not** open until all of: model card valid, hash matches, backend loaded, credential fetched, warmup ran. This is the constitution's Principle II + V boot posture: the service is either fully ready or not serving traffic.
