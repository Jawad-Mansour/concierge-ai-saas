<!-- Owner: Ali -->

# Capture Lead Tool Spec

## Purpose

`capture_lead` creates a tenant-scoped lead from a visitor chat when the router or agent detects contact, sales, booking, or follow-up intent.

This is an unauthenticated visitor-triggered write, so the service must be strict: schema validation, rate limiting, tenant scoping from the verified widget token, spam gating, and audit-friendly metadata are required before anything reaches `lead_repo`.

## Inputs

The service entrypoint lives in `backend/app/services/lead_service.py`; API files should only validate transport/auth and call the service.

Required inputs:

- `tenant_id`: server-derived tenant id from the widget/session token.
- `conversation_id`: active conversation id.
- `visitor_session_id`: stable anonymous widget session id.
- `intent`: short description of what the visitor wants.
- One contact field:
  - `email`, or
  - `phone`

Optional inputs:

- `name`: visitor name.
- `company`: visitor company or organization.
- `message`: visitor-provided details to hand to sales/support.
- `source_url`: page where the widget conversation started.
- `lead_score`: classifier/modelserver score when available.
- `classification`: classifier label and confidence, such as `sales`, `support`, or `spam`.
- `trace_id`: request trace id.

The LLM may propose field values, but the backend validates and normalizes the final payload before writing.

## Outputs

Successful output:

- `lead_id`: created lead id.
- `tenant_id`: tenant that owns the lead.
- `conversation_id`: linked conversation.
- `status`: initially `new`.
- `created_at`: server timestamp.
- `deduplicated`: boolean indicating whether the service merged with an existing open lead.

Rejected output:

- Structured validation or policy error with no database write.
- Spam/rate-limit rejection should return a safe generic message to the visitor while preserving redacted metrics.

## Tenant Isolation Rules

- `tenant_id` must come from verified request context, not LLM tool arguments or request body.
- `lead_repo` must scope every read/write/deduplication query by `tenant_id`.
- Postgres RLS must enforce tenant boundaries for the leads table.
- Lead records may link only to conversations with the same `tenant_id`.
- Tenant admins can view only their own tenant's leads.
- Platform Tenant Manager may trigger tenant erasure but must not read lead contents.
- Logs and traces must redact contact values and free-text message fields before leaving the service.

## Validation Rules

- At least one valid contact method is required: normalized email or phone.
- `intent` is required, trimmed, and capped at `500` characters.
- `name` and `company` are optional but capped at `120` characters.
- `message` is optional and capped at `2,000` characters.
- `source_url` must be a valid HTTP(S) URL when provided.
- `classification=spam` or confidence below the accepted threshold blocks the write.
- Rate limit lead writes per `tenant_id` and `visitor_session_id`.
- Deduplicate active leads by tenant plus normalized email/phone before creating a new row.
- Unknown fields from tool calls are rejected, not silently stored.

## Failure Cases

- Missing tenant context: fail closed with `403` at API boundary or `TenantContextError` in service code.
- Missing contact method: return validation error and ask the visitor for email or phone.
- Invalid email/phone/source URL: return validation error without writing.
- Spam classification or blocked guardrail result: do not write a lead.
- Rate limit exceeded: reject the write and do not call the repository.
- Repository/database failure: return `lead_capture_unavailable`; agent may offer escalation or retry later.
- Cross-tenant conversation id: raise security error and do not write.
- Duplicate lead found: update/append tenant-scoped conversation metadata only if allowed, otherwise return existing active lead id without duplicating.

## Tests/Evals Required

Unit tests in `backend/tests/test_agent_tools.py` or `backend/tests/test_lead_service.py`:

- Valid payload writes one lead with the server-derived tenant id.
- Tool/request payload cannot override tenant id.
- Missing/invalid contact information is rejected before repository writes.
- Spam classification blocks the write.
- Rate limit blocks repeated writes from the same visitor session.
- Deduplication stays within tenant boundaries.
- Cross-tenant conversation linkage is rejected.

Tenant isolation tests:

- Tenant A cannot create or deduplicate against Tenant B leads.
- Tenant admin lead listing returns only same-tenant leads.

Agent evals in `evals/agent/eval_tools.py` with `evals/agent/tool_selection_cases.json`:

- Sales/contact intent selects `capture_lead`.
- Multi-step cases can ask for missing contact details before calling the tool.
- Prompt-injection attempts cannot force arbitrary fields or tenant ids into the write.
