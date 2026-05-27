# Phase 0 — Research: Guardrails Sidecar

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Constitution**: `.specify/memory/constitution.md` v1.0.0

This document resolves the three design decisions identified in the plan's Phase 0 section. Each decision is grounded in the constitution and the spec, with alternatives considered and open risks captured. No `[NEEDS CLARIFICATION]` markers remain.

---

## Decision 1 — Rail engine choice

**Decision**: Use **NeMo Guardrails** as the rail engine for prompt-injection refusal, jailbreak detection, cross-tenant data refusal, and tenant allowed-topics enforcement. Rails are authored in `guardrails/config/*.yaml` (Colang flows + topical rails) and loaded at process startup. Tenant rails (allowed topics, refusal persona, escalation triggers) are composed onto the platform rails at request time using the `tenant_config` carried in the request body.

**Rationale**:
- **Principle I (lean containers)**: NeMo Guardrails' default install does not require torch — it uses an embedding model only if topical rails are configured to use semantic similarity, and even then a small SentenceTransformers model is sufficient. We can sit within the 500 MB image-size budget by pinning NeMo Guardrails without torch-heavy optional extras.
- **Principle VI (fail-closed)**: NeMo's engine raises on malformed configuration or runtime evaluation errors. Wrapping every engine invocation in a single `try`/`except` returning `decision="block"` with `rule_name="engine_error"` and `action="fallback_response"` is one line at the orchestrator boundary in `validators.py` — clean to reason about and easy to assert on.
- **Spec FR-003 (platform rail set), FR-004 (tenant rails), FR-006 (tenant refusal language)**: NeMo's topical-rails + Colang flow model naturally expresses "block this kind of message, then route through the tenant's refusal template" — exactly the shape the spec requires. Tenant config can supply the refusal flow's persona/tone parameters at composition time without rewriting the engine.
- **Jailbreak corpus maintainability**: NeMo's community-shipped jailbreak rules give us a credible starting set (DAN, alter-ego framings, encoded payloads). The corpus is YAML — diffable, reviewable, and contributed to with PRs, which matches how the rest of this slice operates.
- **Principle X (spec before code)**: NeMo Guardrails was the stack named in the user prompt and aligns with the slice constitution's "guardrails sidecar (FastAPI + NeMo Guardrails)" sentence; using anything else would require a constitution amendment.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **Handwritten LLM-based classifier** — call an LLM with a "is this prompt injection?" prompt for each message | Latency budget (Principle IV row: 100 ms p95) is impossible with a network round-trip to an external LLM provider on the chat-turn critical path. Even a local small model would breach the latency budget under realistic concurrency unless GPU-backed, which would violate Principle I (image size and base-image complexity). Fail-closed behavior also becomes harder — an LLM can refuse a "is this prompt injection?" classification with hedged output, leaving the orchestrator without a clean block/pass decision. |
| **Pure regex / rule-of-thumb pattern matching** — write our own regex for each platform rail | Cheap and fast, but the jailbreak corpus moves faster than any in-house regex bank. Maintaining "DAN", "alter ego", "hypothetical evil", and the next dozen frames in regex would consume more engineering than is justified by the four-person team's bandwidth. Also collapses the platform-rail logic into something Charbel and Mohammad's reviewers cannot reason about without becoming guardrails experts — violating the spirit of Principle X (specs and reviewers must align). |
| **Microsoft Guidance / Outlines / structured-decoding libraries** | Designed for shaping LLM output, not for screening LLM input/output. Not the right tool. |

**Open risks**:
- **Image-size risk**: NeMo Guardrails has optional dependencies that can pull in torch. We MUST pin a torch-free install profile and verify with the CI image-size job. If torch sneaks in transitively, fall back to a curated subset of NeMo (its core LLMRails evaluator + Colang interpreter) or, as last resort, the pure-regex alternative for a subset of rails.
- **Latency risk**: NeMo's default execution path involves a small embedding call for topical rails. Cold-start of that path can exceed our budget on the first request. Mitigation: warm the rails engine in the FastAPI startup event before the readiness probe flips green; the readiness probe MUST exercise a synthetic evaluation. The Day-1 latency probe (`evals/security/latency_probe.py`) measures the warmed-up p95, not the cold-start p95.
- **Rail-coverage risk**: NeMo's community jailbreak corpus is not exhaustive. We accept this as a known limitation — the security CI gate (Principle VIII) keeps coverage honest by failing PRs that regress against the committed probe set, and we add new probes as new jailbreak frames surface.

---

## Decision 2 — PII recognizer choice

**Decision**: Use **Microsoft Presidio** (`presidio-analyzer` + `presidio-anonymizer`) with two custom regex-based recognizers added on top:
- `HostedLLMApiKeyAnthropic` — matches `sk-ant-` prefix patterns (Anthropic API keys).
- `HostedLLMApiKeyOpenAI` — matches `sk-` prefix patterns scoped to avoid colliding with `sk-ant-` (OpenAI API keys).

The deployed recognizer set is: `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `US_SSN`, `GENERIC_BEARER_TOKEN`, `HOSTED_LLM_API_KEY_ANTHROPIC`, `HOSTED_LLM_API_KEY_OPENAI`. The first four come from Presidio's built-in recognizers; the last three are committed pattern recognizers under `guardrails/config/pii_redaction.yaml`.

Anonymization uses Presidio's `replace` operator with stable placeholders of the form `<{RECOGNIZER_NAME}>` (e.g., `<EMAIL_ADDRESS>`, `<HOSTED_LLM_API_KEY_ANTHROPIC>`). Stable placeholders are required because (a) the LLM works from the redacted text and shouldn't see different placeholders for the same field across turns, and (b) the probe-string tests under Principle IX assert absence of the original probe string regardless of placeholder spelling.

**Rationale**:
- **Principle IX (provable redaction)**: Presidio is a well-known battle-tested PII library; the redaction guarantees we make come from observation against real sinks (Principle IX's mechanism), not from library marketing. Presidio gives us a wide recognizer surface to start with — we don't have to write `email` and `credit_card` regex correctly ourselves.
- **Custom recognizer ergonomics**: Adding `HOSTED_LLM_API_KEY_ANTHROPIC` and `HOSTED_LLM_API_KEY_OPENAI` is a few-line YAML config in `guardrails/config/pii_redaction.yaml`. This is the right granularity for project-specific recognizers — they live with the rest of the rails config, are diff-reviewable, and don't require a code change to add a future recognizer (e.g., for a third hosted LLM provider).
- **Principle I (image size)**: Presidio's analyzer ships with spaCy for some recognizers. The recognizers we need (the seven listed above) are **all** regex/pattern-based and do not require the spaCy NLP backend. We can configure Presidio to skip spaCy load (or, equivalently, register only `PatternRecognizer` instances and bypass the default `NlpEngine`). This keeps the image under 500 MB without losing recognizer fidelity.
- **Principle IV (numbers backed)**: Per-recognizer recall and precision targets land in `deliverables/DECISIONS.md`, measured by `evals/security/redaction_probes.py` against a labeled set. Presidio gives us a stable, reviewable thing to measure against — handrolled regex would require us to also bench the regex itself.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **Handwritten regex bank** (per recognizer) | Owning the regex for credit cards (Luhn-validated), international phone numbers, and SSN edge cases is more work than the project can absorb. We'd be re-litigating well-solved problems on the chat-turn critical path. Custom recognizers for project-specific patterns (the hosted-LLM keys) still go through Presidio's `PatternRecognizer` so the framework is consistent. |
| **LLM-based PII detector** | Same latency-budget objection as for the rail engine. Also Principle IX requires assertions against real sinks — an LLM detector adds another opaque step that has to be probed too, which compounds testing surface without removing the basic regex work. |
| **OpenTelemetry / sidecar log redaction only** (no inline redaction) | Would let raw PII reach the LLM provider, violating spec User Story 2 and SC-003 ("no sensitive value matched by any supported recognizer appears in any log line, tracing span, or persisted payload the LLM provider receives"). Non-starter. |

**Open risks**:
- **Recall on rare recognizers**: Presidio's `US_SSN` is a regex with weak context awareness; false positives on 9-digit numbers can over-redact. The DECISIONS.md row for "PII redaction precision" surfaces this as a measured number; mitigation if precision is too low is to require a context phrase (e.g., "SSN", "social security") via Presidio's `context` list.
- **API-key prefix collision**: `sk-ant-` is unambiguous but `sk-` is broad enough to match base64 substrings. The `HOSTED_LLM_API_KEY_OPENAI` recognizer requires an entropy floor (a minimum length following `sk-` and characters drawn from the alphabet OpenAI keys use) to bound false positives. The committed pattern is reviewed in PR.
- **Stable-placeholder collision**: If the LLM ever returns a literal `<EMAIL_ADDRESS>` string in its response (because it's mimicking what it saw in the redacted input), the output-side check still treats that as a plain string, not as a real email — no double-redaction loop. Verified by a unit test in `backend/tests/test_redaction.py`.

---

## Decision 3 — Latency strategy

**Decision**: Run rail evaluation **synchronously in-process** inside the FastAPI request handler, with the rails engine and Presidio analyzer loaded once at FastAPI startup and held as module-level singletons. No queue, no process pool, no thread pool offload. Use `async def` handlers so FastAPI can interleave I/O-bound work (the request lifecycle) but the rail evaluation itself runs on the event loop's thread, which is acceptable because rail evaluation is CPU-bound at small scale and the dominant cost is regex matching, not blocking I/O.

If, at production load, the synchronous path is unable to meet the 100 ms p95 target on a single uvicorn worker, the **scale-out** answer is "run more uvicorn workers / more sidecar replicas" (Charbel's docker-compose layout already supports this), **not** introduce an in-process queue. A queue would add tail latency variance and would conflict with the fail-closed semantics — a queued evaluation that times out has to be cancelled and converted to a fail-closed block, and that lifecycle is harder to assert on than `try`/`except` in a single function.

**Rationale**:
- **Principle VI (fail-closed)**: A synchronous request path makes the fail-closed branch trivial — any exception inside `validators.evaluate()` is caught at the top of the handler and returned as a `block` with `engine_error`. An async queue or pool introduces lifecycle states (queued / running / cancelled / orphaned) that all need fail-closed semantics defined, which is more code and more test surface for no latency win at the project's scale.
- **Principle IV (numbers)**: The latency budget (100 ms p95) is the number we measure. Synchronous in-process is the simplest thing that can possibly meet it; we measure it, record it, and revisit only if the number is missed.
- **Cold-start**: Loading NeMo Guardrails and Presidio at FastAPI startup keeps the request-path warm. The readiness probe MUST exercise both rails (a synthetic block-eligible message) and redaction (a synthetic redact-eligible message) before flipping green, so traffic only arrives when the warmup is complete.
- **Spec FR-012 (latency property)**: The spec captures the property "stays within the share of the budget" rather than a specific millisecond number. Synchronous evaluation makes the budget straightforward to measure against.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|--------------|
| **In-process async queue with worker tasks** | Adds lifecycle states without latency gains for our load. Conflicts with fail-closed (queued-then-cancelled is a fail-closed path that needs definition and tests). Premature complexity. |
| **`concurrent.futures.ProcessPoolExecutor` offload** | Process startup overhead per worker is significant, and serializing the request/response across the process boundary adds latency that we can't afford on the chat-turn critical path. Mostly relevant if the rail evaluator were genuinely CPU-heavy (e.g., a deep model); for regex + Colang interpretation it is overkill. |
| **Pre-warmed thread pool** | Python's GIL makes this only useful if rail evaluation drops the GIL during heavy work (Presidio's regex C-impl can, but it's not the bottleneck). For our workload, async handlers on a single thread are the right model; if we need parallelism we add uvicorn workers (multi-process). |

**Open risks**:
- **Tail latency under burst load**: A burst of concurrent requests on a single uvicorn worker can starve the event loop. Mitigation: docker-compose runs the sidecar with `--workers 2` (or whatever the latency probe finds sufficient), and the readiness probe gates traffic on a successful warmup evaluation. The latency probe at the production-like concurrency level is the test that catches this.
- **GIL contention with the OTel SDK**: OTel span export can hit the GIL on hot paths. We use the OTel batch span processor (`BatchSpanProcessor`) so export is amortized off the request path; this is standard and well-tested.

---

## Cross-cutting confirmations

- **No model artifacts on disk** → Principle II is non-applicable for this service; no boot-time SHA-256 check is required.
- **Vault credential** → fetched once at boot via `hvac`; service refuses to start if fetch fails. Validated on every request via a FastAPI dependency. Principle V is satisfied without any per-request Vault round-trip (which would breach Principle IV's latency row).
- **Rails ruleset version** → derived at container build time from a hash of the `guardrails/config/*.yaml` files and baked into `app/version.py`. Set on every span. Principle VII is satisfied.
- **No `NEEDS CLARIFICATION` markers remain** from the spec; Phase 0 closes here.
