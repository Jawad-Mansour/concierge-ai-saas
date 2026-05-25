# Concierge — Repository Structure

Ownership map for the repo. This mirrors the team plan.

## Team

| Person   | Main Responsibility                        |
| -------- | ------------------------------------------ |
| Ali      | Agent, RAG, memory, chat logic             |
| Mohammad | Tenancy, auth, RLS, provisioning           |
| Jana     | Models, security, guardrails               |
| Charbel  | Widget, admin UX, CI/CD, Docker            |

## Tree

```
concierge/
│
├── README.md ........................................ Shared
├── docker-compose.yml ............................... Shared
├── .env.example ..................................... Shared
├── eval_thresholds.yaml ............................. Charbel
├── CLAUDE.md ........................................ Shared
├── CONTRIBUTING.md .................................. Shared
├── structure.md ..................................... Shared
│
├── roadmap/
│   ├── ali.md ....................................... Ali
│   ├── mohammad.md .................................. Mohammad
│   ├── jana.md ...................................... Jana
│   └── charbel.md ................................... Charbel
│
├── deliverables/
│   ├── DESIGN.md .................................... Shared
│   ├── DECISIONS.md ................................. Shared
│   ├── SECURITY.md .................................. Jana
│   ├── RUNBOOK.md ................................... Shared
│   └── EVALS.md ..................................... Shared
│
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md ..................... Shared
│   ├── CODEOWNERS ................................... Shared
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md ............................ Shared
│   │   └── feature_request.md ....................... Shared
│   └── workflows/
│       ├── ci.yml ................................... Charbel 
│       ├── smoke-test.yml ........................... Charbel
│       ├── evals.yml ................................ Charbel
│       └── security-gates.yml ....................... Jana
│
├── specs/
│   ├── tenant_model_SPEC.md ......................... Mohammad
│   ├── role_model_SPEC.md ........................... Mohammad
│   ├── rag_tool_SPEC.md ............................. Ali
│   ├── capture_lead_SPEC.md ......................... Ali
│   ├── escalate_SPEC.md ............................. Ali
│   ├── widget_auth_SPEC.md .......................... Charbel
│   ├── classifier_SPEC.md ........................... Jana
│   └── guardrails_SPEC.md ........................... Jana
│
├── prompts/
│   ├── system_prompt.txt ............................ Ali
│   ├── escalation_prompt.txt ........................ Ali
│   ├── lead_capture_prompt.txt ...................... Ali
│   └── tenant_persona_templates/ .................... Ali
│
├── infra/
│   ├── vault/
│   │   ├── policies/ ................................ Mohammad
│   │   └── seed.sh .................................. Mohammad
│   │
│   ├── postgres/
|   |   ├── Dockerfile ................................ Charbel
│   │   ├── init.sql ................................. Mohammad
│   │   ├── rls_policies.sql ......................... Mohammad
│   │   └── migrations/ .............................. Mohammad
│   │
│   ├── minio/
│   │   └── buckets.sh ............................... Mohammad
│   │
│   └── redis/
│       └── redis.conf ............................... Ali
│
├── backend/
|   ├── Dockerfile ................................... Charbel
|   ├── pyproject.toml ............................... Ali
│   ├── app/
│   │   ├── main.py .................................. Shared Core
│   │   │
│   │   ├── api/
│   │   │   ├── auth.py .............................. Mohammad
│   │   │   ├── tenants.py ........................... Mohammad
│   │   │   ├── widget.py ............................ Charbel
│   │   │   ├── chat.py .............................. Ali
│   │   │   ├── leads.py ............................. Ali
│   │   │   ├── cms.py ............................... Ali
│   │   │   ├── admin.py ............................. Charbel
│   │   │   └── health.py ............................ Shared
│   │   │
│   │   ├── services/
│   │   │   ├── router_service.py .................... Ali
│   │   │   ├── agent_service.py ..................... Ali
│   │   │   ├── rag_service.py ....................... Ali
│   │   │   ├── embedding_service.py ................. Ali
│   │   │   ├── memory_service.py .................... Ali
│   │   │   ├── lead_service.py ...................... Ali
│   │   │   ├── escalation_service.py ................ Ali
│   │   │   ├── tenant_service.py .................... Mohammad
│   │   │   ├── auth_service.py ...................... Mohammad
│   │   │   ├── widget_auth_service.py ............... Charbel
│   │   │   ├── guardrail_service.py ................. Jana
│   │   │   ├── redaction_service.py ................. Jana
│   │   │   ├── tracing_service.py ................... Jana
│   │   │   └── classifier_client.py ................. Jana
│   │   │
│   │   ├── repositories/
│   │   │   ├── tenant_repo.py ....................... Mohammad
│   │   │   ├── user_repo.py ......................... Mohammad
│   │   │   ├── conversation_repo.py ................. Ali
│   │   │   ├── lead_repo.py ......................... Ali
│   │   │   ├── cms_repo.py .......................... Ali
│   │   │   ├── embedding_repo.py .................... Ali
│   │   │   └── audit_repo.py ........................ Mohammad
│   │   │
│   │   ├── models/
│   │   │   ├── tenant.py ............................ Mohammad
│   │   │   ├── user.py .............................. Mohammad
│   │   │   ├── lead.py .............................. Ali
│   │   │   ├── conversation.py ...................... Ali
│   │   │   ├── cms_content.py ....................... Ali
│   │   │   └── embeddings.py ........................ Ali
│   │   │
│   │   ├── middleware/
│   │   │   ├── tenant_context.py .................... Mohammad
│   │   │   ├── auth_middleware.py ................... Mohammad
│   │   │   ├── rate_limit.py ........................ Mohammad
│   │   │   ├── guardrails.py ........................ Jana
│   │   │   └── redaction.py ......................... Jana
│   │   │
│   │   └── utils/
│   │       ├── token_utils.py ....................... Charbel
│   │       ├── logging.py ........................... Jana
│   │       ├── metrics.py ........................... Jana
│   │       └── constants.py ......................... Shared
│   │
│   └── tests/
│       ├── test_rag.py .............................. Ali
│       ├── test_agent_tools.py ...................... Ali
│       ├── test_memory.py ........................... Ali
│       ├── test_tenant_isolation.py ................. Mohammad + Jana
│       ├── test_rls.py .............................. Mohammad
│       ├── test_guardrails.py ....................... Jana
│       ├── test_redaction.py ........................ Jana
│       ├── test_widget_auth.py ...................... Charbel
│       ├── test_ci_smoke.py ......................... Charbel
│       └── golden_sets/ ............................. Shared
│
├── modelserver/
|   ├── Dockerfile ................................... Charbel
|   ├── pyproject.toml ............................... Jana
│   ├── app/
│   │   ├── main.py .................................. Jana
│   │   ├── classifier.py ............................ Jana
│   │   ├── inference.py ............................. Jana
│   │   ├── model_loader.py .......................... Jana
│   │   └── schemas.py ............................... Jana
│   │
│   ├── artifacts/
│   │   ├── classifier.onnx .......................... Jana
│   │   ├── classifier.joblib ........................ Jana
│   │   └── model_card.md ............................ Jana
│   │
│   └── training/
│       ├── train_ml.ipynb ........................... Jana
│       ├── train_dl.ipynb ........................... Jana
│       ├── export_onnx.py ........................... Jana
│       └── evaluate_models.py ....................... Jana
│
├── guardrails/
|   ├── Dockerfile ................................... Charbel
│   ├── pyproject.toml ............................... Jana
│   ├── config/
│   │   ├── rails.yaml ............................... Jana
│   │   ├── jailbreak_rules.yaml ..................... Jana
│   │   ├── cross_tenant_rules.yaml .................. Jana
│   │   └── pii_redaction.yaml ....................... Jana
│   │
│   └── app/
│       ├── main.py .................................. Jana
│       └── validators.py ............................ Jana
│
├── widget/
|   ├── Dockerfile ................................... Charbel
|   ├── nginx.conf ................................... Charbel
│   ├── src/
│   │   ├── App.tsx .................................. Charbel
│   │   ├── widget.tsx ............................... Charbel
│   │   ├── loader.js ................................ Charbel
│   │   ├── api.ts ................................... Charbel
│   │   ├── auth.ts .................................. Charbel
│   │   ├── theme.ts ................................. Charbel
│   │   ├── styles.css ............................... Charbel
│   │   └── components/
│   │       ├── ChatWindow.tsx ....................... Charbel
│   │       ├── MessageBubble.tsx .................... Charbel
│   │       └── InputBox.tsx ......................... Charbel
│   │
│   └── tests/
│       └── widget.test.ts ........................... Charbel
│
├── admin/
|   ├── Dockerfile ................................... Charbel
│   ├── pyproject.toml ............................... Charbel
│   ├── streamlit_app.py ............................. Charbel
│   ├── pages/
│   │   ├── tenant_settings.py ....................... Charbel
│   │   ├── guardrails_config.py ..................... Charbel + Jana
│   │   ├── widget_config.py ......................... Charbel
│   │   └── leads_dashboard.py ....................... Ali
│   │
│   └── components/
│       ├── sidebar.py ............................... Charbel
│       └── charts.py ................................ Charbel
│
├── evals/
│   ├── classifier/
│   │   ├── eval_classifier.py ....................... Jana
│   │   └── datasets/ ................................ Jana
│   │
│   ├── rag/
│   │   ├── eval_rag.py .............................. Ali
│   │   └── golden_questions.json .................... Ali
│   │
│   ├── agent/
│   │   ├── eval_tools.py ............................ Ali
│   │   └── tool_selection_cases.json ............... Ali
│   │
│   ├── security/
│   │   ├── red_team_tests.py ........................ Jana
│   │   ├── injection_cases.json ..................... Jana
│   │   └── cross_tenant_cases.json .................. Jana
│   │
│   └── smoke/
│       └── smoke_test.py ............................ Charbel
│
└── scripts/
    ├── bootstrap.sh ................................. Shared
    ├── seed_tenants.py .............................. Mohammad
    ├── ingest_cms.py ................................ Ali
    ├── create_widget_token.py ....................... Charbel
    ├── run_evals.sh ................................. Charbel
    └── delete_tenant.py ............................. Mohammad + Jana
│
└── demo/
    ├── host/
    │   ├── Dockerfile ............................... Charbel
    │   ├── nginx.conf ............................... Charbel
    │   └── public/
    │       └── index.html ........................... Charbel
    │
    └── blocked-host/
        ├── Dockerfile ............................... Charbel
        ├── nginx.conf ............................... Charbel
        └── public/
            └── blocked.html ......................... Charbel
```

## Docker layout

Built from a `Dockerfile` in this repo:

- `backend/Dockerfile` — FastAPI app (Python)
- `modelserver/Dockerfile` — lean ONNX / sklearn server, no torch (Python)
- `guardrails/Dockerfile` — NeMo Guardrails sidecar (Python)
- `widget/Dockerfile` — React widget build + static serve (Node → nginx)
- `admin/Dockerfile` — Streamlit admin app (Python)
- `infra/postgres/Dockerfile` — `pgvector/pgvector` base with `init.sql` and `rls_policies.sql` baked in so DB init is reproducible

Pulled from official images via `docker-compose.yml` (no Dockerfile needed):

- `redis` — `redis:7`
- `minio` — `minio/minio`
- `vault` — `hashicorp/vault`

## Conventions

- **Branches & commits** — see `CONTRIBUTING.md` at root.
- **Specs** — every major component has a `SPEC.md` under `specs/`, written before the code.
- **Roadmap** — one file per teammate under `roadmap/`. Append-only end-of-day notes. One file per person = no merge conflicts.
- **Deliverables** — the graded docs live in `deliverables/`. These get tightened up before the Friday demo.
