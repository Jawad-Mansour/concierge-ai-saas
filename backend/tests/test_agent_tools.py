# Owner: Ali
import pytest

from app.repositories.conversation_repo import (
    ConversationRecord,
    InMemoryConversationRepository,
)
from app.repositories.lead_repo import InMemoryLeadRepository, LeadCreate
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
