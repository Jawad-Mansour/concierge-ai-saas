# Owner: Jana
"""PII redaction. Presidio analyzer + anonymizer, configured pattern-only
(research.md Decision 2 image-size mitigation: no spaCy NLP backend).

Returned metadata never carries matched values or offsets (Principle IX).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .schemas import RecognizerName, RedactionMetadata

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "pii_redaction.yaml"

# Order matters — research.md Decision 2 open risk "API-key prefix collision":
# HOSTED_LLM_API_KEY_ANTHROPIC must match before HOSTED_LLM_API_KEY_OPENAI.
_RECOGNIZER_ORDER: tuple[RecognizerName, ...] = (
    "HOSTED_LLM_API_KEY_ANTHROPIC",
    "HOSTED_LLM_API_KEY_OPENAI",
    "GENERIC_BEARER_TOKEN",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
)

_BUILTIN_PATTERNS: dict[RecognizerName, re.Pattern[str]] = {
    "EMAIL_ADDRESS": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE_NUMBER": re.compile(
        r"\+?\d{1,3}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"
    ),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


def _load_custom_patterns() -> dict[RecognizerName, re.Pattern[str]]:
    cfg = yaml.safe_load(_CONFIG.read_text(encoding="utf-8")) or {}
    recognizers = cfg.get("recognizers", {})
    out: dict[RecognizerName, re.Pattern[str]] = {}
    for name in (
        "HOSTED_LLM_API_KEY_ANTHROPIC",
        "HOSTED_LLM_API_KEY_OPENAI",
        "GENERIC_BEARER_TOKEN",
    ):
        entry = recognizers.get(name) or {}
        pattern = entry.get("pattern")
        if pattern:
            out[name] = re.compile(pattern)  # type: ignore[index]
    return out


_PATTERNS: dict[RecognizerName, re.Pattern[str]] = {
    **_load_custom_patterns(),
    **_BUILTIN_PATTERNS,
}


def redact(text: str) -> tuple[str, RedactionMetadata | None]:
    """Run analyzer → anonymizer with `<RECOGNIZER_NAME>` replace operators.

    Returns (payload, metadata) where metadata is None iff no recognizer fired.
    Recognizers are deduplicated in `recognizers_fired` and order-preserved
    per `_RECOGNIZER_ORDER` (data-model.md §RedactionMetadata).
    """
    fired_in_order: list[RecognizerName] = []
    total = 0
    redacted = text
    for name in _RECOGNIZER_ORDER:
        pattern = _PATTERNS.get(name)
        if pattern is None:
            continue
        redacted, n = pattern.subn(f"<{name}>", redacted)
        if n > 0:
            total += n
            if name not in fired_in_order:
                fired_in_order.append(name)
    if not fired_in_order:
        return text, None
    return redacted, RedactionMetadata(recognizers_fired=fired_in_order, match_count=total)
