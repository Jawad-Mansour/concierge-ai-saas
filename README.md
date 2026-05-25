<!-- Owner: Shared -->

# Concierge

A multi-tenant AI SaaS. Businesses sign up, manage their content in a CMS,
and embed an AI agent that acts on their public site — answering visitor
questions from their content, capturing leads, and escalating to a human
when needed.

The hard problem isn't the chat. It's the wall between tenants.

## Status

Week 8 project — under active development. See `structure.md` for the
ownership map and `deliverables/DESIGN.md` for the architecture.

## Quick start

```bash
cp .env.example .env
# fill in Vault root token and API keys
docker compose up
```

## Team

| Person   | Slice                                      |
| -------- | ------------------------------------------ |
| Ali      | Agent, RAG, memory, chat logic             |
| Mohammad | Tenancy, auth, RLS, provisioning           |
| Jana     | Models, security, guardrails               |
| Charbel  | Widget, admin UX, CI/CD, Docker            |

## Docs

- `structure.md` — repo layout and file ownership
- `deliverables/DESIGN.md` — system design (isolation, scaling, cost)
- `deliverables/DECISIONS.md` — architecture decisions with rationale
- `deliverables/SECURITY.md` — threat model and guardrails
- `deliverables/RUNBOOK.md` — operating procedures, demo script
- `deliverables/EVALS.md` — eval methodology and committed thresholds
- `specs/` — component specs (written before code)

## Contributing

See `CONTRIBUTING.md`.