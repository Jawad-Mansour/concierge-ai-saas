<!-- Owner: Jana -->

# Concierge — Security Posture

This document records the guardrails sidecar's deployed posture: which rails fire, which recognizers are wired in, how fail-closed is enforced, and how the probe-string discipline (Principle IX) is exercised in CI.

The `rails_version` constant baked into the image is a SHA-256 truncation of the canonical concatenation of `guardrails/config/*.yaml`. Any change to a rail or recognizer changes the hash; a server that boots with a `RAILS_CONFIG_HASH` that no longer matches its on-disk configs refuses to start. See `guardrails/app/version.py` and the boot path in `guardrails/app/main.py`.

## Platform rails

The sidecar enforces four rails ahead of any tenant configuration. Order is fixed: `prompt_injection` → `jailbreak` → `cross_tenant` → (redaction on pass).

| Rail | What it catches | What it does NOT catch | Source |
|------|-----------------|------------------------|--------|
| `prompt_injection` | Visitor message attempts to override the system prompt, invoke developer/admin/debug mode, or extract the system prompt verbatim. | Indirect injection from RAG content (covered by the backend's content-source-trust separation, not this rail). | `guardrails/config/rails.yaml#patterns.prompt_injection`, `cross_tenant_rules.yaml`, evaluated by `app/rails_engine.py`. |
| `jailbreak` | Known jailbreak frames: DAN, alter-ego, hypothetical-evil, base64-encoded payload smuggling. | Novel jailbreaks that don't match a committed frame — those become red-team probe additions, not silent passes. | `guardrails/config/jailbreak_rules.yaml#frames` (named frames per spec US1 acceptance scenario 2). |
| `cross_tenant` | Explicit naming of another tenant from the `tenant_names` allowlist, semantic references ("the other client", "another tenant", "the previous customer"), and cross-boundary system-prompt extraction attempts. | Benign reuse of common nouns like "another question" (precision tested by the cross-tenant benign-control entries in `evals/security/cross_tenant_cases.json`). | `guardrails/config/cross_tenant_rules.yaml`. |
| (redaction) | Seven PII recognizer categories — see below. Runs only on the `pass` branch. | Anything outside the recognizer set; non-PII secrets without a registered recognizer pattern. | `guardrails/config/pii_redaction.yaml` + `guardrails/app/redaction.py`. |

Platform precedence: when a message would fire both a platform rail and a tenant rail, the platform rail wins (`spec edge case "platform rails always take precedence"`, enforced by `guardrails/tests/test_platform_precedence.py`).

## Recognizer set

Seven recognizers are deployed; the registration order matters because `HOSTED_LLM_API_KEY_ANTHROPIC` (`sk-ant-…`) MUST match before `HOSTED_LLM_API_KEY_OPENAI` (`sk-…`) — without that ordering an Anthropic key would be tagged as OpenAI (research.md Decision 2 open risk "API-key prefix collision"). The order is pinned in `guardrails/app/redaction.py:_RECOGNIZER_ORDER`.

| Recognizer | Pattern source | Notes |
|------------|----------------|-------|
| `HOSTED_LLM_API_KEY_ANTHROPIC` | `pii_redaction.yaml#recognizers.HOSTED_LLM_API_KEY_ANTHROPIC.pattern` | `sk-ant-[A-Za-z0-9_-]{20,}` — matches Anthropic API keys. |
| `HOSTED_LLM_API_KEY_OPENAI` | `pii_redaction.yaml#recognizers.HOSTED_LLM_API_KEY_OPENAI.pattern` | `sk-(?!ant-)[A-Za-z0-9]{20,}` — negative lookahead excludes the Anthropic prefix. |
| `GENERIC_BEARER_TOKEN` | `pii_redaction.yaml#recognizers.GENERIC_BEARER_TOKEN.pattern` | Conservative JWT shape (three base64url segments separated by `.`). Reduces false positives on unrelated long strings. |
| `EMAIL_ADDRESS` | Presidio built-in. | |
| `PHONE_NUMBER` | Presidio built-in. | |
| `CREDIT_CARD` | Presidio built-in. | |
| `US_SSN` | Presidio built-in. | |

Anonymizer operator: `replace` with the recognizer's name in angle brackets (e.g., `<EMAIL_ADDRESS>`). Stable placeholders let downstream telemetry record *which kind* of value fired without recording the value itself — directly enabling Principle IX. Replacement counts are surfaced via `RedactionMetadata.match_count`; matched values, offsets, and original substrings never leave the request scope (`guardrails/app/telemetry.py:structured_log` strips `message`/`llm_response`/`matched_value` keys defensively).

## Fail-closed posture

Every internal error path collapses to `block(rule_name, action="fallback_response")`. There is no return-`None`-and-log path anywhere. The closed vocabulary for `rule_name` on the fail-closed branch is:

- `engine_error` — any exception raised by the rail engine or the redactor.
- `config_error` — `tenant_config` was admitted by the schema but the rail engine couldn't make sense of it.

Both produce `action="fallback_response"`, `refusal_text=None`, and `payload` absent. A `guardrail.fail_closed` event is added to the active span and a structured-log line is emitted carrying `tenant_id`, `endpoint`, and the exception class name (never the exception message — that can echo input). The global FastAPI `Exception` handler in `guardrails/app/main.py` is defense-in-depth; the orchestrator's own try/except in `validators.evaluate` catches the typical case.

Boot-time fail-closed: a `RAILS_CONFIG_HASH` mismatch makes `guardrails/app/main.py` call `sys.exit(1)`. The listener never opens against an unverified config set (Principle II).

## Auth model

A Vault-issued service credential is fetched once at boot from `secret/data/guardrails/service_credential` (path TBD against `infra/vault/policies/` — Mohammad). The fetch is non-recoverable: on any failure (auth, network, missing path) the process calls `sys.exit(1)` and the orchestrator restarts the container visibly.

Every `/check/input` and `/check/output` request runs through the `require_service_credential` FastAPI dependency. The comparison is constant-time (`hmac.compare_digest`) against the boot-loaded credential. Failure modes — missing `Authorization` header, wrong scheme (`Basic …`, etc.), token mismatch — all raise the same `HTTPException(401, detail="unauthenticated")`. The global 401 handler in `main.py` emits a byte-identical `UnauthenticatedResponse` body for every cause; no `WWW-Authenticate` realm hint. Network reachability over docker-compose is NOT treated as authentication.

## Probe-string discipline (Principle IX)

`backend/tests/test_redaction.py` injects a per-recognizer unique probe into a `/check/input` request against a **running** sidecar. After the response returns:

1. `docker compose logs --tail=500 guardrails` — the actual container stdout/stderr (no mocked logger).
2. The OTel collector's persisted span-export file (`OTEL_EXPORT_FILE`, set by the CI step).
3. The returned response body bytes.

The assertion is the probe string is **absent** from all three. The test is gated on the `GUARDRAILS_E2E` env-var so devs can opt in locally; CI sets it unconditionally in `security-gates.yml`.

The probe set in `evals/security/redaction_probes.json` carries the per-recognizer templates and runtime-generated values, so each CI run uses a fresh probe string (no cached match-anything regex can hide a leak).

## CI gate

`.github/workflows/security-gates.yml` runs on every PR touching `guardrails/**`, `evals/security/**`, or the related backend wiring. The job:

1. installs `guardrails/[dev]`,
2. runs the auth, platform-rail, tenant-rail, fail-closed, redaction-unit, and span/PII tests,
3. builds the sidecar image and stands up `guardrails` + `vault` + `otel-collector`,
4. runs the probe-string scan against real sinks,
5. replays the red-team JSON probe sets,
6. runs the latency probe and gates on p95 < 100 ms.

No `continue-on-error`, no probe weakening, no deletion. Weakening this workflow is a constitution violation (Principle VIII).
