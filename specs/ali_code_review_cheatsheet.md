<!-- Owner: Ali -->
# Ali Code Review Cheat Sheet

## 1. One-Minute Conceptual Story

My slice is the intelligence layer of the concierge chatbot. The UI sends a visitor message to `POST /chat`; the chat API calls Jana's classifier and guardrails when they are available; then Ali's chat service stores the user message, routes the turn, calls the right tool or agent path, stores the assistant answer, and returns the response to the UI.

The main design idea is a modular monolith:
- API files stay thin.
- Services own business logic.
- Repositories abstract persistence.
- Prompts stay outside service code.
- Tests and evals prove behavior.

## 2. End-to-End Request Flow

1. Charbel's widget sends a chat payload to `POST /chat`.
2. `backend/app/api/chat.py` validates the request with `ChatRequestBody`.
3. If Jana's classifier client exists on `request.app.state`, the API calls `classifier_client.classify(...)`.
4. If Jana's guardrails exist, `screen_input(...)` can block or escalate before Ali's agent responds.
5. `ChatService.handle_message(...)` stores the user message in short-term memory.
6. `ChatService` builds memory context for the current tenant/conversation.
7. `RouterService.route(...)` chooses one of: `drop`, `rag`, `capture_lead`, `escalate`, or `agent`.
8. For RAG, `RagService.search(...)` retrieves tenant-scoped context.
9. For lead capture, `LeadService.capture_lead(...)` validates and deduplicates contact info.
10. For escalation, `EscalationService.escalate(...)` validates tenant, conversation, and visitor session.
11. For complex turns, `AgentService.run(...)` plans tool calls using Anthropic when configured, or a heuristic fallback otherwise.
12. `ChatService` stores the assistant response in memory.
13. If Jana's output guardrail exists, `screen_output(...)` can block or rewrite the final response.
14. The API returns `{ conversation_id, decision, message, trace_id }`.

## 3. Files to Explain First

### `backend/app/api/chat.py`

What it owns:
- The FastAPI `/chat` router.
- Request validation for the UI-facing chat payload.
- Integration points with Jana's classifier and guardrails.
- Runtime composition through `build_chat_service()`.

Important review points:
- `tenant_id` is temporarily accepted in the request body for local/testing flow.
- Final production tenant context should come from widget/auth context, not user-controlled input.
- `build_chat_service()` currently wires demo RAG data, in-memory lead persistence, Redis memory fallback, and Anthropic/heuristic agent planner selection.

### `backend/app/services/chat_service.py`

What it owns:
- The main chat orchestration.
- Saving user and assistant messages.
- Building memory context.
- Calling the router.
- Turning router/agent/RAG results into the final assistant message.

Important review points:
- It does not decide classification itself.
- It accepts Jana's classification result from the API layer.
- If the router decides `agent`, it calls `AgentService` when available.

### `backend/app/services/router_service.py`

What it owns:
- Mapping classifier output to a routing decision.
- Normalizing Jana labels like `SPAM`, `FAQ`, `ACCOUNT_OPS`, `HARD_QUESTION`, and `UNKNOWN`.
- Falling back to agent when confidence is low or classifier output is degraded.

Decision map:
- `spam` with high confidence -> `drop`
- low confidence -> `agent`
- `faq` or `support` -> `rag`
- `sales` or `lead` -> `capture_lead`
- `human_handoff` or `escalate` -> `escalate`
- unknown/unhandled -> `agent`

## 4. Core Services

### RAG

Main files:
- `backend/app/services/rag_service.py`
- `backend/app/repositories/embedding_repo.py`

What it does:
- Validates a tenant-scoped search request.
- Calls the embedding repository with `tenant_id`, query, filters, and `top_k`.
- Rejects any result whose `tenant_id` does not match the request tenant.
- Returns answer context, citations, metadata, and status.

Key statuses:
- `ok`: usable context found.
- `no_results`: repository found nothing.
- `low_confidence`: best result score is below `min_score`.

### Memory

Main file:
- `backend/app/services/memory_service.py`

What it does:
- Stores short-term conversation messages.
- Supports user, assistant, and tool roles.
- Keeps messages scoped by tenant and conversation.
- Uses Redis in runtime when available, with in-memory fallback.

Redis key pattern:
```text
session:tenant:{tenant_id}:conversation:{conversation_id}:memory
```

Why this matters:
- It matches Mohammad's tenant erasure pattern: `session:tenant:{tenant_id}:*`.

### Agent

Main file:
- `backend/app/services/agent_service.py`

What it does:
- Runs a small tool-planning loop.
- Uses `ToolRegistry` to call `rag_search`, `capture_lead`, or `escalate`.
- Stops when the planner returns a final response, a tool is unavailable, or the loop limit is reached.

Planner behavior:
- `AnthropicAgentPlanner` is used when `ANTHROPIC_API_KEY` is configured.
- `HeuristicAgentPlanner` is used when Anthropic is missing or placeholder.
- Anthropic usage is read from `usage.input_tokens` and `usage.output_tokens` for cost attribution.

### Lead Capture

Main files:
- `backend/app/services/lead_service.py`
- `backend/app/repositories/lead_repo.py`

What it does:
- Requires email or phone.
- Normalizes email and phone.
- Rejects spam-classified leads.
- Rate-limits writes per tenant and visitor session.
- Deduplicates open leads only within the same tenant/contact.

### Escalation

Main files:
- `backend/app/services/escalation_service.py`
- `backend/app/repositories/conversation_repo.py`

What it does:
- Requires tenant, conversation, and visitor session.
- Looks up the conversation using tenant and conversation id.
- Rejects mismatched visitor sessions.
- Returns an existing open escalation instead of creating duplicates.
- Redacts secrets like API keys/tokens from escalation summaries.

## 5. Tests as Proof During Review

Use tests as evidence, not just as "we wrote tests."

### `backend/tests/test_chat.py`

Proves:
- FAQ messages route to RAG.
- Agent path is used for ambiguous turns.
- Jana classifier result is accepted.
- Degraded classifier output becomes agent fallback.
- `/chat` reads classifier from `request.app.state`.
- Redis memory is selected when available and falls back to in-memory when unavailable.
- Anthropic planner is selected only when a real key is configured.
- `/chat` is mounted in the FastAPI app.

### `backend/tests/test_memory.py`

Proves:
- Memory is scoped by tenant and conversation.
- TTL expiration works.
- Appending refreshes TTL.
- Only latest messages are kept.
- Prompt context is formatted in order.
- Empty content and unknown fields are rejected.
- Clear removes only the target conversation.
- Redis key matches Mohammad's erasure pattern.
- Redis append, trim, TTL, and clear behavior work.

### `backend/tests/test_rag.py`

Proves:
- RAG returns ordered context and citations for the same tenant.
- Cross-tenant chunks are never accepted.
- Unpublished content can be filtered.
- Invalid `top_k` and unknown filters are rejected.
- Low-confidence retrieval returns no context.
- CMS ingestion creates searchable tenant-scoped chunks.

### `backend/tests/test_agent_tools.py`

Proves:
- Lead capture validation, spam blocking, rate limiting, and deduplication.
- Escalation tenant/session checks, idempotency, and redaction.
- Router decisions for spam, low confidence, FAQ, lead, and human handoff.
- Agent tool loop behavior, unavailable tools, iteration limits, and invalid requests.
- Anthropic planner environment handling and invalid response handling.

## 6. Current Limitations to Say Honestly

- Runtime RAG factory still uses demo in-memory data until final tenant CMS/vector persistence is connected.
- Runtime lead capture uses an in-memory repository until final shared persistence is connected.
- Runtime escalation is implemented as a service, but not fully wired into `build_chat_service()` because it needs conversation persistence/session ownership from the shared backend.
- `tenant_id` still appears in Ali-owned request models for local testing, but production should derive tenant from auth/widget context.
- Jana's classifier and guardrails are optional in local runs because the API checks whether clients/functions are available.
- Redis must be available through `REDIS_URL`; otherwise memory falls back to in-memory.

## 7. Teammate Dependencies

Charbel:
- Sends chat requests from the widget to `POST /chat`.
- Final widget/auth payload should provide trusted tenant/session context.
- Temporary integration can use the current request body shape.

Jana:
- Provides `request.app.state.classifier_client`.
- Provides `request.app.state.guardrail_client`.
- Provides `screen_input(...)` and `screen_output(...)`.

Mohammad:
- Provides verified tenant/auth context.
- Owns tenant erasure expectations for Redis.
- May hook LLM cost attribution at the Anthropic planner call.
- Provides final persistence/session patterns needed to replace in-memory runtime scaffolding.

## 8. Questions You Should Be Ready to Answer

Where does the chat request enter?
- `POST /chat` in `backend/app/api/chat.py`.

What happens before Ali's logic?
- Jana's classifier and input guardrail can run first if configured.

What happens if classifier confidence is low or degraded?
- `RouterService` routes to `agent` instead of trusting a direct route.

How does RAG avoid returning another tenant's content?
- Repository search is tenant-scoped, and `RagService` explicitly checks every returned chunk tenant id.

What is the Redis key pattern?
- `session:tenant:{tenant_id}:conversation:{conversation_id}:memory`.

Where does the Anthropic call happen?
- `AnthropicAgentPlanner.plan(...)` in `backend/app/services/agent_service.py`.

What data exists for cost attribution?
- Tenant id, provider, model, input token count, and output token count.

What happens without Anthropic?
- Runtime falls back to `HeuristicAgentPlanner`.

How are leads protected?
- Contact validation, spam blocking, tenant-scoped deduplication, and per-tenant/session rate limiting.

How does escalation avoid cross-tenant leaks?
- It fetches conversation by tenant and conversation id and returns a generic not-found error if it does not exist for that tenant.

## 9. Recommended Study Passes

30-minute architecture pass:
- Read sections 1-3 of this cheat sheet.
- Draw the request flow once from memory.

60-90 minute service pass:
- Read the services in this order: chat, router, RAG, memory, agent, lead, escalation.
- For each service, write one sentence for input, output, failure cases, and test proof.

45-minute test pass:
- Read the four main test files.
- For each test, say out loud which behavior it proves.

Final rehearsal:
- Explain one happy path: FAQ -> classifier -> RAG -> memory -> response.
- Explain one fallback path: degraded classifier -> agent -> Anthropic/heuristic planner.
- Explain one safety story: tenant isolation in RAG and Redis memory.
