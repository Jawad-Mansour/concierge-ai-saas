<!-- Owner: Ali -->

# RAG Tool Spec

## Purpose

`rag_search` retrieves and summarizes tenant-owned CMS content for the router and the tool-calling agent. It is the only backend path the agent may use for knowledge-grounded answers.

The tool must:

- Search only CMS chunks that belong to the verified request tenant.
- Return enough citations for the answer layer to show where information came from.
- Prefer grounded refusal over guessing when retrieval confidence is low.
- Record tenant-scoped retrieval metrics for evals, debugging, and per-tenant cost analysis.

## Inputs

The service entrypoint lives in `backend/app/services/rag_service.py`; API handlers and agent tools should pass a typed request object instead of raw dictionaries.

Required inputs:

- `tenant_id`: server-derived tenant id from auth/widget token context.
- `conversation_id`: active conversation id for trace linkage and optional memory context.
- `query`: visitor question or rewritten query text.
- `top_k`: max chunks to return, default `5`, max `10`.

Optional inputs:

- `filters`: allowed metadata filters, initially `content_type`, `page_id`, `locale`, and `published_only`.
- `rewrite_query`: boolean indicating whether the service may call the query rewrite step.
- `min_score`: minimum similarity/rerank score required to treat a result as usable.
- `trace_id`: request trace id propagated from chat handling.

Client-supplied `tenant_id`, `embedding_ids`, SQL fragments, or arbitrary metadata keys are never accepted.

## Outputs

Successful output:

- `answer_context`: ordered text snippets safe for the LLM answer prompt.
- `citations`: list of `{chunk_id, cms_content_id, title, url, score}`.
- `retrieval_meta`: `{tenant_id, query_hash, top_k, returned_count, strategy, latency_ms}`.
- `status`: one of `ok`, `no_results`, or `low_confidence`.

The tool returns context, not the final visitor-facing prose. The agent or router answer step uses `prompts/system_prompt.txt` plus tenant persona and guardrails to produce the final response.

## Tenant Isolation Rules

- `tenant_id` is taken only from verified request context, never request body or LLM tool arguments.
- `embedding_repo` must scope every vector query by `tenant_id`.
- Postgres RLS must also protect embedding and CMS rows, using the tenant context set for the request.
- Returned citations must include only rows whose `tenant_id` matches the request tenant.
- Logs, traces, and eval artifacts may store query hashes and chunk ids, but must not store unredacted visitor PII.
- Query rewrite and answer generation prompts must not include content from other tenants, platform secrets, system prompts, or hidden guardrail text.

## Validation Rules

- `query` must be non-empty after trimming and must be capped, initially at `2,000` characters.
- `top_k` must be an integer from `1` to `10`.
- `filters` must be allowlisted and value types must be validated before reaching repositories.
- `tenant_id` and `conversation_id` must be valid UUIDs or the project-standard id type.
- Retrieval must ignore unpublished CMS content unless the caller is an authenticated tenant admin using an explicit preview path.
- Result snippets must be length-capped before insertion into prompts to protect token budgets.

## Failure Cases

- Missing or invalid tenant context: fail closed with `403` at API boundary or `TenantContextError` inside service code.
- Empty or overlong query: return validation error and do not call embeddings or LLM APIs.
- Embedding provider unavailable: return `retrieval_unavailable`; router/agent should apologize and offer escalation.
- Vector database unavailable: return `retrieval_unavailable`; no fallback to unscoped SQL search.
- No matching chunks: return `status=no_results` with empty citations.
- Low retrieval score: return `status=low_confidence`; answer layer must avoid unsupported claims.
- Cross-tenant result detected in service assertions: raise security error, log redacted audit event, and fail the request.

## Tests/Evals Required

Unit tests in `backend/tests/test_rag.py`:

- Valid query returns ordered chunks and citations for the same tenant.
- Tenant A query never returns Tenant B chunks even when text overlaps.
- Invalid `top_k`, empty query, and disallowed filters are rejected before repository calls.
- Low score and no-result paths produce grounded refusal-ready statuses.
- Repository calls always receive the server-derived tenant id.

Agent/router tests in `backend/tests/test_agent_tools.py`:

- FAQ-style router path calls `rag_search` directly.
- Ambiguous agent path can choose `rag_search` and then answer using returned context.
- Tool arguments cannot override tenant context.

RAG evals in `evals/rag/eval_rag.py` with `evals/rag/golden_questions.json`:

- Hit rate or recall@k on tenant-scoped golden questions.
- Citation correctness against expected CMS document ids.
- Cross-tenant leakage golden cases where distractor chunks exist in another tenant.
- One retrieval improvement comparison, such as query rewrite, rerank, or metadata filter, reported in `deliverables/EVALS.md`.
