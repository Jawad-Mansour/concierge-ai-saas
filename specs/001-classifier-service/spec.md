# Feature Specification: Classifier Service

**Feature Branch**: `001-classifier-service`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "Specify the classifier service for the Concierge project. The classifier is the routing brain of the chat pipeline. It receives every incoming visitor message and predicts one of five intent classes — SPAM, FAQ, CONTACT_LEAD, HARD_QUESTION, UNKNOWN — so the backend's router can drop spam, answer from CMS, capture a lead, escalate to the agent, or fall back. One HTTP endpoint (POST /predict) called by the backend's classifier client, authenticated by a Vault-issued service credential, with p95 latency under 50ms. The shipped model is one of three trained offline in Colab (classical sklearn, small ONNX deep model, or LLM zero-shot) and pinned by SHA-256 in a model card. Tenant-agnostic by design, observable via OTel spans, gated in CI by a macro-F1 evaluation against a held-out set."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Route a routine visitor message in time for the chat turn (Priority: P1)

A visitor types a message into the chat widget on a tenant's site. The backend router needs to decide, before doing anything else, whether to drop it, answer it cheaply from the tenant's CMS, treat it as a lead, or hand it to the agent. The classifier provides that single decision in a fraction of the chat-turn budget, so the visitor sees a coherent reply without a perceptible delay regardless of how the router ends up handling the message.

**Why this priority**: This is the entire reason the service exists. Without a fast, reliable classification call, the router has no way to keep the majority of traffic off the expensive agent path, and the chat-turn latency budget collapses. Every other capability of the service is in service of this one.

**Independent Test**: Send a representative spread of visitor messages (one per class) to the prediction endpoint with a valid service credential and confirm that (a) each call returns a class drawn from the five-class set and a confidence in [0, 1], (b) the call completes well within the chat-turn latency budget for short messages, and (c) the response is deterministic for identical input within a deployed model version.

**Acceptance Scenarios**:

1. **Given** a visitor message that is clearly junk advertising, **When** the router asks the classifier for a prediction, **Then** the response identifies the message as spam with high confidence so the router can drop it silently.
2. **Given** a visitor question that asks a single factual thing the tenant's CMS can answer (e.g., business hours), **When** the router asks the classifier for a prediction, **Then** the response identifies the message as an FAQ so the router can answer deterministically without invoking the agent.
3. **Given** a visitor message expressing buying interest or sharing contact details, **When** the router asks the classifier for a prediction, **Then** the response identifies the message as a contact-lead so the router can trigger the lead-capture flow.
4. **Given** a multi-part or ambiguous visitor message that requires reasoning across sources, **When** the router asks the classifier for a prediction, **Then** the response identifies the message as a hard question so the router can hand it to the agent.
5. **Given** a message the model cannot confidently place in any of the four substantive classes, **When** the router asks the classifier for a prediction, **Then** the response is the explicit unknown class rather than a low-confidence guess, so the router escalates to the agent instead of acting on noise.
6. **Given** the classifier responds within the typical-message latency budget, **When** the router aggregates 95th-percentile latency across a representative day of traffic, **Then** the classifier's contribution stays within the per-turn budget agreed with the router (so it does not become the bottleneck of the chat turn).

---

### User Story 2 — Authenticate every prediction call as a trusted internal caller (Priority: P1)

The classifier sits behind an internal network boundary and is only meant to be called by the backend's classifier client. Every request must present a service credential issued from the project's secrets store; anything else is rejected without leaking why. This prevents accidental use from other services, untrusted networks, or misconfigured local environments and gives the team a clean signal in logs when something is wired up incorrectly.

**Why this priority**: Without authentication, any service in the cluster (or anything that reaches the network the classifier listens on) could shape its predictions into the chat pipeline. Auth is mandatory for the very first deployable version, not a follow-on hardening task.

**Independent Test**: Call the prediction endpoint three times — once with a valid credential, once with a missing credential, once with a malformed credential — and confirm only the valid call returns a prediction; both invalid calls return an authentication-failure response that does not reveal whether the credential was missing, expired, or wrong.

**Acceptance Scenarios**:

1. **Given** a caller presents a valid, current service credential, **When** the caller requests a prediction, **Then** the request is processed normally and a prediction is returned.
2. **Given** a caller omits the credential entirely, **When** the caller requests a prediction, **Then** the request is rejected as unauthenticated and the response body does not describe what was missing.
3. **Given** a caller presents an invalid or expired credential, **When** the caller requests a prediction, **Then** the request is rejected as unauthenticated using the same response shape as the missing-credential case.

---

### User Story 3 — Stay observable and traceable in production (Priority: P2)

When a chat turn behaves oddly — an answer is wrong, a lead was missed, latency spiked — the team needs to find the exact prediction that drove the router's decision and know which model version produced it. Every prediction emits a distributed-tracing span that carries the tenant under which the call was made, the predicted class, the confidence, the call's latency, and the hash of the model that produced it.

**Why this priority**: Without this telemetry, root-causing a routing mistake means guessing. With it, any prediction in production is reproducible to a specific model artifact and a specific tenant context. It's not P1 because the service can still serve traffic without it, but it is required to operate the service responsibly.

**Independent Test**: Issue a prediction call and locate the corresponding distributed-tracing span. Confirm the span contains the tenant identifier passed in the request, the predicted class returned, the confidence returned, the measured per-call latency, and the model hash. Confirm a second call against a different deployed model version produces a span whose model-hash field differs.

**Acceptance Scenarios**:

1. **Given** the service has produced a prediction, **When** the operator inspects the trace for that request, **Then** the span includes tenant, predicted class, confidence, latency, and model hash.
2. **Given** a new model version has been deployed, **When** a prediction is made under the new version, **Then** the model-hash field on the span reflects the new artifact and differs from spans from the previous version.

---

### User Story 4 — Fail loudly at boot, fail gracefully under load (Priority: P2)

If the model artifact on disk does not match the hash the service expects, the service must refuse to start so the wrong model never silently serves traffic. If, after starting, a single prediction takes too long, the service must return the explicit unknown class rather than blocking the chat turn, and the slow call must be visible in telemetry so operators can investigate.

**Why this priority**: The cost of a wrong model silently shipping is much higher than the cost of a noisy crash loop, and the cost of a slow individual prediction stalling every chat turn is much higher than returning the safe escalation fallback for that one turn.

**Independent Test**: Run two failure drills. (1) Swap the model artifact on disk with one whose hash does not match the recorded value and start the service; confirm the service exits non-zero with a clear error rather than serving requests against an unverified file. (2) Force a single prediction to exceed the hard timeout; confirm the response is the unknown class with confidence zero, and that the corresponding trace span is marked as a degraded prediction.

**Acceptance Scenarios**:

1. **Given** the model artifact on disk does not match its recorded hash, **When** the service starts, **Then** the service refuses to begin serving traffic, logs a hash-mismatch error, and exits with a non-zero status so the orchestrator restarts it visibly.
2. **Given** the model file is missing or corrupt, **When** the service starts, **Then** the service refuses to begin serving traffic, logs a load error, and exits with a non-zero status.
3. **Given** a single inference exceeds the hard timeout, **When** the service responds to the caller, **Then** the response is the unknown class with confidence zero, a timeout event is logged, and the trace span is marked as a degraded prediction.
4. **Given** a caller sends a malformed request body, **When** the service responds, **Then** the response is a structured bad-request error and no partial prediction is returned.

---

### User Story 5 — Hold a quality bar on every change (Priority: P2)

Whenever the model artifact or the model-serving code is changed, an automated evaluation runs against a committed held-out dataset. If macro-F1 across the five classes drops below the team's recorded threshold, the change cannot land. This protects the router from silent quality regressions that would only show up later as routing mistakes.

**Why this priority**: The classifier is a single point of decision for the entire chat pipeline. A regression here is harder to spot in production than a unit-test failure, so the gate has to live in the change-review process.

**Independent Test**: Open a change that touches the model-serving code or the model artifact. Confirm the evaluation runs automatically as part of the change-review pipeline, that its computed macro-F1 is visible in the pipeline output, and that the change is blocked when the score falls below the recorded threshold.

**Acceptance Scenarios**:

1. **Given** a change touches the model-serving code or the model artifact, **When** the change-review pipeline runs, **Then** the held-out evaluation is executed and its score is reported.
2. **Given** the held-out macro-F1 from a change is below the recorded threshold, **When** the pipeline finishes, **Then** the change is blocked from landing.
3. **Given** the held-out macro-F1 meets or exceeds the threshold, **When** the pipeline finishes, **Then** the gate passes and the change is eligible to land.

---

### User Story 6 — Ship one model across every tenant (Priority: P3)

A single artifact serves every tenant. The classifier never lets the tenant identifier influence the predicted class — it is passed only so traces and rate-limiting can attribute the call. Custom per-tenant routing behavior is expressed in the tenant's guardrails configuration elsewhere in the system, not in the model itself.

**Why this priority**: This is a deliberate design choice that keeps operations simple (one artifact to evaluate, version, and roll out), but it's not a runtime feature a user can observe directly. It's a property the implementation must preserve.

**Independent Test**: Send the same message twice, with two different tenant identifiers, against the same deployed model version, and confirm the predicted class and confidence are the same in both responses.

**Acceptance Scenarios**:

1. **Given** two requests carry the same message text but different tenant identifiers, **When** both are scored by the same deployed model version, **Then** the predicted class and confidence are identical.

---

### Edge Cases

- **Empty or whitespace-only message text** — treated as a malformed request, not as content to classify.
- **Extremely long message text** (well beyond the typical-message size used for the latency target) — must still produce a prediction; the latency target applies to typical-size messages only, and longer inputs may legitimately exceed it without that being considered a service failure, though they still must not exceed the hard timeout.
- **Non-English or mixed-language input** — receives a prediction from whatever class the model judges most likely; if the model is not confident in any substantive class, the unknown fallback applies and the router escalates.
- **Tenant identifier missing from the request** — treated as a malformed request, since downstream tracing and rate-limiting depend on it.
- **Tenant identifier present but unknown to the rest of the system** — the classifier still returns a prediction (it is tenant-agnostic) and lets downstream services decide how to handle the unknown tenant.
- **Confidence reported as exactly zero** — reserved for the timeout-degraded path; predictions on the substantive classes always report a strictly positive confidence.
- **Burst of concurrent requests during a traffic spike** — the service must continue to meet the typical-message latency target on the bulk of calls; if it cannot, slow calls fall through to the timeout-degraded unknown response rather than blocking the chat turn.
- **Model artifact file present but corrupt or truncated** — handled identically to a hash mismatch at boot: refuse to start, exit non-zero.
- **Caller retries an authentication-failed request** — every retry returns the same opaque rejection; no information is leaked about whether the credential is closer to or further from valid.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service MUST expose a single prediction endpoint that accepts a tenant identifier and a message text and returns one predicted class plus a confidence score.
- **FR-002**: The set of possible predicted classes MUST be exactly five: spam, FAQ, contact-lead, hard-question, and unknown.
- **FR-003**: The confidence score returned with every prediction MUST be a value between zero and one inclusive.
- **FR-004**: The service MUST reject any prediction request that does not present a valid service credential issued by the project's secrets store, using a single authentication-failure response shape that does not distinguish missing, expired, or otherwise invalid credentials.
- **FR-005**: The service MUST reject any prediction request whose body is missing required fields, contains an empty or whitespace-only message, or is otherwise malformed, with a structured bad-request response and no partial prediction.
- **FR-006**: The service MUST treat the tenant identifier in the request as opaque routing/tracing metadata only and MUST NOT allow it to change the predicted class or confidence for the same message text under the same deployed model version.
- **FR-007**: The shipped model MUST be a single committed artifact pinned by a cryptographic hash recorded in a model-card document committed alongside the artifact.
- **FR-008**: At startup, the service MUST verify the on-disk model artifact's hash against the recorded value and MUST refuse to begin serving traffic, log the mismatch or load error, and exit with a non-zero status when verification fails.
- **FR-009**: The service MUST enforce a hard per-call inference timeout and, on exceeding it, MUST return the explicit unknown class with confidence zero, log a timeout event, and mark the corresponding trace span as a degraded prediction.
- **FR-010**: The 95th-percentile latency of the prediction endpoint MUST stay within the agreed budget <TBD: agree with Ali> for typical-size messages so that the classifier does not become the bottleneck of the chat turn.
- **FR-011**: Every prediction MUST emit a distributed-tracing span carrying the tenant identifier, the predicted class, the confidence, the per-call latency, and the model hash that produced the prediction.
- **FR-012**: An automated evaluation MUST run against a committed held-out dataset whenever the model artifact or the model-serving code changes, MUST compute macro-F1 across the five classes, and MUST block the change from landing when the score falls below the team's recorded threshold.
- **FR-013**: The service MUST NOT perform PII redaction, content-safety enforcement, or knowledge-base lookup — those responsibilities live in other components of the system and are explicitly out of scope here.
- **FR-014**: The deployed model artifact and the evaluation threshold MUST be reproducibly tied to a recorded modeling decision so that any deployed prediction can be traced back to a known model version and a known quality bar.

### Key Entities *(include if feature involves data)*

- **Prediction Request** — what a caller sends. Carries the tenant identifier (opaque to the model) and the visitor message text. Carries the caller's service credential as a separate authentication element, not as model input.
- **Prediction Response** — what the service returns. Carries the predicted class (one of the five) and the confidence score in [0, 1]. The unknown class with confidence zero is a reserved signal that inference was not completed within the per-call budget.
- **Visitor Message** — the free-text input the model classifies. Tenant-agnostic from the model's point of view; characterized by length (short typical messages drive the latency target) and language (any).
- **Intent Class** — the closed set of five labels the model can return: spam (drop silently), FAQ (answer from CMS), contact-lead (capture lead), hard-question (hand to agent), unknown (escalate as fallback).
- **Model Artifact** — the single file the service loads at startup. Identified by a cryptographic hash that is committed alongside it in a model-card document. Produced offline; not retrained at runtime.
- **Model Card** — the committed document that names the deployed artifact, records its hash, and links the artifact to the modeling decision that justified shipping it.
- **Service Credential** — the token issued by the project's secrets store that authenticates the backend's classifier client to the classifier service. Verified on every prediction request.
- **Held-out Evaluation Dataset** — the committed labeled set used by the automated quality gate. Drives the macro-F1 score that the gate compares against the recorded threshold.
- **Evaluation Threshold** — the recorded minimum macro-F1 score below which a change cannot land. Versioned alongside the rest of the project.
- **Prediction Trace Span** — the distributed-tracing record emitted for each prediction. Carries tenant, predicted class, confidence, latency, and model hash, and may be marked as a degraded prediction on timeout.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For typical-size visitor messages, 95% of prediction calls complete in well under the per-turn chat budget <TBD: agree with Ali> the router negotiates with the classifier, so the classifier is never the bottleneck of a chat turn.
- **SC-002**: The held-out macro-F1 score of the deployed model meets or exceeds the team's recorded threshold at the moment of deployment, and every subsequent change is automatically blocked from landing if it would push that score below the threshold.
- **SC-003**: 100% of authenticated prediction calls in production are reproducible to a specific model artifact via the model-hash field on their trace span; no prediction is unattributable.
- **SC-004**: Zero unauthenticated calls reach inference: every call without a valid credential is rejected before any prediction is performed, and the rejection response does not let the caller distinguish between missing, expired, and otherwise invalid credentials.
- **SC-005**: When a model artifact whose hash does not match the recorded value is placed on disk, the service never serves a prediction against it — the deployment fails visibly at boot rather than silently shipping the wrong model.
- **SC-006**: When a single inference cannot complete in time, the caller receives the explicit unknown fallback (rather than a stalled chat turn) in every such case, and every such case is visible as a degraded span in production telemetry.
- **SC-007**: For the same message text scored under the same deployed model version, the predicted class and confidence are independent of the tenant identifier — verified by a routine check during deployment and on demand thereafter.

## Assumptions

- The backend's classifier client is the only legitimate caller of the prediction endpoint; the endpoint is not exposed to visitors or to other tenants directly. Internal network placement and the service credential together enforce this.
- The classifier client is responsible for retry, circuit-breaking, and fallback policy on the backend side. The classifier service itself does not retry inference; if it cannot answer in time it returns the unknown fallback and lets the router escalate.
- A "typical" visitor message for the purpose of the latency target is a short message (broadly, well under a few hundred characters). Unusually long messages may exceed the typical-message target without being treated as a service failure, but they must still respect the hard timeout.
- The five intent classes are stable for the lifetime of the deployed model. Changing the class set is a model-version change handled through the same evaluation-gated rollout path as any other model update.
- The choice among the three candidate model families (classical baseline, small deep model exported to a portable runtime, hosted-LLM zero-shot baseline) is made offline based on the held-out evaluation and recorded with its justification in the team's decisions document. The shipped artifact is whichever of the three the team selects there.
- Tracing infrastructure (distributed tracing collector, log aggregation) and a secrets store for service credentials are already in place at the platform level and are consumed, not built, by this service.
- The held-out evaluation dataset is treated as a committed asset of the project; changes to it are themselves reviewed, and the recorded threshold moves only deliberately, not as a side effect of changing the data.
- PII redaction happens upstream (in the backend's redaction middleware) before any message reaches the classifier. The classifier does not see raw PII and does not need to know whether redaction has happened.
- Content-safety rails and cross-tenant safety rails are enforced by the guardrails sidecar, not here.
- The classifier has no awareness of any tenant's CMS content; FAQ as a class means "the message looks like the kind of thing CMS can answer", and it is the router's job to attempt the CMS lookup and decide what to do if no answer is found.
- Dependency management uses uv with a pyproject.toml per service. No requirements.txt.
