# Owner: Jana
# Owner: Jana
"""Redaction-safe structured logging for the backend.

Mirrors the `structured_log` helper in modelserver/app/telemetry.py and
guardrails/app/telemetry.py so all three services log under one schema: one
JSON object per line, `event` plus structured fields, never visitor content.

DEFENSE-IN-DEPTH, not the PII control. Content is expected to be redacted
upstream by the redaction middleware before any log call (Constitution:
"redacted before any data reaches logs"). The strip below only catches a
caller passing a field named like content or a secret — it does not detect
PII inside an arbitrarily-named field. Redaction is the real guarantee.

Filename note: this module is `app.utils.logging`, which shadows the stdlib
`logging` by name. Under Python 3 absolute imports, the bare `import logging`
below still resolves the stdlib module (a nested `app.utils.logging` is never
matched by a top-level import), so this is safe and intentional — the path was
fixed by the agreed layout, not chosen here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("backend.logging")

# Field names that may carry visitor content, model output, or secrets; popped
# before serialization. Union of both service modules' lists plus the content
# and secret field names this backend's code uses. Erring wide is deliberate:
# a dropped debug field costs less than a leak the PII CI gate then fails on.
# Trim only with a stated reason.
_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        # visitor / model content (service modules + obvious aliases)
        "message", "llm_response", "matched_value",
        "prompt", "query", "input", "text", "content",
        "response", "answer", "output",
        # stringified exceptions can embed the triggering input; log
        # error=type(exc).__name__ instead (precedent: modelserver deps.py)
        "exception_message",
        # direct PII named by the constitution
        "email", "phone", "credit_card",
        # secrets — Principle V, never in logs
        "api_key", "token", "secret", "password", "authorization",
    }
)


def structured_log(event: str, /, **fields: Any) -> None:
    """Emit one structured JSON log line.

    `event` is positional-only so it can't be confused with a data field, and
    any field whose name is in `_FORBIDDEN_FIELDS` is dropped before
    serialization. Same signature/behavior as the service telemetry modules,
    so a log consumer parses all three services identically.
    """
    for forbidden in _FORBIDDEN_FIELDS:
        fields.pop(forbidden, None)
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))
