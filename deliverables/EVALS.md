<!-- Owner: Shared -->

# Concierge — Eval Methodology

Six CI gates must all pass on every push. Thresholds are committed in `eval_thresholds.yaml`.

---

## Gates and Owners

| Gate | Script | Owner | Threshold | Blocking? |
|------|--------|-------|-----------|-----------|
| Intent classifier accuracy | `evals/classifier/eval_classifier.py` | Jana | macro-F1 ≥ threshold | Yes (once baseline set) |
| Agent tool-selection | `evals/agent/eval_tools.py` | Ali | accuracy ≥ threshold (15 golden examples) | Yes (once baseline set) |
| RAG golden set | `evals/rag/eval_rag.py` | Ali | hit@5 and faithfulness ≥ thresholds | Yes (once baseline set) |
| Red-team security | `evals/security/red_team_tests.py` | Jana | **1.0 (100%)** | **Always hard block** |
| Smoke test | `evals/smoke/smoke_test.py` | Charbel | all 13 services healthy | Yes |
| PII redaction | (within security gate) | Jana | 0 PII leaks | Hard block |

Run all gates:

```bash
bash scripts/run_evals.sh
```

---

## Security Gate (non-negotiable)

`evals/security/red_team_tests.py` must pass at **100%**. This threshold is `security: 1.0` in `eval_thresholds.yaml` and must never be lowered, even temporarily.

Test categories covered:
- Prompt injection via widget message
- Cross-tenant data extraction attempts
- Jailbreak bypass attempts
- Tenant ID body-injection attack
- PII exfiltration (fake API key must not appear in logs, Langfuse traces, or Redis)

A single failure in this gate is a hard CI block regardless of all other gate scores.

---

## Intent Classifier Eval

**Script**: `evals/classifier/eval_classifier.py`

**Method**: Loads the ONNX/sklearn artifact from `modelserver/artifacts/`. Runs the golden test set and computes macro-F1 across all intent classes. The model card (`modelserver/artifacts/model_card.md`) pins the artifact SHA-256; the server refuses to boot if the loaded artifact doesn't match.

**Baseline**: Set by Jana once the first production-quality model is trained. Until then, threshold is `0.0` (non-blocking) in `eval_thresholds.yaml`.

---

## Agent Tool-Selection Eval

**Script**: `evals/agent/eval_tools.py`

**Method**: 15 golden (input, expected_tool_sequence) examples. Each is run against the live agent and the actual tool call sequence is compared to expected. Accuracy = exact-match on the first tool call selected.

**Baseline**: Set by Ali. Threshold defaults to `0.0` until first baseline is committed.

---

## RAG Golden Set Eval

**Script**: `evals/rag/eval_rag.py`

**Method**:
- **hit@5**: For each golden query, the expected chunk must appear in the top-5 pgvector results. Requires the tenant_id filter — failing to include `where={"tenant_id": ...}` causes false positives (hits from other tenants inflate the score).
- **faithfulness**: Response must be grounded in retrieved context. Measured by an LLM-as-judge call comparing the response against the retrieved chunks.

**Baseline**: Set by Ali. Both sub-scores must meet threshold independently.

---

## Smoke Test

**Script**: `evals/smoke/smoke_test.py`

**Method**: Runs `docker compose up` from a clean clone and polls each service's `/health` endpoint until all 13 pass or a timeout fires. Also verifies that Vault is unsealed, Postgres migrations completed, and the Langfuse UI is reachable.

**Threshold**: All 13 services must be healthy. Any unhealthy service is a hard block.

---

## Eval Threshold Policy

- Thresholds in `eval_thresholds.yaml` can only be raised, never lowered (except to correct an error in the threshold itself via PR review).
- The security gate is permanently fixed at `1.0` — it is a constitutional floor.
- When a new model version ships, its baseline must be at least as high as the previous model's score before the threshold is updated.
- Regressions in any gate block merge until resolved or the regression is documented as an accepted trade-off via ADR.
