# Phase 1 — Data Model: Guardrails Sidecar

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Contracts**: [`contracts/`](./contracts/)

This document describes the data entities the sidecar accepts, returns, and operates on internally. All entities are conveyed over the HTTP boundary as JSON; the canonical implementations are Pydantic v2 models in `guardrails/app/schemas.py`. Closed-vocabulary fields (`decision`, `rule_name`, `action`, `recognizer_name`) are defined as `Literal` types so that adding a value is a typed, reviewable code change rather than an accidental string.

## Entities

### `EvaluationRequestInput`

Sent by the backend to `POST /check/input` before the LLM call.

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `tenant_id` | string | yes | non-empty, length ≤ 64, `[A-Za-z0-9_-]+` | Opaque to the sidecar; used for tracing only (Principle VII). |
| `message` | string | yes | length ≤ 16 KiB | The visitor's incoming message. May contain PII (will be redacted before any sink). |
| `tenant_config` | `TenantConfig` | yes | well-formed per `TenantConfig` schema | If the tenant has no configured rails, the backend MUST send `tenant_config: {}` — not omit the field. |

**Validation behavior**: A request missing `tenant_id`, missing `message`, or with `message` that is empty / whitespace-only is rejected at FastAPI's Pydantic validation layer with HTTP 422 (the structured "bad request" outcome — spec edge case "empty message" is captured here as a malformed request, per the spec). The `tenant_id_missing=true` span attribute is set when `tenant_id` is absent, per Principle VII.

### `EvaluationRequestOutput`

Sent by the backend to `POST /check/output` after the LLM call.

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `tenant_id` | string | yes | same as above | Same notes. |
| `llm_response` | string | yes | length ≤ 32 KiB | The LLM's draft response. May contain PII the model echoed from input or hallucinated. |
| `tenant_config` | `TenantConfig` | yes | same as above | Same notes. |

### `EvaluationResponse` *(discriminated union — `oneOf`)*

Returned by both endpoints. Always HTTP 200 unless the request failed authentication (401) or validation (422).

```
EvaluationResponse = EvaluationResponsePass | EvaluationResponseBlock
```

The discriminator is the `decision` field.

#### `EvaluationResponsePass`

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `decision` | `Literal["pass"]` | yes | exactly `"pass"` | |
| `payload` | string | yes | length ≤ same as input field | The (possibly redacted) text the caller should use downstream. On `/check/input` this becomes the prompt content sent to the LLM. On `/check/output` this becomes the response delivered to the visitor. |
| `redaction` | `RedactionMetadata \| null` | yes | non-null iff any redaction was applied | Names the recognizers that fired and a count; never the matched values. |

#### `EvaluationResponseBlock`

| Field | Type | Required | Constraints | Notes |
|-------|------|----------|-------------|-------|
| `decision` | `Literal["block"]` | yes | exactly `"block"` | |
| `rule_name` | `RuleName` | yes | drawn from the closed vocabulary below | Which rail fired. |
| `action` | `Action` | yes | drawn from the closed vocabulary below | What the backend should do next. |
| `refusal_text` | string \| null | yes | non-null only when `action="tenant_refusal"` | Carries the tenant's configured refusal language and tone (FR-006). |

**Critical structural property**: `EvaluationResponseBlock` MUST NOT carry the original payload (or any substring of it). This is enforced by the schema, the unit tests, and the constitution re-check in `plan.md`. A block carries `rule_name`, `action`, and optionally the tenant's `refusal_text` — nothing else.

### `TenantConfig`

Per-tenant rail configuration. Supplied by the backend on every call (the sidecar does not persist or cache tenant config — Principle X / spec FR-011).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `allowed_topics` | `list[string] \| null` | no | When null/absent, no allowed-topics rail is enforced. Each topic is a short label the rail engine matches against (e.g., `"product_questions"`, `"pricing"`, `"hours"`). |
| `refusal_persona` | `RefusalPersona \| null` | no | When null/absent, a platform-default refusal is used. |
| `escalation_triggers` | `list[EscalationTrigger] \| null` | no | When null/absent, no tenant-side escalation triggers fire (platform escalation rules still apply via NeMo's standard flows). |

The schema is treated as well-formed by the sidecar — validation lives in the admin app (spec assumption + FR-011). If the sidecar nonetheless receives an unparseable `tenant_config`, the orchestrator's fail-closed branch returns `decision="block"`, `rule_name="config_error"`, `action="fallback_response"` (Principle VI / spec FR-009).

### `RefusalPersona`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `voice` | string | yes | Short label, e.g., `"formal"`, `"friendly"`, `"terse"`. |
| `template` | string | yes | The text the rail engine uses when composing a tenant-refusal block response. May contain `{reason}` and `{topic}` placeholders that the engine fills in. |

### `EscalationTrigger`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `kind` | `Literal["keyword", "intent"]` | yes | Whether the trigger matches a keyword/phrase or a structural intent pattern. |
| `value` | string | yes | The keyword or intent pattern. |

### `RedactionMetadata`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `recognizers_fired` | `list[RecognizerName]` | yes | Deduplicated; order-stable for testing. |
| `match_count` | integer ≥ 0 | yes | Total number of redactions performed on the payload. |

**Critical privacy property**: `RedactionMetadata` MUST NOT carry matched values, original substrings, or character offsets of the matches. Span attributes (`redaction.recognizers_fired`, `redaction.match_count`) mirror this exactly (Principle IX / spec FR-014).

## Closed-vocabulary value sets

### `Decision`

```
Literal["pass", "block"]
```

No other values. Reviewed in PR if extended.

### `RuleName`

The set of values the sidecar may return on a `block`:

| Value | Tier | Meaning |
|-------|------|---------|
| `prompt_injection` | platform | Visitor message attempts to override the system prompt or invoke developer/admin mode. |
| `jailbreak` | platform | Visitor message matches a known jailbreak frame (DAN, alter-ego, hypothetical-evil, encoded payload). |
| `cross_tenant` | platform | Message or response references another tenant's data, system prompt, or internal state. |
| `off_topic` | tenant | Message falls outside the tenant's `allowed_topics` list. |
| `escalation_trigger` | tenant | Message matches one of the tenant's `escalation_triggers`. |
| `engine_error` | fail-closed | Rail engine raised during evaluation. Fail-closed (Principle VI). |
| `config_error` | fail-closed | Tenant config malformed despite upstream validation (defensive). Fail-closed. |

### `Action`

The closed vocabulary of actions returned alongside a `block`:

| Value | Used by | Meaning to the backend |
|-------|---------|------------------------|
| `safe_refusal` | `prompt_injection`, `jailbreak`, `cross_tenant` | Return a platform-default safe refusal to the visitor. |
| `tenant_refusal` | `off_topic` | Return the tenant's configured refusal (the response carries `refusal_text`). |
| `escalate` | `escalation_trigger` | Hand the conversation off to a human; do not let the agent attempt an answer. |
| `fallback_response` | `engine_error`, `config_error` | Return a fixed platform fallback ("sorry, something went wrong") to the visitor. |

Adding a new `Action` value is a typed-vocabulary change reviewed in PR alongside the backend's handler for it. Backend's `guardrail_service.py` MUST raise on receiving an unknown `Action` (no silent ignore — Principle VI).

### `RecognizerName`

Drawn from the deployed recognizer set (see [research.md §Decision 2](./research.md#decision-2--pii-recognizer-choice)):

```
Literal[
  "EMAIL_ADDRESS",
  "PHONE_NUMBER",
  "CREDIT_CARD",
  "US_SSN",
  "GENERIC_BEARER_TOKEN",
  "HOSTED_LLM_API_KEY_ANTHROPIC",
  "HOSTED_LLM_API_KEY_OPENAI",
]
```

Recognizer additions are reviewed in PR; the typed `Literal` makes them appear as a code diff rather than an opaque string.

## Internal-only entities

These do not cross the HTTP boundary but are essential to reason about the sidecar's behavior.

### `RailsRulesetVersion`

A short content hash of the union of `guardrails/config/*.yaml` files, computed at container build time and baked into `guardrails/app/version.py`. Emitted as `guardrails.rails_version` on every span (Principle VII / spec FR-013). Format: 12 hex characters of SHA-256 of the concatenated, sorted-by-filename YAML content.

### `EvaluationSpan`

The OpenTelemetry span emitted for each evaluation. Not a wire entity; just the set of attributes the implementation must set:

| Attribute | Type | Source |
|-----------|------|--------|
| `tenant_id` | string | Request body. |
| `tenant_id_missing` | bool | True iff the request had no `tenant_id` — anomaly path. |
| `guardrails.endpoint` | string | `"input"` or `"output"`. |
| `guardrails.decision` | string | `"pass"` or `"block"`. |
| `guardrails.rule_name` | string | Set iff `decision == "block"`. |
| `guardrails.latency_ms` | float | Wall-clock measured around the orchestrator's evaluate call. |
| `guardrails.rails_version` | string | The `RailsRulesetVersion`. |

Plus, when redaction occurred, a child span `guardrails.redaction` with:

| Attribute | Type |
|-----------|------|
| `redaction.recognizers_fired` | string list |
| `redaction.match_count` | integer |

No span attribute carries a substring of `message`, `llm_response`, or any redacted value (Principle IX).

## State transitions

The sidecar is **stateless** — there are no entities with lifecycle across requests. Each request is evaluated independently; the only persistent state is the loaded rails engine and the loaded recognizer set, which are immutable for the lifetime of the process.

A single evaluation's internal state transitions are:

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
   │ schema validate (FastAPI)│──── invalid ───► 422 (structured)
   └─────────────┬───────────┘
                 │ well-formed
                 ▼
   ┌─────────────────────────┐
   │ orchestrator evaluate   │
   │   ├─ platform rails     │──── any rail fires ─► block(rule_name, action)
   │   ├─ tenant rails       │──── any rail fires ─► block(rule_name, action)
   │   ├─ redaction (Presidio)│──── redactions made ─► pass(redacted_payload, RedactionMetadata)
   │   └─ no rail fires       │────────────────────► pass(payload, redaction=null)
   └─────────────┬───────────┘
                 │ any exception
                 ▼
   ┌─────────────────────────┐
   │ fail-closed wrapper     │────► block(rule_name="engine_error",
   │  (Principle VI)         │             action="fallback_response")
   └─────────────────────────┘
```

The fail-closed wrapper catches **every** path through the orchestrator. There is no return-`None`-and-log branch anywhere — only `pass(...)` or `block(...)`.
