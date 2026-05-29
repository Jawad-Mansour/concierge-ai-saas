# Owner: Jana
"""Backend-side redaction for sinks the guardrails sidecar doesn't see:
  - structured logs emitted by backend handlers,
  - OTel span attributes set by backend code,
  - FastAPI default error response bodies,
  - escalation summary fields persisted to the leads/escalations stores.

Lead-write fields (`email`, `phone`, `name`, `company`) are legitimate PII
captures and pass through unchanged. Free-text fields (`message`, `intent`)
are redacted before persistence.

The recognizer patterns mirror `guardrails/config/pii_redaction.yaml` so the
two layers agree on what counts as PII.
"""
from __future__ import annotations

import re
from typing import Iterable

LEAD_WRITE_FIELDS: frozenset[str] = frozenset({"email", "phone", "name", "company"})
FREE_TEXT_FIELDS: frozenset[str] = frozenset({"message", "intent", "transcript", "summary"})

_RECOGNIZERS: list[tuple[str, re.Pattern[str]]] = [
    ("HOSTED_LLM_API_KEY_ANTHROPIC", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("HOSTED_LLM_API_KEY_OPENAI", re.compile(r"sk-(?!ant-)[A-Za-z0-9]{20,}")),
    (
        "GENERIC_BEARER_TOKEN",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    ("EMAIL_ADDRESS", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE_NUMBER", re.compile(r"\+?\d{1,3}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]


def redact_text(text: str) -> str:
    out = text
    for name, pattern in _RECOGNIZERS:
        out = pattern.sub(f"<{name}>", out)
    return out


def redact_record(record: dict, *, fields_to_redact: Iterable[str] | None = None) -> dict:
    """Return a copy of `record` with all FREE_TEXT_FIELDS (or `fields_to_redact`
    if supplied) passed through `redact_text`. LEAD_WRITE_FIELDS are left alone."""
    targets = set(fields_to_redact) if fields_to_redact is not None else FREE_TEXT_FIELDS
    out = dict(record)
    for k, v in record.items():
        if k in LEAD_WRITE_FIELDS:
            continue
        if k in targets and isinstance(v, str):
            out[k] = redact_text(v)
    return out
