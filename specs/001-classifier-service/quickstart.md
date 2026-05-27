# Quickstart — Classifier Service

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Contracts**: [`contracts/`](./contracts/)

This walk-through brings the classifier service up locally next to the backend, exercises `POST /predict`, confirms authentication and timeout-fallback behavior, verifies tenant-agnostic prediction, and demonstrates the model-hash boot check. Use it as the acceptance loop before opening a PR and as the demo path for the Friday review.

Time to complete from a clean clone: ~5 minutes first time, ~30 seconds on subsequent runs.

## Prerequisites

- Docker + docker-compose installed.
- Project bootstrapped via `scripts/bootstrap.sh` (creates the docker network, Vault dev token, and seeds `secret/data/modelserver/service_credential`).
- The shipped model artifact exists at `modelserver/artifacts/classifier.onnx` **or** `modelserver/artifacts/classifier.joblib`, with `modelserver/artifacts/model_card.md` carrying its SHA-256.

If you haven't bootstrapped yet:

```bash
./scripts/bootstrap.sh
```

## 1. Bring the stack up

```bash
docker compose up -d modelserver backend
```

Wait for the readiness probe to flip green. The classifier's boot path (see [data-model.md "Boot-time state transitions"](./data-model.md#boot-time-state-transitions)) runs in this order:

1. Parse `model_card.md`.
2. Compute SHA-256 of the artifact on disk; compare against the card.
3. Instantiate the inference backend (ONNX or sklearn) and load the artifact.
4. Fetch the service credential from Vault.
5. Run a synthetic prediction (warm-up).
6. Open the listener; readiness flips green.

Any failure at steps 1–5 makes the container exit non-zero — the orchestrator restarts it visibly (FR-008 / Principle II).

```bash
docker compose ps modelserver
# STATE should be "running" with health: "healthy"
```

Confirm the loaded model hash matches the card:

```bash
docker compose logs modelserver | grep model_hash_verified
# Expected: structured log line with the full SHA-256 and the artifact filename.
```

## 2. Hit `/predict` with a valid credential

Grab the service credential from Vault (dev mode):

```bash
SVC_CRED=$(vault kv get -field=token secret/modelserver/service_credential)
```

Send a clear FAQ-shaped message:

```bash
curl -sX POST http://localhost:8001/predict \
  -H "Authorization: Bearer $SVC_CRED" \
  -H "Content-Type: application/json" \
  -d '{
        "tenant_id": "tenant-acme",
        "message": "What are your business hours?"
      }' | jq
```

Expected response shape (the exact `predicted_class` and `confidence` depend on which bake-off candidate is currently shipped):

```json
{
  "predicted_class": "FAQ",
  "confidence": 0.92,
  "model_hash": "a1b2c3d4e5f6"
}
```

Confirm `model_hash` matches the 12-character truncation of the full SHA-256 in `modelserver/artifacts/model_card.md`.

## 3. Exercise each class

```bash
# SPAM
curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"BUY CHEAP MEDS NOW!!! click http://spammy.example"}' | jq

# CONTACT_LEAD
curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"Im interested in pricing — can you call me at +1-555-0123?"}' | jq

# HARD_QUESTION
curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"Can you compare your enterprise plan to the team plan, and tell me if the SLA covers EU data residency?"}' | jq

# Low-confidence → UNKNOWN (confidence > 0)
curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"hey"}' | jq
```

For the ambiguous "hey" case the response should be `predicted_class: "UNKNOWN"` with `0 < confidence < threshold`. The `model_hash` is the same as above (same process, same artifact).

## 4. Confirm tenant-agnostic prediction (SC-008)

Send the same message twice with two different `tenant_id` values:

```bash
M='Can you tell me your hours?'

R1=$(curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"tenant-acme\",\"message\":\"$M\"}")
R2=$(curl -sX POST http://localhost:8001/predict -H "Authorization: Bearer $SVC_CRED" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"tenant-globex\",\"message\":\"$M\"}")

# The two responses should be byte-identical except for any incidental ordering.
diff <(echo "$R1" | jq -S .) <(echo "$R2" | jq -S .)
# Expected: empty (no diff).
```

If `diff` reports any difference, the tenant_id is leaking into prediction — a P1 violation of FR-006.

## 5. Confirm the 401 path is opaque

```bash
# Missing credential
curl -sX POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"hi"}' -o - -w "HTTP %{http_code}\n"

# Malformed credential
curl -sX POST http://localhost:8001/predict \
  -H "Authorization: Bearer not-a-real-token" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"hi"}' -o - -w "HTTP %{http_code}\n"
```

Both MUST return `HTTP 401` with the identical body `{"detail":"unauthenticated"}` (FR-004, Principle V).

## 6. Observe the spans

The classifier exports spans to the local OTel collector. Inspect the most recent traces:

```bash
docker compose logs otel-collector --tail=50 | grep classifier
```

For each prediction you should see a span carrying:

- `tenant_id`
- `classifier.predicted_class` (one of the five class names)
- `classifier.confidence` (float, including `0.0` for degraded)
- `classifier.latency_ms` (float)
- `classifier.model_hash` (12-character lowercase hex)
- `classifier.degraded` (bool — only `true` on the timeout-fallback path)

**Critical**: `grep` the collector logs for the literal message text you sent in step 2. You should find **zero hits**. The classifier's "never log content" stance (research.md cross-cutting confirmations) keeps Principle IX-relevant hygiene intact.

## 7. Trigger the timeout-degraded path (FR-009)

Set the per-call timeout to a value below what inference can satisfy and bounce the worker. The simplest way is via an env-var override the service accepts in dev mode:

```bash
docker compose exec modelserver sh -c "echo 'INFERENCE_TIMEOUT_MS=1' >> /app/.env"
docker compose restart modelserver
```

Hit `/predict`:

```bash
curl -sX POST http://localhost:8001/predict \
  -H "Authorization: Bearer $SVC_CRED" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant-acme","message":"hi"}' | jq
```

Expected:

```json
{
  "predicted_class": "UNKNOWN",
  "confidence": 0.0,
  "model_hash": "a1b2c3d4e5f6"
}
```

`confidence: 0.0` is the reserved sentinel (data-model.md "Confidence values"). The corresponding span carries `classifier.degraded: true` and a `classifier.timeout` counter event.

Restore:

```bash
docker compose exec modelserver sh -c "sed -i '/INFERENCE_TIMEOUT_MS/d' /app/.env"
docker compose restart modelserver
```

If you ever see `confidence > 0.0` on this drill, Principle VI for the classifier has been violated — root-cause before merging.

## 8. Hash-mismatch boot drill (Principle II / FR-008)

Swap the artifact with one whose SHA-256 doesn't match the card:

```bash
docker compose exec modelserver sh -c "mv /app/artifacts/classifier.onnx /app/artifacts/classifier.onnx.bak"
docker compose exec modelserver sh -c "echo 'not a real model' > /app/artifacts/classifier.onnx"
docker compose restart modelserver
```

Expected: the container exits non-zero (the orchestrator's restart loop becomes visible in `docker compose ps`). `docker compose logs modelserver` shows a `model_hash_mismatch` structured log line naming the expected and actual hashes — truncated, never the raw artifact bytes.

Restore:

```bash
docker compose exec modelserver sh -c "mv -f /app/artifacts/classifier.onnx.bak /app/artifacts/classifier.onnx"
docker compose restart modelserver
```

If the service ever **starts** with a mismatched artifact (i.e., responds 200 to `/predict` from this drill), Principle II has been violated and the model_loader has lost its hash check.

## 9. Run the held-out evaluation (FR-012)

```bash
python evals/classifier/eval_classifier.py
```

The script loads the shipped artifact (via the same `model_loader.py` path the service uses), runs predictions over `evals/classifier/datasets/test.jsonl`, and prints macro-F1 plus per-class precision/recall. The CI gate (`evals.yml`) runs this script on every PR touching `modelserver/` or `artifacts/` and fails the build if macro-F1 falls below `eval_thresholds.yaml`.

For a healthy shipped artifact, the printed macro-F1 should equal or exceed the threshold; this is also what the DECISIONS.md row "Held-out macro-F1 of deployed model" records.

## 10. Latency probe (for the DECISIONS.md row)

```bash
python evals/classifier/latency_probe.py --concurrency 16 --requests 1000
```

The script prints p50/p95/p99 for `/predict`. Record p95 in `deliverables/DECISIONS.md` under the "p95 latency budget" row alongside the methodology (concurrency, request count, message-length mix). If p95 exceeds 50 ms on typical messages, either:

- Add uvicorn workers in `docker-compose.yml` (cheapest first move; see research.md decision 2).
- Or open an issue against this spec before continuing — the budget is load-bearing for the chat-turn latency contract with the router.

## Done

If steps 2–8 all behaved as expected and steps 9–10 came in over threshold / under budget, the classifier is ready to be wired into `backend/app/services/classifier_client.py` (Jana-owned per `structure.md`, so wiring lands in the same PR or the immediately following one).
