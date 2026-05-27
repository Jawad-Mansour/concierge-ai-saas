<!-- Owner: Ali -->

# Escalate Tool Spec

## Purpose

`escalate` marks a tenant-scoped conversation for human follow-up when the visitor explicitly asks for a person, the agent is out of scope, guardrails require handoff, or repeated low-confidence retrieval makes an automated answer unsafe.

The tool creates a durable escalation signal for tenant admins without giving the visitor or LLM any ability to choose another tenant, inspect internal data, or bypass guardrails.

## Inputs

The service entrypoint lives in `backend/app/services/escalation_service.py`; API handlers and agent code should call it through a typed service method.

Required inputs:

- `tenant_id`: server-derived tenant id from auth/widget context.
- `conversation_id`: active conversation to escalate.
- `visitor_session_id`: anonymous widget session id.
- `reason`: enum value:
  - `human_requested`
  - `out_of_scope`
  - `low_confidence`
  - `safety_or_guardrail`
  - `technical_failure`

Optional inputs:

- `summary`: concise redacted conversation summary for the tenant admin.
- `priority`: `low`, `normal`, or `high`; default `normal`.
- `last_user_message_id`: message id that triggered escalation.
- `lead_id`: related lead id when capture already happened.
- `trace_id`: request trace id.

The LLM may draft `summary`, but the backend owns validation, redaction, and final persistence.

## Outputs

Successful output:

- `escalation_id`: created ticket/flag id.
- `tenant_id`: tenant that owns the escalation.
- `conversation_id`: linked conversation.
- `status`: initially `open`.
- `priority`: final normalized priority.
- `created_at`: server timestamp.
- `visitor_message`: safe response text telling the visitor a human will follow up.

Duplicate output:

- If the conversation already has an open escalation, return the existing escalation id with `status=open` and do not create another row.

## Tenant Isolation Rules

- `tenant_id` is read only from verified context and passed through every service/repository call.
- Conversation, lead, and escalation records must all have the same `tenant_id`.
- `conversation_repo` lookups and escalation writes must be scoped by tenant and protected by RLS.
- Tenant admins can view and resolve only their tenant's escalations.
- Platform Tenant Manager may erase escalation rows through the maintenance path but must not read escalation content.
- Summaries and logs must run through redaction before persistence to traces or external systems.

## Validation Rules

- `conversation_id` must exist for the current tenant.
- `reason` must be one of the allowed enum values.
- `priority` must be one of `low`, `normal`, or `high`.
- `summary` is optional, capped at `1,000` characters, and redacted before storage.
- `lead_id`, when provided, must belong to the same tenant and conversation.
- Repeated escalation calls for the same open conversation should be idempotent.
- The service must not accept arbitrary assignee ids, external ticket ids, or status changes from visitor-triggered tool calls.

## Failure Cases

- Missing tenant context: fail closed with `403` at API boundary or `TenantContextError` in service code.
- Conversation not found for tenant: return not found without revealing whether it exists elsewhere.
- Invalid reason or priority: return validation error and do not write.
- Cross-tenant lead/conversation mismatch: raise security error and do not write.
- Existing open escalation: return existing open escalation instead of duplicating.
- Repository/database failure: return `escalation_unavailable`; agent should apologize and offer a fallback contact path if tenant config provides one.
- Redaction failure: fail closed rather than storing unredacted sensitive data.

## Tests/Evals Required

Unit tests in `backend/tests/test_agent_tools.py` or `backend/tests/test_escalation_service.py`:

- Explicit "talk to a human" intent calls `escalate`.
- Low-confidence RAG path can escalate with `reason=low_confidence`.
- Valid escalation is scoped to the server-derived tenant id.
- Tool/request payload cannot override tenant id, status, or assignee fields.
- Cross-tenant conversation and lead ids are rejected.
- Duplicate open escalation is idempotent.
- Summary text is length-capped and redacted before logs/traces.

Tenant isolation tests:

- Tenant A cannot see, create against, or resolve Tenant B escalations.
- Platform erasure path can delete escalation rows without exposing contents.

Agent evals in `evals/agent/eval_tools.py` with `evals/agent/tool_selection_cases.json`:

- Human-handoff prompts select `escalate`.
- Out-of-scope prompts select `escalate` rather than unsupported RAG answers.
- Prompt-injection attempts cannot force cross-tenant escalation metadata.
