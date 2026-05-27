# Feature Specification: Guardrails Sidecar

**Feature Branch**: `002-guardrails-sidecar`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "Specify the guardrails sidecar for the Concierge project. The sidecar enforces safety rails on every chat turn that touches the LLM. Two layers of rails: platform rails every tenant inherits and cannot disable, and tenant rails each tenant configures via the admin UI. Two endpoints: one screens the visitor's incoming message before it reaches the LLM; the other screens the LLM's outgoing response before it reaches the visitor. Both return a pass/block decision; pass may carry a redacted payload, block carries the name of the rail that fired and an action the backend should take. Service credential required on every call. Platform rails cover prompt-injection refusal, jailbreak detection, cross-tenant data refusal, and PII redaction (including project-specific recognizers for hosted-LLM API keys). Tenant rails cover allowed topics, persona / refusal tone, and escalation triggers. Tenant configs are validated at write-time by the admin app, so the sidecar never sees malformed configs. Fail-closed under any internal error. p95 latency under 100ms. Every evaluation emits an observability span; redactions are logged by recognizer name but never by matched value."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Block a hostile visitor message before it reaches the LLM (Priority: P1)

A visitor sends a message that attempts to override the agent's instructions, impersonate the assistant, claim admin or developer access, invoke a known jailbreak pattern, or ask about another tenant's data. Before the message ever reaches the LLM, the sidecar inspects it, fires the matching platform rail, and tells the backend to return a safe refusal instead of letting the model see the message. The visitor experiences a clean, in-character refusal; the model is never exposed to the attempted manipulation; the team sees in telemetry exactly which rail caught it.

**Why this priority**: Platform safety is the entire reason the sidecar exists. Without this story, the LLM can be manipulated into leaking system prompts, cross-tenant data, or unsafe behavior, which is a security incident, not a feature gap. Every other story is in service of this one.

**Independent Test**: Send a representative set of hostile messages (one per platform-rail category) to the input-screening endpoint with a valid credential and a typical tenant configuration. Confirm each is blocked, the block response names the specific rail that fired, and an action is provided that tells the backend how to handle the refusal. Confirm that for a benign message under the same conditions the decision is "pass".

**Acceptance Scenarios**:

1. **Given** a visitor message that attempts to override the agent's instructions or unlock a developer/admin mode, **When** the sidecar screens it, **Then** the decision is "block", the response names the prompt-injection rail, and the action tells the backend to return a safe refusal.
2. **Given** a visitor message matching a known jailbreak framing (alter ego, hypothetical evil persona, encoded payload, etc.), **When** the sidecar screens it, **Then** the decision is "block", the response names the jailbreak-detection rail, and an action is provided.
3. **Given** a visitor message referencing another tenant by name, asking about another tenant's internal state, or otherwise crossing the tenant boundary, **When** the sidecar screens it, **Then** the decision is "block", the response names the cross-tenant rail, and an action is provided.
4. **Given** a benign in-scope visitor message, **When** the sidecar screens it, **Then** the decision is "pass" and the payload returned is the input message (possibly with PII redacted — see Story 2).

---

### User Story 2 — Strip PII from anything that reaches the LLM or any log (Priority: P1)

A visitor pastes their email, phone number, credit card, or — accidentally — an API key into the chat. Before the message reaches the LLM, the sidecar detects the sensitive value and replaces it in the payload with a placeholder. The LLM works from the redacted text; the original sensitive value never leaves the sidecar boundary. The same applies to the LLM's outgoing response: if the model has somehow produced something that looks like PII (e.g., echoing back what the visitor pasted), it is redacted again before being returned to the visitor. Telemetry records that redaction happened and which recognizer fired, but never the matched value itself.

**Why this priority**: Redaction is the only thing standing between a visitor's casually-pasted credit card and a chat-history store or an LLM provider's logs. If it doesn't work, every other safety claim about the product is undercut. Project-specific recognizers (e.g., for hosted-LLM API key prefixes the team itself uses internally) protect against the specific failure mode of an engineer accidentally pasting a key into their own dev chat.

**Independent Test**: Submit messages containing each supported sensitive value type — email address, phone number, credit card number, government-ID-style number, generic bearer token, and the project's named hosted-LLM API key formats — to the input-screening endpoint. Confirm the returned payload has each sensitive value replaced with a stable placeholder rather than the original text. Confirm the corresponding telemetry record names the recognizer but does not include the matched value. Repeat for the output-screening endpoint with the same payload contents.

**Acceptance Scenarios**:

1. **Given** a visitor message that contains an email address, phone number, credit card number, government-ID-style number, or generic bearer token, **When** the sidecar screens the input, **Then** the decision is "pass" and the returned payload has each sensitive value replaced with a placeholder.
2. **Given** a visitor message contains a value matching a project-specific recognizer for a hosted-LLM API key, **When** the sidecar screens the input, **Then** the value is redacted from the payload before it can reach the LLM.
3. **Given** an LLM response contains any of the sensitive value types above, **When** the sidecar screens the output, **Then** the value is redacted from the payload before it can reach the visitor.
4. **Given** any redaction has occurred, **When** the team inspects telemetry or logs for that evaluation, **Then** the record names which recognizer fired but does not contain the matched value.

---

### User Story 3 — Enforce per-tenant rails on top of platform rails (Priority: P1)

A tenant administrator configures, through the admin app, which topics the agent is allowed to discuss, the agent's persona and refusal tone, and a list of keywords or intent patterns that force escalation to a human instead of letting the agent attempt an answer. On every chat turn for that tenant, the sidecar applies these tenant rails in addition to the always-on platform rails. If a visitor's message falls outside the allowed topics, the sidecar blocks it and returns the tenant's configured refusal language and tone. If a visitor's message matches the tenant's escalation triggers, the sidecar blocks it with an action that tells the backend to escalate rather than answer.

**Why this priority**: Multi-tenant customization is a core product capability. Without per-tenant rails, every tenant either gets the same generic guardrails (too restrictive for some, too permissive for others) or has to be served by a different deployment, which is operationally untenable. P1 because shipping the sidecar without it makes the product unsellable to most prospective tenants.

**Independent Test**: Configure two distinct tenant rail sets — different allowed topics, different refusal personas, different escalation triggers — and submit (a) an on-topic message under tenant A, (b) the same message under tenant B where it is off-topic, and (c) a message containing tenant A's escalation trigger. Confirm tenant A's message passes, tenant B's is blocked with tenant B's refusal voice, and the escalation case blocks with the escalation action regardless of whether the message would otherwise have been on-topic.

**Acceptance Scenarios**:

1. **Given** a tenant configures a list of allowed topics, **When** a visitor sends a message clearly inside that list, **Then** the sidecar lets it pass (subject to platform rails).
2. **Given** a tenant configures a list of allowed topics, **When** a visitor sends a message outside that list, **Then** the sidecar blocks the message and the block carries the tenant's configured refusal language and tone.
3. **Given** a tenant configures escalation-trigger keywords or intent patterns, **When** a visitor's message matches a trigger, **Then** the sidecar blocks the message with an action that tells the backend to escalate to a human handoff rather than attempt an agent answer.
4. **Given** two tenants with different rail configurations, **When** they each send the same visitor message, **Then** the sidecar's decisions reflect each tenant's own configuration independently.

---

### User Story 4 — Fail closed under any internal error (Priority: P1)

The sidecar's rail engine throws while evaluating a message. Or the tenant config can't be fetched. Or the sidecar itself runs into an unexpected internal error. In every such case, the sidecar does not "let it through to be safe" — it returns a block decision, names the failure explicitly, and provides an action that tells the backend to return a fallback response to the visitor. The team would much rather have a chat turn show a polite "sorry, something went wrong" than risk an unsafe message reaching the LLM or an unsafe response reaching the visitor because the safety check silently no-op'd.

**Why this priority**: The fail-closed posture is a security property of the whole system, not a polish item. Getting it wrong silently downgrades safety under exactly the conditions (load, regression, dependency outage) when safety matters most.

**Independent Test**: Inject three failure conditions — a rail-engine exception during evaluation, a tenant-config fetch failure, and a generic unexpected internal error. For each, confirm the sidecar's response is a block decision, that it names the failure category as the rule that fired, that the action tells the backend to return a fallback response, and that no part of the original payload is treated as "passed" by default.

**Acceptance Scenarios**:

1. **Given** the rail engine raises an exception while evaluating a message, **When** the sidecar responds, **Then** the decision is "block", the rule name identifies the failure as an engine error, and the action tells the backend to return a fallback response.
2. **Given** the sidecar cannot fetch or load the tenant's rail configuration, **When** the sidecar responds, **Then** the decision is "block", the rule name identifies the failure as a config error, and the action tells the backend to return a fallback response.
3. **Given** a generic unexpected internal error occurs in the sidecar, **When** the sidecar responds, **Then** the decision is still "block" — there is no silent "pass" path under any failure mode.
4. **Given** the sidecar has no tenant configuration on file for the requested tenant, **When** the sidecar evaluates the message, **Then** it treats the tenant as having no tenant rails configured and still applies all platform rails to the message.

---

### User Story 5 — Authenticate every call as a trusted internal caller (Priority: P1)

The sidecar is only meant to be called by the backend. Every call must present a service credential issued from the project's secrets store. A request without a valid credential is rejected up front — no rail evaluation happens, nothing of value is returned, and the response carries no information about why the credential failed. This protects the sidecar from being used outside the chat pipeline and gives the team a clean signal when wiring is wrong.

**Why this priority**: Without authentication, anything reachable on the sidecar's network can poke at the rail engine, learn from block/pass patterns, or otherwise misuse the surface. Auth is mandatory for the first deployable version, not later hardening.

**Independent Test**: Call each endpoint with (a) a valid credential, (b) no credential, and (c) a malformed credential. Confirm only the valid-credential call reaches rail evaluation; the other two are rejected up front with a single opaque authentication-failure response shape that does not let the caller tell the failure modes apart.

**Acceptance Scenarios**:

1. **Given** a caller presents a valid, current service credential, **When** the caller hits either endpoint, **Then** the request is processed normally and a pass/block decision is returned.
2. **Given** a caller omits the credential entirely, **When** the caller hits either endpoint, **Then** the request is rejected as unauthenticated and no rail evaluation occurs.
3. **Given** a caller presents an invalid or expired credential, **When** the caller hits either endpoint, **Then** the request is rejected as unauthenticated using the same response shape as the missing-credential case.

---

### User Story 6 — Stay observable on every evaluation (Priority: P2)

When a chat turn behaves oddly — a legitimate message gets blocked, an unsafe message slipped through, a redaction looks wrong, latency spiked — the team needs to find the exact rail evaluation that drove the outcome. Every evaluation emits a distributed-tracing span carrying the tenant, which endpoint was hit, the decision, the rule that fired on a block, the per-call latency, and the version of the rails ruleset in force. Spans carry no PII: when redaction happened the span names the recognizer that fired, never the matched value, and logs follow the same rule.

**Why this priority**: Without this telemetry, every rail incident is debugged by guessing. It's not P1 because the sidecar can still serve traffic without it, but it is required to operate the system responsibly and to answer post-incident questions.

**Independent Test**: Trigger one pass, one platform-rail block, one tenant-rail block, and one PII-redaction-bearing pass; locate the four corresponding trace spans and confirm each carries tenant, endpoint, decision, rule name (when blocked), latency, and rails version. Confirm none of the spans contain the matched PII value.

**Acceptance Scenarios**:

1. **Given** the sidecar has evaluated a request, **When** the operator inspects the trace, **Then** the span carries tenant identifier, endpoint (input or output), decision, rule name (when blocked), per-call latency, and rails-ruleset version.
2. **Given** an evaluation involved PII redaction, **When** the operator inspects the trace and the logs for that evaluation, **Then** they identify which recognizer(s) fired but do not contain the matched values.
3. **Given** the rails ruleset has been updated and redeployed, **When** a subsequent evaluation runs, **Then** the rails-version field on the span reflects the new ruleset and differs from spans from the previous version.

---

### User Story 7 — Stay fast enough not to be felt (Priority: P2)

The sidecar sits on the critical path of every chat turn that reaches the LLM — once for the input, again for the output. If it is slow, the visitor feels it as a slow chat. The sidecar's per-call latency stays low enough at the 95th percentile that it does not become the dominant contributor to chat-turn latency under normal load.

**Why this priority**: A safe but slow guardrails layer is operationally fine for a demo and unacceptable in production traffic. Not P1 only because the first usable version of the service can ship slightly slower and be optimized; the property still has to hold before real users are on it.

**Independent Test**: Run a representative mix of input and output evaluations across several tenant configurations under realistic concurrency. Confirm that 95% of evaluations complete well within the sidecar-side share of the chat-turn latency budget agreed with the backend.

**Acceptance Scenarios**:

1. **Given** a representative mix of input and output evaluations under realistic concurrency, **When** the 95th-percentile latency of the sidecar is measured, **Then** it stays within the share of the chat-turn latency budget agreed with the backend, so the sidecar is not the dominant source of chat-turn latency.

---

### Edge Cases

- **Tenant configuration not on file at all** — treated as "no tenant rails configured"; platform rails still apply, and the call still proceeds normally rather than being treated as an error.
- **Tenant configuration present but with no allowed-topics list, no escalation triggers, or no refusal persona set** — those tenant rails are simply not enforced for that tenant; platform rails still apply.
- **Visitor message is empty or whitespace-only** — passed through as input (subject to platform rails), since blocking empty input is not a safety concern; whether to send empty input to the LLM is the backend's call.
- **Outgoing LLM response is empty** — passed through as output; same reasoning as above.
- **Sensitive value spans across the boundary of two redaction matches** (e.g., a credit card number split by a stray newline) — the model treats the input as it sees it; if the value is recognized by the rail engine it is redacted, otherwise it is not. Recognizers' coverage is the rail engine's responsibility, not the sidecar contract's.
- **Same sensitive value appears multiple times in the same message** — every occurrence is replaced; the telemetry record lists the recognizer once per evaluation, not once per occurrence.
- **Cross-tenant rail and tenant allowed-topics disagree** — platform rails always take precedence; a cross-tenant reference is blocked even if the tenant configured a permissive topic list.
- **Fail-closed during the output check** — when the sidecar cannot safely evaluate the LLM's outgoing response, the response does not reach the visitor; the backend returns a fallback response instead. This is intentional even though it costs the visitor a real answer in some failure cases.
- **Caller retries an authentication-failed request** — every retry returns the same opaque rejection; no information is leaked about whether the credential is closer to or further from valid.
- **A tenant edits their rail configuration mid-conversation** — the next evaluation uses whatever configuration the backend supplies in the request; the sidecar does not cache config across calls.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The sidecar MUST expose two evaluation endpoints — one that screens an incoming visitor message before it reaches the LLM, one that screens the LLM's response before it reaches the visitor — and each MUST accept a tenant identifier, the content under evaluation, and the tenant's rail configuration as inputs.
- **FR-002**: Every evaluation MUST return either a "pass" decision (with the possibly-redacted payload the caller should use) or a "block" decision that names the specific rail that fired and supplies an action telling the caller how to handle the block.
- **FR-003**: The sidecar MUST enforce a set of platform safety rails on every evaluation — covering at minimum prompt-injection refusal, jailbreak detection, cross-tenant data refusal, and PII redaction — and tenants MUST NOT be able to disable, weaken, or bypass these rails through their tenant configuration.
- **FR-004**: The sidecar MUST apply each tenant's configured tenant-level rails — at minimum, allowed topics, refusal persona/tone, and escalation triggers — in addition to the platform rails, using the tenant configuration supplied in the request.
- **FR-005**: The sidecar MUST redact, before any payload reaches the LLM or any log, values matching project-supported sensitive-data recognizers including at minimum email addresses, phone numbers, credit card numbers, government-ID-style numbers, generic bearer tokens, and project-specific recognizers for hosted-LLM API key formats used by the project.
- **FR-006**: When a tenant-rail allowed-topics violation triggers a block, the block response MUST carry refusal language and tone derived from the tenant's configured persona.
- **FR-007**: When a tenant-rail escalation trigger fires, the block response MUST supply an action that instructs the backend to hand the conversation off to a human rather than attempt an agent answer.
- **FR-008**: The sidecar MUST authenticate every request using a service credential issued by the project's secrets store and MUST reject every other request with a single opaque authentication-failure response that does not distinguish missing, expired, or otherwise invalid credentials.
- **FR-009**: The sidecar MUST treat any internal error during evaluation — including rail-engine failures, tenant-configuration fetch/load failures, and any other unexpected internal exception — as a block, naming the failure as the rule that fired and supplying a fallback-response action. There MUST NOT be any silent "pass" path on internal error.
- **FR-010**: When the sidecar has no tenant configuration on file for the requested tenant, it MUST treat the tenant as having no tenant rails configured and continue to apply all platform rails to the request normally.
- **FR-011**: The sidecar MUST NOT validate the structure of incoming tenant configurations in the request path — tenant-configuration validity is enforced upstream at config-write time, and the sidecar treats any configuration it receives as well-formed.If a malformed configuration causes an internal error despite upstream validation, the fail-closed rule in FR-009 applies.
- **FR-012**: The 95th-percentile latency of either endpoint MUST stay within the share of the chat-turn latency budget agreed with the backend, so the sidecar does not become the dominant source of chat-turn latency under normal load.
- **FR-013**: Every evaluation MUST emit a distributed-tracing span carrying the tenant identifier, which endpoint was evaluated (input or output), the decision, the rule name on a block, the per-call latency, and the version of the rails ruleset in force.
- **FR-014**: When an evaluation performs PII redaction, both the tracing span and any log entry for that evaluation MUST identify which recognizer(s) fired but MUST NOT contain the matched value.
- **FR-015**: The sidecar MUST NOT classify visitor intent, retrieve from the tenant's content store, or persist conversation history — those responsibilities live in other components of the system and are explicitly out of scope here.

### Key Entities *(include if feature involves data)*

- **Evaluation Request (Input)** — what the backend sends before the LLM call. Carries the tenant identifier, the visitor's message, and the tenant's rail configuration.
- **Evaluation Request (Output)** — what the backend sends after the LLM call. Carries the tenant identifier, the LLM's draft response, and the tenant's rail configuration.
- **Evaluation Response** — what the sidecar returns. Either a "pass" with the (possibly redacted) payload the caller should use, or a "block" with the rule name that fired and an action describing how the backend should handle the block.
- **Platform Rail** — a safety rail that runs on every evaluation regardless of tenant. The platform rail set in scope here covers prompt injection, jailbreak detection, cross-tenant data refusal, and PII redaction.
- **Tenant Rail Configuration** — the per-tenant rail settings supplied by the backend on each evaluation. In scope: allowed topics, refusal persona/tone, escalation triggers. Validated upstream at config-write time, treated as well-formed by the sidecar.
- **Sensitive Value Recognizer** — a named pattern the sidecar uses to identify a class of sensitive value for redaction (e.g., "email", "credit-card", "hosted-llm-api-key:anthropic"). Identified by name in telemetry; its matched values never appear in telemetry or logs.
- **Block Action** — the value attached to a block decision that tells the backend what to do next. The set in scope includes at minimum "return a safe refusal", "return the tenant's configured refusal", "escalate to a human handoff", and "return a fallback response" (used by fail-closed paths).
- **Rails Ruleset Version** — an identifier for the version of the platform-rail logic currently in force. Recorded on every tracing span so the team can correlate evaluations with deployed rail versions.
- **Service Credential** — the token issued by the project's secrets store that authenticates the backend's sidecar client to the sidecar. Verified on every request.
- **Evaluation Trace Span** — the distributed-tracing record emitted for each evaluation. Carries tenant, endpoint, decision, rule name (on block), latency, rails version, and recognizer names (when redaction occurred). Carries no matched sensitive values.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of chat turns that reach the LLM pass through the sidecar's input check first, and 100% of LLM responses returned to a visitor pass through the sidecar's output check first — there is no production path that reaches or returns from the LLM without an evaluation.
- **SC-002**: Across a representative red-team probe set covering prompt injection, jailbreaks, cross-tenant references, and known PII patterns, the sidecar blocks the unsafe categories and redacts the sensitive-value categories at a rate that meets the team's agreed safety thresholds, and a benign control set passes through unchanged.
- **SC-003**: No sensitive value matched by any supported recognizer appears in any log line, tracing span, or persisted payload the LLM provider receives — verified by routine inspection during deployment and on demand thereafter.
- **SC-004**: The 95th-percentile latency of sidecar evaluation stays within its agreed share of the chat-turn budget under normal production load, so the sidecar is not the dominant contributor to chat-turn latency.
- **SC-005**: Every recorded internal error in the sidecar in production corresponds to a "block" decision being returned to the caller — zero internal errors result in a silent "pass".
- **SC-006**: Zero unauthenticated callers reach rail evaluation: every call without a valid credential is rejected before any rail runs, and the rejection response is indistinguishable across the missing, expired, and otherwise-invalid cases.
- **SC-007**: The sidecar applies whatever configuration the backend supplies in each request, with no caching.
- **SC-008**: Each rail evaluation in production is uniquely attributable to (a) a tenant, (b) an endpoint, (c) a decision and rule, and (d) a specific rails-ruleset version, via its tracing span — no production evaluation is unattributable.

## Assumptions

- The backend is the only legitimate caller of the sidecar. Network placement and the service credential together enforce this; the sidecar does not need a separate visitor-facing surface.
- The admin app validates tenant rail configuration when an administrator saves it. The sidecar therefore receives only well-formed configurations and does not duplicate that validation in the hot path. If a malformed configuration ever reaches the sidecar despite this, it falls under the "internal error → block fail-closed" rule.
- The platform rails listed in scope here (prompt injection, jailbreak detection, cross-tenant references, PII redaction) are the rails in this delivery. Adding a future platform rail is a normal change to this service rather than a new component.
- The set of supported sensitive-value recognizers is the project's curated set and is governed alongside the rails themselves; specific tenant-supplied recognizers are not in scope for this delivery beyond the project-defined hosted-LLM API key recognizers.
- Per-call rail evaluation does not need to persist any state between calls — the tenant configuration is supplied on each request, the recognizers are part of the deployed image, and conversation history is owned by the backend, not the sidecar.
- Tracing infrastructure (distributed tracing collector, log aggregation) and a secrets store for service credentials are platform-level capabilities and are consumed, not built, by this service.
- The exact share of the chat-turn latency budget the sidecar is permitted to consume is negotiated with the backend and recorded alongside the integration; the spec preserves the property ("not the dominant source of latency"), not a specific millisecond figure.
- Intent classification is performed elsewhere (in the classifier service), retrieval from a tenant's content store is performed elsewhere (in the RAG pipeline), and conversation history is owned elsewhere (in the session-memory store). The sidecar consumes none of these and provides none of them.
- The block actions returned to the backend are a closed, agreed vocabulary (safe refusal, tenant-configured refusal, escalate to human, fallback response). The backend is responsible for mapping each action to the actual visitor-facing behavior; the sidecar's job ends at returning the action name.
- Dependency management uses uv with a pyproject.toml per service. No requirements.txt.
