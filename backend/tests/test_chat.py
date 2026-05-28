# Owner: Ali
from types import SimpleNamespace

import pytest

import app.api.chat as chat_api
from app.api.chat import ChatRequestBody, chat
from app.repositories.embedding_repo import EmbeddingChunk, InMemoryEmbeddingRepository
from app.repositories.lead_repo import InMemoryLeadRepository
from app.services.agent_service import (
    AgentService,
    HeuristicAgentPlanner,
    ToolPlan,
    ToolRegistry,
)
from app.services.chat_service import ChatService, ChatValidationError
from app.services.lead_service import LeadService
from app.services.memory_service import InMemoryMemoryStore, MemoryService
from app.services.rag_service import RagService
from app.services.router_service import RouterService


class FixedClassifier:
    def __init__(self, label, confidence, degraded=False):
        self.label = label
        self.confidence = confidence
        self.degraded = degraded

    def classify(self, message):
        return self.label, self.confidence


class JanaClassification:
    def __init__(self, predicted_class, confidence, degraded=False):
        self.predicted_class = predicted_class
        self.confidence = confidence
        self.degraded = degraded


class AsyncClassifierClient:
    def __init__(self, classification):
        self.classification = classification
        self.calls = []

    async def classify(self, *, tenant_id, message):
        self.calls.append({"tenant_id": tenant_id, "message": message})
        return self.classification


class SequencePlanner:
    def __init__(self, plans):
        self.plans = plans

    def plan(self, *, request, tool_calls):
        if len(tool_calls) >= len(self.plans):
            return ToolPlan(None, "done", final_response="Agent handled it.")
        return self.plans[len(tool_calls)]


def chat_payload(**overrides):
    payload = {
        # Mocked Mohammad/Charbel-owned auth input:
        # the final chat API must derive tenant_id from a verified widget token.
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "message": "What does the team plan cost?",
        # Mocked Charbel-owned widget input.
        "source_url": "https://tenant-a.example/pricing",
        "trace_id": "trace-a",
    }
    payload.update(overrides)
    return payload


def rag_service():
    return RagService(
        InMemoryEmbeddingRepository(
            [
                EmbeddingChunk(
                    chunk_id="a-pricing",
                    tenant_id="tenant-a",
                    cms_content_id="cms-a-pricing",
                    title="Pricing",
                    text="Team pricing starts at 49 dollars per month.",
                )
            ]
        )
    )


def memory_service():
    return MemoryService(InMemoryMemoryStore())


def test_chat_routes_faq_to_rag_and_stores_memory():
    memory = memory_service()
    service = ChatService(
        memory_service=memory,
        router_service=RouterService(
            classifier=FixedClassifier("faq", 0.92),
            rag_tool=rag_service(),
        ),
    )

    response = service.handle_message(chat_payload())

    assert response.decision == "rag"
    assert response.message == "Team pricing starts at 49 dollars per month."
    assert [
        message.role
        for message in memory.get_messages(
            tenant_id="tenant-a",
            conversation_id="conversation-a",
        )
    ] == ["user", "assistant"]


def test_chat_uses_agent_when_router_hands_off():
    memory = memory_service()
    agent = AgentService(
        tool_registry=ToolRegistry(
            rag_tool=rag_service(),
            lead_tool=LeadService(repository=InMemoryLeadRepository()),
        ),
        planner=SequencePlanner([ToolPlan("rag_search", "need tenant knowledge")]),
    )
    service = ChatService(
        memory_service=memory,
        router_service=RouterService(classifier=FixedClassifier("unknown", 0.2)),
        agent_service=agent,
    )

    response = service.handle_message(chat_payload(message="Pricing and follow up please"))

    assert response.decision == "agent"
    assert response.message == "Agent handled it."


def test_chat_rejects_unknown_fields():
    service = ChatService(
        memory_service=memory_service(),
        router_service=RouterService(classifier=FixedClassifier("spam", 0.95)),
    )

    with pytest.raises(ChatValidationError):
        service.handle_message(chat_payload(tenant_override="tenant-b"))


def test_chat_uses_jana_classifier_result_when_supplied():
    service = ChatService(
        memory_service=memory_service(),
        router_service=RouterService(rag_tool=rag_service()),
    )

    response = service.handle_message(
        chat_payload(),
        classification=JanaClassification("FAQ", 0.91),
    )

    assert response.decision == "rag"
    assert response.message == "Team pricing starts at 49 dollars per month."


def test_chat_treats_degraded_jana_classifier_as_agent():
    service = ChatService(
        memory_service=memory_service(),
        router_service=RouterService(rag_tool=rag_service()),
    )

    response = service.handle_message(
        chat_payload(),
        classification=JanaClassification("FAQ", 0.91, degraded=True),
    )

    assert response.decision == "agent"


@pytest.mark.anyio
async def test_chat_api_reads_classifier_from_app_state():
    classifier = AsyncClassifierClient(JanaClassification("FAQ", 0.91))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(classifier_client=classifier)))
    service = ChatService(
        memory_service=memory_service(),
        router_service=RouterService(rag_tool=rag_service()),
    )

    response = await chat(
        request,
        ChatRequestBody(**chat_payload()),
        chat_service=service,
    )

    assert response["decision"] == "rag"
    assert classifier.calls == [
        {"tenant_id": "tenant-a", "message": "What does the team plan cost?"}
    ]


def test_chat_service_factory_uses_redis_memory_store_when_available(monkeypatch):
    calls = []

    class FakeRedisMemoryStore:
        def __init__(self):
            calls.append("redis")

        def append(self, **kwargs):
            return None

        def get(self, **kwargs):
            return []

        def clear(self, **kwargs):
            return None

    monkeypatch.setattr(chat_api, "RedisMemoryStore", FakeRedisMemoryStore)

    service = chat_api.build_chat_service()

    assert isinstance(service.memory_service.store, FakeRedisMemoryStore)
    assert calls == ["redis"]


def test_chat_service_factory_falls_back_to_in_memory_when_redis_unavailable(monkeypatch):
    class BrokenRedisMemoryStore:
        def __init__(self):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(chat_api, "RedisMemoryStore", BrokenRedisMemoryStore)

    service = chat_api.build_chat_service()

    assert isinstance(service.memory_service.store, InMemoryMemoryStore)


def test_chat_service_factory_uses_anthropic_planner_when_key_is_configured(monkeypatch):
    created = []

    class FakeAnthropicPlanner:
        def __init__(self):
            created.append("anthropic")

        def plan(self, *, request, tool_calls):
            return ToolPlan(None, "fake anthropic", final_response="Anthropic handled it.")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-real-looking-key")
    monkeypatch.setattr(chat_api, "AnthropicAgentPlanner", FakeAnthropicPlanner)

    service = chat_api.build_chat_service()

    assert created == ["anthropic"]
    assert isinstance(service.agent_service.planner, FakeAnthropicPlanner)


def test_chat_service_factory_uses_heuristic_planner_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    service = chat_api.build_chat_service()

    assert isinstance(service.agent_service.planner, HeuristicAgentPlanner)


def test_chat_service_factory_ignores_placeholder_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "replace-me")

    service = chat_api.build_chat_service()

    assert isinstance(service.agent_service.planner, HeuristicAgentPlanner)
