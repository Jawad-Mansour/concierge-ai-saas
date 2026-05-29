# Owner: Ali
import pytest

from app.repositories.cms_repo import InMemoryCmsRepository
from app.repositories.embedding_repo import (
    EmbeddingChunk,
    InMemoryEmbeddingRepository,
    InMemoryVectorEmbeddingRepository,
)
from app.services.embedding_service import (
    EmbeddingService,
    IngestionValidationError,
)
from app.services.embedding_provider import HashingEmbeddingProvider, VoyageEmbeddingProvider
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


def test_ingest_cms_content_creates_tenant_scoped_chunks_searchable_by_rag():
    cms_repo = InMemoryCmsRepository()
    embedding_repo = InMemoryEmbeddingRepository()
    ingestion = EmbeddingService(
        cms_repository=cms_repo,
        embedding_repository=embedding_repo,
        chunk_size_words=8,
        chunk_overlap_words=2,
    )

    result = ingestion.ingest_content(
        {
            "tenant_id": "tenant-a",
            "content_id": "cms-a-hours",
            "title": "Hours",
            "body": "Our shop is open Monday through Friday from nine to five.",
            "url": "https://tenant-a.example/hours",
            "content_type": "page",
            "published": True,
        }
    )
    rag_result = RagService(embedding_repo).search(
        rag_payload(query="When is the shop open?", top_k=2)
    )

    assert result.tenant_id == "tenant-a"
    assert result.content_id == "cms-a-hours"
    assert result.chunk_count >= 1
    assert rag_result.status == "ok"
    assert rag_result.citations[0].cms_content_id == "cms-a-hours"


def test_ingest_cms_content_generates_embeddings_for_vector_retrieval():
    cms_repo = InMemoryCmsRepository()
    embedding_provider = HashingEmbeddingProvider(dimensions=16)
    embedding_repo = InMemoryVectorEmbeddingRepository(
        embedding_provider=embedding_provider,
    )
    ingestion = EmbeddingService(
        cms_repository=cms_repo,
        embedding_repository=embedding_repo,
        embedding_provider=embedding_provider,
        chunk_size_words=8,
        chunk_overlap_words=2,
    )

    ingestion.ingest_content(
        {
            "tenant_id": "tenant-a",
            "content_id": "cms-a-support",
            "title": "Support",
            "body": "Premium onboarding support is available every weekday.",
        }
    )
    result = RagService(embedding_repo, strategy="semantic_vector").search(
        rag_payload(query="weekday onboarding support", top_k=1)
    )

    assert result.status == "ok"
    assert result.retrieval_meta.strategy == "semantic_vector"
    assert result.citations[0].cms_content_id == "cms-a-support"


def test_voyage_embedding_provider_uses_voyage_api(monkeypatch):
    calls = []

    def fake_post_json(url, payload, headers, timeout_seconds):
        calls.append((url, payload, headers, timeout_seconds))
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setenv("VOYAGE_API_KEY", "test-voyage-key")
    provider = VoyageEmbeddingProvider(
        model="voyage-3.5",
        post_json=fake_post_json,
    )

    embedding = provider.embed_text("sample tenant text")

    assert embedding == [0.1, 0.2, 0.3]
    assert calls[0][0] == "https://api.voyageai.com/v1/embeddings"
    assert calls[0][1] == {"model": "voyage-3.5", "input": ["sample tenant text"]}
    assert calls[0][2]["authorization"] == "Bearer test-voyage-key"


def test_ingest_cms_content_rejects_unknown_or_empty_fields():
    ingestion = EmbeddingService(cms_repository=InMemoryCmsRepository())

    with pytest.raises(IngestionValidationError):
        ingestion.ingest_content(
            {
                "tenant_id": "tenant-a",
                "content_id": "cms-a",
                "title": " ",
                "body": "Some body",
            }
        )

    with pytest.raises(IngestionValidationError):
        ingestion.ingest_content(
            {
                "tenant_id": "tenant-a",
                "content_id": "cms-a",
                "title": "Title",
                "body": "Some body",
                "tenant_override": "tenant-b",
            }
        )


def test_ingest_cms_repository_lists_only_same_tenant_chunks():
    cms_repo = InMemoryCmsRepository()
    ingestion = EmbeddingService(
        cms_repository=cms_repo,
        chunk_size_words=6,
        chunk_overlap_words=1,
    )

    ingestion.ingest_content(
        {
            "tenant_id": "tenant-a",
            "content_id": "cms-a",
            "title": "Tenant A",
            "body": "Tenant A has public pricing information.",
        }
    )
    ingestion.ingest_content(
        {
            "tenant_id": "tenant-b",
            "content_id": "cms-b",
            "title": "Tenant B",
            "body": "Tenant B has private support information.",
        }
    )

    assert {chunk.tenant_id for chunk in cms_repo.list_chunks(tenant_id="tenant-a")} == {
        "tenant-a"
    }
