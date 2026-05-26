# Owner: Ali
import pytest

from app.repositories.embedding_repo import EmbeddingChunk, InMemoryEmbeddingRepository
from app.services.rag_service import (
    CrossTenantRetrievalError,
    RagService,
    RagValidationError,
)


def rag_repo():
    return InMemoryEmbeddingRepository(
        [
            EmbeddingChunk(
                chunk_id="a-pricing",
                tenant_id="tenant-a",
                cms_content_id="cms-a-pricing",
                title="Pricing",
                text="Team pricing starts at 49 dollars per month with onboarding support.",
                url="https://tenant-a.example/pricing",
                content_type="page",
                locale="en",
            ),
            EmbeddingChunk(
                chunk_id="a-private-draft",
                tenant_id="tenant-a",
                cms_content_id="cms-a-draft",
                title="Draft",
                text="Unpublished discount policy for internal review.",
                content_type="page",
                published=False,
            ),
            EmbeddingChunk(
                chunk_id="b-pricing",
                tenant_id="tenant-b",
                cms_content_id="cms-b-pricing",
                title="Tenant B Pricing",
                text="Tenant B enterprise pricing includes private support.",
                url="https://tenant-b.example/pricing",
                content_type="page",
                locale="en",
            ),
        ]
    )


def rag_payload(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "query": "What does team pricing cost?",
        "top_k": 3,
        "filters": {"published_only": True},
    }
    payload.update(overrides)
    return payload


def test_rag_returns_ordered_context_and_citations_for_same_tenant():
    service = RagService(rag_repo())

    result = service.search(rag_payload())

    assert result.status == "ok"
    assert result.answer_context == [
        "Team pricing starts at 49 dollars per month with onboarding support."
    ]
    assert result.citations[0].chunk_id == "a-pricing"
    assert result.citations[0].cms_content_id == "cms-a-pricing"
    assert result.retrieval_meta.tenant_id == "tenant-a"
    assert result.retrieval_meta.returned_count == 1


def test_rag_never_returns_other_tenant_chunks_with_overlapping_text():
    service = RagService(rag_repo())

    result = service.search(rag_payload(query="enterprise pricing private support"))

    assert result.status == "ok"
    assert all(citation.chunk_id != "b-pricing" for citation in result.citations)
    assert {citation.chunk_id for citation in result.citations} == {"a-pricing"}


def test_rag_filters_unpublished_content():
    service = RagService(rag_repo())

    result = service.search(rag_payload(query="discount policy", filters={"published_only": True}))

    assert result.status == "no_results"
    assert result.answer_context == []
    assert result.citations == []


def test_rag_rejects_invalid_top_k_and_unknown_filters_before_search():
    service = RagService(rag_repo())

    with pytest.raises(RagValidationError):
        service.search(rag_payload(top_k=0))

    with pytest.raises(RagValidationError):
        service.search(rag_payload(filters={"tenant_id": "tenant-b"}))


def test_rag_low_confidence_returns_no_context():
    service = RagService(rag_repo())

    result = service.search(rag_payload(query="pricing", min_score=0.95))

    assert result.status == "low_confidence"
    assert result.answer_context == []
    assert result.citations == []


def test_rag_detects_repository_cross_tenant_leak():
    class LeakyRepository:
        def search(self, **kwargs):
            return [
                EmbeddingChunk(
                    chunk_id="leak",
                    tenant_id="tenant-b",
                    cms_content_id="cms-b",
                    title="Leak",
                    text="Other tenant text",
                )
            ]

    service = RagService(LeakyRepository())

    with pytest.raises(CrossTenantRetrievalError):
        service.search(rag_payload())
