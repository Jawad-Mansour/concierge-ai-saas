# Owner: Jana
"""Rail engine — platform rails + tenant rails evaluation.

Implementation note: NeMo Guardrails is the production rail engine
(plan.md "Primary Dependencies"). For local dev + tests + the hot path on
non-NeMo-eligible inputs, the patterns from `config/rails.yaml#patterns` +
`config/jailbreak_rules.yaml#frames` + `config/cross_tenant_rules.yaml#patterns`
back the same decisions. The pattern source-of-truth is the YAML — NeMo flows
in production are constructed to fire on the same patterns, so the boot-time
config-hash check (Principle II) protects both code paths.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

from .schemas import Action, Decision, RuleName, TenantConfig

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _compile_patterns(raw: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in raw]


def _load_pattern_set() -> tuple[
    list[re.Pattern[str]],  # prompt_injection
    list[re.Pattern[str]],  # jailbreak (rails.yaml#jailbreak ∪ jailbreak_rules frames)
    list[re.Pattern[str]],  # cross_tenant (rails ∪ cross_tenant_rules semantic)
    list[str],              # tenant_names literal blocklist
]:
    rails = yaml.safe_load((_CONFIG_DIR / "rails.yaml").read_text(encoding="utf-8")) or {}
    jail = yaml.safe_load((_CONFIG_DIR / "jailbreak_rules.yaml").read_text(encoding="utf-8")) or {}
    xtenant = yaml.safe_load((_CONFIG_DIR / "cross_tenant_rules.yaml").read_text(encoding="utf-8")) or {}

    patterns = rails.get("patterns", {})
    prompt_injection = _compile_patterns(patterns.get("prompt_injection", []))

    jailbreak = list(patterns.get("jailbreak", []))
    for frame in jail.get("frames", []):
        jailbreak.extend(frame.get("patterns", []))
    jailbreak_compiled = _compile_patterns(jailbreak)

    cross_tenant = list(patterns.get("cross_tenant", []))
    cross_tenant.extend(xtenant.get("patterns", {}).get("semantic", []))
    cross_tenant_compiled = _compile_patterns(cross_tenant)

    tenant_names = [str(n) for n in xtenant.get("tenant_names") or []]
    return prompt_injection, jailbreak_compiled, cross_tenant_compiled, tenant_names


_PROMPT_INJECTION, _JAILBREAK, _CROSS_TENANT, _TENANT_NAMES = _load_pattern_set()


def evaluate_platform_rails(
    message: str, endpoint: str
) -> tuple[Decision, RuleName | None, Action | None]:
    """Return the first matching platform rail or ("pass", None, None).

    Order: prompt_injection → jailbreak → cross_tenant. `endpoint` is "input"
    or "output"; both run the same set, but prompt_injection is logically
    input-only and we skip it for outputs.
    """
    if endpoint == "input":
        for pat in _PROMPT_INJECTION:
            if pat.search(message):
                return "block", "prompt_injection", "safe_refusal"
    for pat in _JAILBREAK:
        if pat.search(message):
            return "block", "jailbreak", "safe_refusal"
    for pat in _CROSS_TENANT:
        if pat.search(message):
            return "block", "cross_tenant", "safe_refusal"
    for name in _TENANT_NAMES:
        if name and name.lower() in message.lower():
            return "block", "cross_tenant", "safe_refusal"
    return "pass", None, None


def _topic_in_allowed(message: str, allowed: list[str]) -> bool:
    """Light keyword overlap — production swaps in NeMo's topical-rails composition.

    The test plan (T015 / T027) targets the orchestration shape; the actual
    topical-rails accuracy is governed by the red-team probe set, not by this
    helper's heuristic.
    """
    haystack = message.lower()
    return any(topic.lower() in haystack for topic in allowed if topic)


def _compose_refusal(template: str, *, topic: str, reason: str) -> str:
    return template.format(topic=topic, reason=reason)


def evaluate_tenant_rails(
    message: str, tenant_config: TenantConfig
) -> tuple[Decision, RuleName | None, Action | None, str | None]:
    """Escalation triggers run first (override off-topic, per data-model.md)."""
    for trigger in tenant_config.escalation_triggers or []:
        if trigger.kind == "keyword":
            if trigger.value and trigger.value.lower() in message.lower():
                return "block", "escalation_trigger", "escalate", None
        elif trigger.kind == "intent":
            # Production: NeMo intent classifier. Heuristic fallback: substring.
            if trigger.value and trigger.value.lower() in message.lower():
                return "block", "escalation_trigger", "escalate", None

    allowed = tenant_config.allowed_topics
    if allowed:
        if not _topic_in_allowed(message, allowed):
            persona = tenant_config.refusal_persona
            template = persona.template if persona else "I can only help with {topic}. {reason}"
            text = _compose_refusal(
                template,
                topic=", ".join(allowed),
                reason="That falls outside what I can answer here.",
            )
            return "block", "off_topic", "tenant_refusal", text

    return "pass", None, None, None
