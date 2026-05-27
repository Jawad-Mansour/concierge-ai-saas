# Phase 0 — Research: Classifier Service

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Constitution**: `.specify/memory/constitution.md` v1.0.0

This document resolves the three design decisions identified in the plan's Phase 0 section. Each is grounded in the constitution and the spec, with alternatives considered and open risks captured. No `[NEEDS CLARIFICATION]` markers remain.

---

## Decision 1 — Bake-off framing

**Decision**: Use a **single shared evaluation harness** (`modelserver/training/evaluate_models.py`) that takes all three candidates and emits one CSV-style four-metric table into `deliverables/EVALS.md` plus a one-row summary into `deliverables/DECISIONS.md`. The three candidates are:

| Candidate | Training notebook | Artifact format | Inference runtime |
|-----------|-------------------|-----------------|-------------------|
| **A. Classical baseline** | `train_ml.ipynb` (sklearn `Pipeline` of TF-IDF + LogisticRegression; also benches GradientBoostingClassifier and keeps the better of the two) | `classifier.joblib` | `joblib.load(...)` + `pipeline.predict_proba(...)` |
| **B. Small deep model** | `train_dl.ipynb` (compact transformer encoder or 1D-CNN over character/byte-pair tokens, sized to keep inference latency under budget) → `export_onnx.py` for export with `opset_version` pinned and a numerical-equivalence check against the training-time outputs | `classifier.onnx` | `onnxruntime.InferenceSession(...)` |
| **C. LLM zero-shot baseline** | None (no training); a frozen prompt template + a pinned hosted model identifier (e.g., `claude-sonnet-4-6`) | Prompt file `classifier_prompt.txt` + model identifier recorded in `model_card.md` | Hosted provider SDK call inside `inference.py` |

The harness measures and records **all four** metrics required by Principle III, for **all three** candidates, on the **same** held-out set:

1. **Macro-F1 on the held-out set** — `evals/classifier/eval_classifier.py`, against `evals/classifier/datasets/test.jsonl`.
2. **p95 latency under the service load profile** — `evals/classifier/latency_probe.py`, run with the production-equivalent concurrency the team agrees on.
3. **On-disk artifact size** — measured directly from `modelserver/artifacts/`.
4. **Per-1k-request operational cost** — for A and B this is the marginal compute cost on the shared container budget (effectively zero per-1k beyond the steady-state container cost); for C this is the provider's per-token price multiplied by the average token-spend per prediction observed on the held-out set.

The four-metric table is produced once per change to any candidate. The DECISIONS.md row records which candidate wins, *why* it wins against the other two on the four metrics, and which numbers are load-bearing (e.g., "Candidate B wins on F1 by +3 pts; per-1k cost ~0; p95 within budget").

**Rationale**:
- **Principle III explicitly requires** all three candidates evaluated on the same held-out set, with the decision recorded in DECISIONS.md and defended against the other two on the listed metrics. This research decision is the *structure* that makes principle III enforceable — a shared harness ensures the four-metric table is reproducible from one script per the constitution.
- **Principle IV (every decision a number)**: "accuracy alone does not justify a decision" (per the constitution). Holding all four numbers fixed for every candidate forces the trade-off into the open. The shared harness ensures we don't ship the table with one column missing because the relevant probe wasn't trivial.
- **Principle X (spec before code)**: spec section "THE MODEL" names all three candidates and demands the choice be defended in DECISIONS.md — the harness is the spec's mechanism made concrete.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **Three independent eval scripts**, one per candidate | Easy to drift apart in methodology (different test-set version, different concurrency for latency, different cost formula). Principle III's "same held-out set" clause becomes hard to verify. |
| **Skip candidate C (LLM zero-shot)** because per-call cost looks high upfront | Violates Principle III. The cost is *what we measure*, not what we assume. The exercise of putting C through the harness gives us a recorded number to defend the rejection with. |
| **Add a fourth candidate** (e.g., distilled BERT) | Out of spec scope; spec names exactly three. Adding a fourth is its own future spec. |

**Open risks**:
- **Test-set leakage**: if `evaluate_models.py` is ever run against `train.jsonl` instead of `test.jsonl`, the macro-F1 numbers become meaningless. Mitigation: the harness loads from a pinned path (`evals/classifier/datasets/test.jsonl`) and prints the dataset commit-SHA in its output; the DECISIONS.md row records that SHA so a reader can verify.
- **Provider drift on candidate C**: a hosted LLM's behavior can change without a new model identifier. Mitigation: the model card pins the model identifier, the harness records the date/time of the eval run, and a periodic re-run of the harness (Charbel's `evals.yml` schedule or a manual rerun before the demo) keeps the number current. If C is ever the shipped candidate, this risk becomes load-bearing and the model card explicitly says so.

---

## Decision 2 — Inference runtime choice

**Decision**: Implement `inference.py` with two backends — `OnnxBackend` and `SklearnBackend` — selected at boot from the file extension of the artifact in `modelserver/artifacts/`. The active backend is held in a module-level singleton; the dispatch happens once at boot, not per request. For the LLM-zero-shot candidate, a third backend `HostedLlmBackend` exists; it is selected when `model_card.md` declares the artifact type as `hosted_llm_prompt`.

```
artifact extension  →  backend
   classifier.onnx      OnnxBackend (onnxruntime.InferenceSession)
   classifier.joblib    SklearnBackend (joblib.load + sklearn Pipeline)
   classifier_prompt.txt (with hosted_llm flag in card)
                        HostedLlmBackend (provider SDK call)
```

All three backends implement the same `InferenceBackend` protocol:

```python
class InferenceBackend(Protocol):
    def predict(self, message: str) -> tuple[IntentClass, float]: ...
```

The orchestrator in `classifier.py` calls `backend.predict(...)` inside an `asyncio.wait_for(..., timeout=0.200)` block, catches `asyncio.TimeoutError` + every other exception, and on either returns `(IntentClass.UNKNOWN, 0.0)` with `classifier.degraded=true` on the span.

**Rationale**:
- **Principle VI (fail-closed)**: a single `try` / `except` at the orchestrator boundary handles every inference-time failure mode uniformly. The three backends don't each invent their own fail-closed semantics — they raise, and the orchestrator translates raises into the canonical `UNKNOWN`/`0.0` response. This is the cleanest possible implementation of "never the last successful value, never a default best-guess label" (constitution clause VI for the classifier).
- **Latency budget (Principle IV, p95 = 50 ms)**: `onnxruntime` is C++-backed and small-model inference comfortably fits in tens of ms on commodity CPU; `joblib.load`+`sklearn.predict_proba` on a TF-IDF + LogReg pipeline is even faster. The shared `predict` protocol ensures the hot path is dispatching to a single backend object, not branching on extension every request.
- **Principle I (image size)**: `onnxruntime` is ~30 MB; `sklearn`+`scipy`+`numpy` is heavier but still well within budget. If both runtimes are present in the image (because we want to keep the image consistent across deployments and let the bake-off winner be swapped via artifact replacement), the total is still under 500 MB by a wide margin. The team can also build two image variants if image size becomes load-bearing — that's a deployment optimization, not a constitution issue.
- **HostedLlmBackend** has very different latency and cost characteristics. If C is selected, the bake-off table in DECISIONS.md explicitly records the latency hit and the team accepts it. The HostedLlmBackend's `predict` still has to honor the 200 ms hard timeout — which in practice means C cannot win the bake-off if the provider's p95 is above ~150 ms (leaving 50 ms for the wrapper). This is by design: the bake-off mechanically rejects candidates that breach the latency budget.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **One runtime only, always ONNX** — train classical models too and export to ONNX | sklearn → ONNX is possible but the conversion is lossy for some pipeline components (TF-IDF vocab quirks); adds bake-off complexity. Easier to keep two backends with a clean protocol. |
| **Thread-pool offload** for inference | The GIL releases inside `onnxruntime` and inside numpy/scipy under sklearn — so for small-model inference at the project's load, async-on-a-single-thread is faster than thread-pool overhead. Process pool is overkill for this scale (see decision 3). |
| **A queue between the FastAPI handler and the inference call** | Adds lifecycle states (queued / running / cancelled / orphaned) that all need fail-closed semantics defined; for a single-step inference call, a direct sync invocation under a timeout context is simpler. |

**Open risks**:
- **ONNX numerical drift from training**: a model trained in PyTorch and exported to ONNX can diverge from the training-time outputs on edge cases. Mitigation: `export_onnx.py` MUST include a numerical-equivalence check against a sample of training-time predictions and fail loudly on divergence > a small epsilon. The DECISIONS.md row for "Bake-off winner justification" links to that check's output.
- **Joblib version pinning**: `joblib.load(...)` is sensitive to the scikit-learn version that pickled the artifact. The serving container's `scikit-learn` version MUST equal the training notebook's version; the model card records both, and a boot-time version check would be defensive but is currently judged unnecessary because the artifact ships in the same PR as any sklearn upgrade. If this assumption breaks, the boot path gains a version-check step.
- **Hosted-LLM provider outage**: if C is the shipped candidate and the provider is down, every prediction takes the timeout path — which means the entire chat pipeline degrades into "the router escalates everything to the agent because the classifier returned UNKNOWN". The constitution's fail-closed posture handles this correctly (a degraded chat is better than a wrong-routed chat), but operationally it argues against shipping C unless the team accepts that tradeoff in DECISIONS.md.

---

## Decision 3 — Confidence threshold for the UNKNOWN escalation

**Decision**: Derive the **UNKNOWN-escalation threshold** as the confidence level below which the model's predictions on the held-out set show no better than random class assignment. Computed once per shipped artifact by `evaluate_models.py` and recorded in `deliverables/DECISIONS.md` as a single number per the seven-row table in `plan.md`. At inference time, the orchestrator compares `max(predict_proba)` to the threshold; if it falls below, the response is forced to `IntentClass.UNKNOWN` and `confidence` carries the raw probability (so the backend can distinguish "model is uncertain" from "inference timed out", which is `confidence == 0.0`).

Concretely the derivation is:

1. Run the shipped artifact against the held-out set and collect `(predicted_class, confidence)` for every example.
2. Bin predictions by confidence (e.g., 20 equal-width bins over [0, 1]).
3. For each bin, compute accuracy against the gold label.
4. The threshold is the smallest confidence at which the bin's accuracy is still meaningfully above 1/5 (random for a 5-class problem). The exact margin above random is the recorded constant in `eval_thresholds.yaml`.

**Rationale**:
- **Spec User Story 1 acceptance scenario 5**: "the response is the explicit unknown class rather than a low-confidence guess, so the router escalates to the agent instead of acting on noise." The threshold is the mechanism that makes this acceptance scenario testable.
- **Principle IV (every decision a number)**: the threshold MUST be recorded as a number in DECISIONS.md with a reproducible derivation. The above algorithm gives one such derivation; the team can iterate on it but cannot ship without a documented number.
- **Reserved `0.0` for timeout**: keeping `confidence > 0` for "real" UNKNOWNs and reserving `confidence == 0` for timeout-degraded responses lets the backend tell the two apart without an extra response field. The contract documents this reservation explicitly.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **No threshold — always return the argmax class** | Violates spec User Story 1.5. The router would see low-confidence guesses as "real" classifications and route them, e.g., as FAQs that have no CMS match — wasted work or wrong answers. |
| **A fixed threshold (e.g., 0.5) chosen by intuition** | Not a number backed by data; violates Principle IV. The threshold *value* may be reasonable but the *justification* is not. |
| **A per-class threshold** (one threshold per class) | Possible follow-up if the four-metric bake-off shows a class with very different confidence distribution from the rest. For v1 a single threshold is simpler; the DECISIONS.md row can record the per-class accuracy distribution as future ammunition for the per-class variant. |
| **A confidence threshold derived from the model's training set rather than the held-out set** | Overconfidence on the training set would make the threshold useless. The held-out set is what we have for unbiased estimates. |

**Open risks**:
- **Threshold drift across model versions**: a re-trained model may need a different threshold to keep the UNKNOWN escalation at the same operating point. Mitigation: `evaluate_models.py` recomputes the threshold for every artifact and prints both the old and new values; the PR description records the change. The `eval_thresholds.yaml` file holds the *minimum macro-F1* gate (Principle VIII / spec FR-012) not the UNKNOWN threshold — the UNKNOWN threshold lives next to the model card so it travels with the artifact.
- **Class imbalance bias**: if one class dominates the held-out set, the global accuracy-against-random comparison can be misleading. Mitigation: the held-out set is class-balanced by construction (the dataset README records this); if it ever stops being so, the derivation method moves to per-class accuracy-above-class-prior.

---

## Cross-cutting confirmations

- **No PII reaches logs or spans from this service** (Principle IX-relevant note, even though redaction itself is out of scope): the handler logs only structural facts (`tenant_id`, `predicted_class`, `confidence`, `latency_ms`, `model_hash`), never the input string. The span attribute set is the same. This is the design's standing answer to Principle IX for the v1 classifier.
- **The model hash on every span** (Principle VII tail / spec FR-011 / SC-004): cached at boot from `model_loader.py` into `app/version.py`, set on every span as `classifier.model_hash`. Reproducibility from any production span to a specific artifact is what makes SC-004 ("100% of authenticated prediction calls reproducible to a specific model artifact via the model-hash field") hold.
- **Tenant-agnostic prediction** (spec FR-006 / SC-008): `tenant_id` is read off the request body, set on the span, and **not** passed into `backend.predict(...)`. The CI gate (Principle VIII) sends the same message under two `tenant_id` values and asserts identical responses — that probe makes the property testable in CI.
- **No `NEEDS CLARIFICATION` markers remain** from the spec; Phase 0 closes here.
