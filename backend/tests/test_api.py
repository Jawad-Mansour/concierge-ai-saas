# Owner: Ali
from app.api.cms import CmsIngestBody, ingest_content
from app.api.leads import LeadCaptureBody, capture_lead
from app.repositories.cms_repo import InMemoryCmsRepository
from app.repositories.embedding_repo import InMemoryEmbeddingRepository
from app.repositories.lead_repo import InMemoryLeadRepository
from app.services.embedding_service import EmbeddingService
from app.services.lead_service import LeadService


def test_leads_api_capture_uses_service_layer():
    repo = InMemoryLeadRepository()
    response = capture_lead(
        LeadCaptureBody(
            tenant_id="tenant-a",
            conversation_id="conversation-a",
            visitor_session_id="visitor-a",
            intent="I want a demo",
            email="buyer@example.com",
        ),
        lead_service=LeadService(repo),
    )

    assert response["tenant_id"] == "tenant-a"
    assert response["conversation_id"] == "conversation-a"
    assert repo.records[0].email == "buyer@example.com"


def test_cms_api_ingest_uses_embedding_service_layer():
    cms_repo = InMemoryCmsRepository()
    embedding_repo = InMemoryEmbeddingRepository()
    response = ingest_content(
        CmsIngestBody(
            tenant_id="tenant-a",
            content_id="cms-a",
            title="Pricing",
            body="Pricing starts at 49 dollars per month.",
            url="https://tenant-a.example/pricing",
        ),
        embedding_service=EmbeddingService(
            cms_repository=cms_repo,
            embedding_repository=embedding_repo,
        ),
    )

    assert response == {
        "tenant_id": "tenant-a",
        "content_id": "cms-a",
        "chunk_count": 1,
    }
    assert cms_repo.list_chunks(tenant_id="tenant-a")[0].cms_content_id == "cms-a"
