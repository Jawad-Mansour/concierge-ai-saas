# Owner: Ali
import pytest

from app.repositories.conversation_repo import (
    ConversationRecord,
    InMemoryConversationRepository,
)
from app.repositories.lead_repo import InMemoryLeadRepository, LeadCreate
from app.services.agent_service import (
    AgentService,
    AgentConfigurationError,
    AgentPlannerError,
    AnthropicAgentPlanner,
    AgentValidationError,
    ToolPlan,
    ToolRegistry,
)
from app.services.escalation_service import (
    ConversationNotFoundError,
    EscalationService,
    EscalationValidationError,
)
from app.services.lead_service import (
    LeadRateLimitError,
    LeadService,
    LeadValidationError,
    LeadWriteRateLimiter,
)
from app.services.router_service import RouterService, RouterValidationError


def lead_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "intent": "I want pricing for a team plan",
        "email": "Buyer@Example.com",
        "name": "Buyer One",
        "source_url": "https://tenant-a.example/pricing",
        "classification": {"label": "sales", "confidence": 0.92},
    }
    payload.update(overrides)
    return payload


def escalation_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "reason": "human_requested",
        "summary": "Visitor wants to speak with a human about pricing.",
        "priority": "normal",
    }
    payload.update(overrides)
    return payload


def escalation_repo():
    return InMemoryConversationRepository(
        [
            ConversationRecord(
                tenant_id="tenant-a",
                conversation_id="conversation-a",
                visitor_session_id="visitor-a",
            )
        ]
    )


class FixedClassifier:
    def __init__(self, label, confidence):
        self.label = label
        self.confidence = confidence

    def classify(self, message):
        return self.label, self.confidence


class StubRagTool:
    def __init__(self, status="ok"):
        self.status = status
        self.calls = []

    def search(self, payload):
        self.calls.append(payload)

        class Result:
            status = self.status

        return Result()


class RepeatingPlanner:
    def __init__(self, tool_name):
        self.tool_name = tool_name

    def plan(self, *, request, tool_calls):
        return ToolPlan(self.tool_name, "repeat forever")


class SequencePlanner:
    def __init__(self, plans):
        self.plans = plans

    def plan(self, *, request, tool_calls):
        if len(tool_calls) >= len(self.plans):
            return ToolPlan(None, "done", final_response="Done")
        return self.plans[len(tool_calls)]


class RecordingCostTracker:
    def __init__(self):
        self.calls = []

    def record_llm_call(self, **kwargs):
        self.calls.append(kwargs)


def router_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "message": "How much is pricing?",
        "source_url": "https://tenant-a.example/pricing",
        "trace_id": "trace-a",
    }
    payload.update(overrides)
    return payload


def agent_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "message": "Please answer pricing and follow up",
        "source_url": "https://tenant-a.example/pricing",
        "contact_email": "buyer@example.com",
        "trace_id": "trace-a",
    }
    payload.update(overrides)
    return payload


def test_capture_lead_creates_tenant_scoped_record():
    repo = InMemoryLeadRepository()
    service = LeadService(repo)

    result = service.capture_lead(lead_payload())

    assert result.tenant_id == "tenant-a"
    assert result.conversation_id == "conversation-a"
    assert result.status == "new"
    assert result.deduplicated is False
    assert repo.records[0].tenant_id == "tenant-a"
    assert repo.records[0].email == "buyer@example.com"


def test_capture_lead_rejects_missing_contact_before_write():
    repo = InMemoryLeadRepository()
    service = LeadService(repo)

    with pytest.raises(LeadValidationError):
        service.capture_lead(lead_payload(email=None, phone=None))

    assert repo.records == []


def test_capture_lead_blocks_spam_before_write():
    repo = InMemoryLeadRepository()
    service = LeadService(repo)

    with pytest.raises(LeadValidationError):
        service.capture_lead(
            lead_payload(classification={"label": "spam", "confidence": 0.99})
        )

    assert repo.records == []


def test_capture_lead_rejects_unknown_tool_fields():
    repo = InMemoryLeadRepository()
    service = LeadService(repo)

    with pytest.raises(LeadValidationError):
        service.capture_lead(lead_payload(assignee_id="agent-owned-field"))

    assert repo.records == []


def test_capture_lead_rate_limits_same_visitor_session():
    repo = InMemoryLeadRepository()
    limiter = LeadWriteRateLimiter(max_writes=1, window_seconds=60)
    service = LeadService(repo, rate_limiter=limiter)

    service.capture_lead(lead_payload())

    with pytest.raises(LeadRateLimitError):
        service.capture_lead(
            lead_payload(email="second@example.com", conversation_id="conversation-b")
        )


def test_capture_lead_deduplicates_only_within_same_tenant():
    repo = InMemoryLeadRepository()
    repo.create(
        LeadCreate(
            tenant_id="tenant-b",
            conversation_id="conversation-b",
            visitor_session_id="visitor-b",
            intent="Different tenant lead",
            email="buyer@example.com",
        )
    )
    service = LeadService(repo)

    result = service.capture_lead(lead_payload(email="buyer@example.com"))

    assert result.tenant_id == "tenant-a"
    assert result.deduplicated is False
    assert len(repo.records) == 2


def test_capture_lead_returns_existing_open_lead_for_same_tenant_contact():
    repo = InMemoryLeadRepository()
    service = LeadService(repo)

    first = service.capture_lead(lead_payload())
    second = service.capture_lead(
        lead_payload(conversation_id="conversation-later", visitor_session_id="visitor-b")
    )

    assert second.lead_id == first.lead_id
    assert second.deduplicated is True


def test_escalate_creates_tenant_scoped_open_escalation():
    repo = escalation_repo()
    service = EscalationService(repo)

    result = service.escalate(escalation_payload(priority="high"))

    assert result.tenant_id == "tenant-a"
    assert result.conversation_id == "conversation-a"
    assert result.status == "open"
    assert result.priority == "high"
    assert result.deduplicated is False
    assert repo.escalations[0].tenant_id == "tenant-a"


def test_escalate_rejects_unknown_tool_fields():
    service = EscalationService(escalation_repo())

    with pytest.raises(EscalationValidationError):
        service.escalate(escalation_payload(assignee_id="not-visitor-controlled"))


def test_escalate_rejects_cross_tenant_conversation_without_leaking_existence():
    repo = InMemoryConversationRepository(
        [
            ConversationRecord(
                tenant_id="tenant-b",
                conversation_id="conversation-a",
                visitor_session_id="visitor-a",
            )
        ]
    )
    service = EscalationService(repo)

    with pytest.raises(ConversationNotFoundError):
        service.escalate(escalation_payload())

    assert repo.escalations == []


def test_escalate_requires_matching_visitor_session():
    service = EscalationService(escalation_repo())

    with pytest.raises(EscalationValidationError):
        service.escalate(escalation_payload(visitor_session_id="other-session"))


def test_escalate_is_idempotent_for_open_conversation():
    repo = escalation_repo()
    service = EscalationService(repo)

    first = service.escalate(escalation_payload())
    second = service.escalate(escalation_payload(reason="low_confidence"))

    assert second.escalation_id == first.escalation_id
    assert second.deduplicated is True
    assert len(repo.escalations) == 1


def test_escalate_redacts_secrets_from_summary_before_storage():
    repo = escalation_repo()
    service = EscalationService(repo)

    service.escalate(escalation_payload(summary="token=abc123456 should not persist"))

    assert repo.escalations[0].summary == "[REDACTED] should not persist"


def test_router_drops_high_confidence_spam_without_calling_tools():
    router = RouterService(classifier=FixedClassifier("spam", 0.95))

    result = router.route(router_payload(message="free money crypto pump"))

    assert result.decision == "drop"
    assert result.classification.label == "spam"


def test_router_sends_low_confidence_turn_to_agent():
    router = RouterService(classifier=FixedClassifier("unknown", 0.4))

    result = router.route(router_payload(message="This needs multiple steps"))

    assert result.decision == "agent"


def test_router_calls_rag_for_high_confidence_faq():
    rag_tool = StubRagTool(status="ok")
    router = RouterService(classifier=FixedClassifier("faq", 0.91), rag_tool=rag_tool)

    result = router.route(router_payload(message="What are your hours?"))

    assert result.decision == "rag"
    assert rag_tool.calls[0]["tenant_id"] == "tenant-a"
    assert rag_tool.calls[0]["query"] == "What are your hours?"
    assert rag_tool.calls[0]["filters"] == {"published_only": True}


def test_router_hands_off_to_agent_when_rag_is_not_confident():
    rag_tool = StubRagTool(status="low_confidence")
    router = RouterService(classifier=FixedClassifier("faq", 0.91), rag_tool=rag_tool)

    result = router.route(router_payload(message="What is your refund policy?"))

    assert result.decision == "agent"


def test_router_asks_for_contact_before_capturing_lead():
    lead_service = LeadService(InMemoryLeadRepository())
    router = RouterService(
        classifier=FixedClassifier("sales", 0.9),
        lead_tool=lead_service,
    )

    result = router.route(router_payload(message="I want a demo"))

    assert result.decision == "capture_lead"
    assert result.lead_result is None
    assert "email or phone" in result.response


def test_router_captures_lead_when_contact_is_present():
    repo = InMemoryLeadRepository()
    lead_service = LeadService(repo)
    router = RouterService(
        classifier=FixedClassifier("sales", 0.9),
        lead_tool=lead_service,
    )

    result = router.route(
        router_payload(message="I want a demo", contact_email="buyer@example.com")
    )

    assert result.decision == "capture_lead"
    assert result.lead_result is not None
    assert result.lead_result.tenant_id == "tenant-a"
    assert repo.records[0].email == "buyer@example.com"


def test_router_escalates_human_handoff_requests():
    escalation_service = EscalationService(escalation_repo())
    router = RouterService(
        classifier=FixedClassifier("human_handoff", 0.92),
        escalation_tool=escalation_service,
    )

    result = router.route(router_payload(message="I want to talk to a person"))

    assert result.decision == "escalate"
    assert result.escalation_result is not None
    assert result.escalation_result.tenant_id == "tenant-a"


def test_router_rejects_unknown_request_fields():
    router = RouterService(classifier=FixedClassifier("faq", 0.9))

    with pytest.raises(RouterValidationError):
        router.route(router_payload(tenant_override="tenant-b"))


def test_agent_calls_rag_then_capture_lead_for_multi_step_turn():
    rag_tool = StubRagTool(status="ok")
    lead_repo = InMemoryLeadRepository()
    lead_service = LeadService(lead_repo)
    agent = AgentService(
        tool_registry=ToolRegistry(rag_tool=rag_tool, lead_tool=lead_service),
        planner=SequencePlanner(
            [
                ToolPlan("rag_search", "answer first"),
                ToolPlan("capture_lead", "capture follow-up"),
            ]
        ),
    )

    result = agent.run(agent_payload())

    assert [call.tool_name for call in result.tool_calls] == [
        "rag_search",
        "capture_lead",
    ]
    assert result.stopped_reason == "final"
    assert rag_tool.calls[0]["tenant_id"] == "tenant-a"
    assert rag_tool.calls[0]["filters"] == {"published_only": True}
    assert lead_repo.records[0].tenant_id == "tenant-a"
    assert lead_repo.records[0].email == "buyer@example.com"


def test_agent_escalates_when_planner_selects_human_handoff():
    escalation_service = EscalationService(escalation_repo())
    agent = AgentService(
        tool_registry=ToolRegistry(escalation_tool=escalation_service),
        planner=SequencePlanner([ToolPlan("escalate", "human needed")]),
    )

    result = agent.run(agent_payload(message="I need a person"))

    assert result.tool_calls[0].tool_name == "escalate"
    assert result.tool_calls[0].payload["tenant_id"] == "tenant-a"
    assert result.stopped_reason == "final"


def test_agent_stops_when_tool_is_unavailable():
    agent = AgentService(
        tool_registry=ToolRegistry(),
        planner=SequencePlanner([ToolPlan("rag_search", "try rag")]),
    )

    result = agent.run(agent_payload())

    assert result.tool_calls == []
    assert result.stopped_reason == "tool_unavailable"


def test_agent_enforces_iteration_limit():
    rag_tool = StubRagTool(status="ok")
    agent = AgentService(
        tool_registry=ToolRegistry(rag_tool=rag_tool),
        planner=RepeatingPlanner("rag_search"),
        max_iterations=2,
    )

    result = agent.run(agent_payload())

    assert [call.tool_name for call in result.tool_calls] == ["rag_search", "rag_search"]
    assert result.stopped_reason == "loop_limit"
    assert result.final_response == "I reached the tool limit for this turn."


def test_agent_rejects_unknown_request_fields():
    agent = AgentService(tool_registry=ToolRegistry())

    with pytest.raises(AgentValidationError):
        agent.run(agent_payload(tenant_override="tenant-b"))


def test_agent_heuristic_planner_uses_allowed_tools_only():
    escalation_service = EscalationService(escalation_repo())
    agent = AgentService(tool_registry=ToolRegistry(escalation_tool=escalation_service))

    result = agent.run(agent_payload(message="I need to talk to a human"))

    assert [call.tool_name for call in result.tool_calls] == ["escalate"]
    assert result.stopped_reason == "final"


def test_anthropic_planner_reads_key_from_environment(monkeypatch):
    calls = []

    def fake_post_json(url, payload, headers, timeout_seconds):
        calls.append((url, payload, headers, timeout_seconds))
        return {
            "content": [
                {
                    "type": "tool_use",
                    "input": {
                        "tool_name": "rag_search",
                        "reason": "answer from tenant docs",
                        "final_response": None,
                    },
                }
            ],
            "usage": {"input_tokens": 31, "output_tokens": 9},
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    cost_tracker = RecordingCostTracker()
    planner = AnthropicAgentPlanner(
        post_json=fake_post_json,
        cost_tracker=cost_tracker,
    )

    plan = planner.plan(request=agent_payload_model(), tool_calls=[])

    assert plan.tool_name == "rag_search"
    assert calls[0][1]["model"] == "test-model"
    assert calls[0][2]["x-api-key"] == "test-key"
    assert "tenant-a" not in calls[0][1]["messages"][0]["content"]
    assert cost_tracker.calls == [
        {
            "tenant_id": "tenant-a",
            "provider": "anthropic",
            "model": "test-model",
            "input_tokens": 31,
            "output_tokens": 9,
        }
    ]


def test_anthropic_planner_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(AgentConfigurationError):
        AnthropicAgentPlanner()


def test_anthropic_planner_rejects_invalid_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    planner = AnthropicAgentPlanner(post_json=lambda *_args: {"content": [{"text": "nope"}]})

    with pytest.raises(AgentPlannerError):
        planner.plan(request=agent_payload_model(), tool_calls=[])


def agent_payload_model():
    from app.services.agent_service import AgentRequest

    return AgentRequest.model_validate(agent_payload())
