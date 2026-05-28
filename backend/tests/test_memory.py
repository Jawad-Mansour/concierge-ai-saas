# Owner: Ali
import pytest

from app.services.memory_service import (
    InMemoryMemoryStore,
    MemoryService,
    MemoryValidationError,
    TenantContextError,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def memory_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "role": "user",
        "content": "I need pricing details.",
        "trace_id": "trace-a",
    }
    payload.update(overrides)
    return payload


def memory_service(*, ttl_seconds=30, max_messages=20):
    clock = FakeClock()
    store = InMemoryMemoryStore(clock=clock)
    service = MemoryService(
        store,
        ttl_seconds=ttl_seconds,
        max_messages=max_messages,
        clock=clock,
    )
    return service, clock


def test_memory_appends_and_reads_messages_for_same_tenant_conversation():
    service, _clock = memory_service()

    message = service.append_message(memory_payload())
    messages = service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a")

    assert message.content == "I need pricing details."
    assert messages == [message]


def test_memory_is_scoped_by_tenant_and_conversation():
    service, _clock = memory_service()

    service.append_message(memory_payload())
    service.append_message(
        memory_payload(
            tenant_id="tenant-b",
            conversation_id="conversation-a",
            content="Tenant B question.",
        )
    )
    service.append_message(
        memory_payload(
            tenant_id="tenant-a",
            conversation_id="conversation-b",
            content="Other conversation.",
        )
    )

    messages = service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a")

    assert [message.content for message in messages] == ["I need pricing details."]


def test_memory_expires_after_ttl():
    service, clock = memory_service(ttl_seconds=30)

    service.append_message(memory_payload())
    clock.advance(31)

    assert service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a") == []


def test_memory_append_refreshes_ttl():
    service, clock = memory_service(ttl_seconds=30)

    service.append_message(memory_payload(content="First"))
    clock.advance(20)
    service.append_message(memory_payload(content="Second", role="assistant"))
    clock.advance(20)

    messages = service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a")

    assert [message.content for message in messages] == ["First", "Second"]


def test_memory_keeps_only_latest_messages():
    service, _clock = memory_service(max_messages=2)

    service.append_message(memory_payload(content="One"))
    service.append_message(memory_payload(content="Two", role="assistant"))
    service.append_message(memory_payload(content="Three"))

    messages = service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a")

    assert [message.content for message in messages] == ["Two", "Three"]


def test_memory_prompt_context_formats_history_in_order():
    service, _clock = memory_service()

    service.append_message(memory_payload(content="Hello"))
    service.append_message(memory_payload(role="assistant", content="Hi there"))

    assert (
        service.prompt_context(tenant_id="tenant-a", conversation_id="conversation-a")
        == "user: Hello\nassistant: Hi there"
    )


def test_memory_rejects_empty_content_and_unknown_fields():
    service, _clock = memory_service()

    with pytest.raises(MemoryValidationError):
        service.append_message(memory_payload(content=" "))

    with pytest.raises(MemoryValidationError):
        service.append_message(memory_payload(tenant_override="tenant-b"))


def test_memory_requires_tenant_context_for_reads_and_writes():
    service, _clock = memory_service()

    with pytest.raises(MemoryValidationError):
        service.append_message(memory_payload(tenant_id=" "))

    with pytest.raises(TenantContextError):
        service.get_messages(tenant_id=" ", conversation_id="conversation-a")


def test_memory_clear_removes_only_target_conversation():
    service, _clock = memory_service()

    service.append_message(memory_payload())
    service.append_message(
        memory_payload(conversation_id="conversation-b", content="Keep this")
    )

    service.clear_conversation(tenant_id="tenant-a", conversation_id="conversation-a")

    assert service.get_messages(tenant_id="tenant-a", conversation_id="conversation-a") == []
    assert [
        message.content
        for message in service.get_messages(
            tenant_id="tenant-a",
            conversation_id="conversation-b",
        )
    ] == ["Keep this"]


def test_memory_key_matches_tenant_erasure_pattern():
    service, _clock = memory_service()

    assert (
        service._key("tenant-a", "conversation-a")
        == "session:tenant:tenant-a:conversation:conversation-a:memory"
    )
