# Owner: Jana
"""Evaluation orchestrator.

Order (data-model.md state transitions):
  1. platform rails  → block-on-match wins.
  2. tenant rails    → block-on-match next.
  3. redaction       → only runs on pass.

The whole body is wrapped in a fail-closed try/except (Principle VI). Every
exception path returns `EvaluationResponseBlock(rule_name=engine_error|config_error,
action=fallback_response, refusal_text=None)`.
"""
from __future__ import annotations

import time

from opentelemetry import trace

from . import rails_engine, redaction, telemetry, version
from .schemas import (
    EvaluationResponse,
    EvaluationResponseBlock,
    EvaluationResponsePass,
    TenantConfig,
)

_tracer = trace.get_tracer("guardrails.validators")


async def evaluate(
    *,
    endpoint: str,
    content: str,
    tenant_id: str | None,
    tenant_config: TenantConfig,
) -> EvaluationResponse:
    with _tracer.start_as_current_span("guardrails.evaluate") as span:
        started = time.perf_counter()

        try:
            decision, rule, action = rails_engine.evaluate_platform_rails(content, endpoint)
            if decision == "block":
                assert rule is not None and action is not None
                telemetry.set_evaluation_attrs(
                    span,
                    tenant_id=tenant_id,
                    endpoint=endpoint,
                    decision=decision,
                    rule_name=rule,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    rails_version=version.RAILS_VERSION,
                )
                return EvaluationResponseBlock(
                    rule_name=rule, action=action, refusal_text=None
                )

            # Tenant rails — skipped when `tenant_config` is empty (FR-010).
            if (
                tenant_config.allowed_topics
                or tenant_config.escalation_triggers
                or tenant_config.refusal_persona
            ):
                try:
                    t_decision, t_rule, t_action, t_text = rails_engine.evaluate_tenant_rails(
                        content, tenant_config
                    )
                except ValueError as exc:
                    # Defensive: tenant_config was admitted by the schema but the
                    # rail engine couldn't make sense of it (T031/T035 — config_error).
                    telemetry.structured_log(
                        "guardrail.fail_closed",
                        origin="tenant_rails",
                        error_type=type(exc).__name__,
                        tenant_id=tenant_id,
                        endpoint=endpoint,
                    )
                    telemetry.set_evaluation_attrs(
                        span,
                        tenant_id=tenant_id,
                        endpoint=endpoint,
                        decision="block",
                        rule_name="config_error",
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        rails_version=version.RAILS_VERSION,
                    )
                    return EvaluationResponseBlock(
                        rule_name="config_error",
                        action="fallback_response",
                        refusal_text=None,
                    )
                if t_decision == "block":
                    assert t_rule is not None and t_action is not None
                    telemetry.set_evaluation_attrs(
                        span,
                        tenant_id=tenant_id,
                        endpoint=endpoint,
                        decision="block",
                        rule_name=t_rule,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        rails_version=version.RAILS_VERSION,
                    )
                    return EvaluationResponseBlock(
                        rule_name=t_rule, action=t_action, refusal_text=t_text
                    )

            # Pass path — redaction runs here.
            with _tracer.start_as_current_span("guardrails.redaction") as redaction_span:
                payload, metadata = redaction.redact(content)
                if metadata is not None:
                    telemetry.set_redaction_attrs(
                        redaction_span,
                        recognizers_fired=metadata.recognizers_fired,
                        match_count=metadata.match_count,
                    )

            telemetry.set_evaluation_attrs(
                span,
                tenant_id=tenant_id,
                endpoint=endpoint,
                decision="pass",
                rule_name=None,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                rails_version=version.RAILS_VERSION,
            )
            return EvaluationResponsePass(payload=payload, redaction=metadata)

        except Exception as exc:  # noqa: BLE001 — fail-closed catches everything
            telemetry.record_counter(span, "guardrail.fail_closed")
            telemetry.structured_log(
                "guardrail.fail_closed",
                origin="orchestrator",
                error_type=type(exc).__name__,
                tenant_id=tenant_id,
                endpoint=endpoint,
            )
            telemetry.set_evaluation_attrs(
                span,
                tenant_id=tenant_id,
                endpoint=endpoint,
                decision="block",
                rule_name="engine_error",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                rails_version=version.RAILS_VERSION,
            )
            return EvaluationResponseBlock(
                rule_name="engine_error",
                action="fallback_response",
                refusal_text=None,
            )
