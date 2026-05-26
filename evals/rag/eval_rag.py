# Owner: Ali
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.repositories.embedding_repo import (  # noqa: E402
    EmbeddingChunk,
    InMemoryEmbeddingRepository,
)
from app.services.rag_service import RagService  # noqa: E402


@dataclass(frozen=True)
class RagEvalCase:
    name: str
    tenant_id: str
    query: str
    expected_chunk_id: str


@dataclass(frozen=True)
class RagEvalResult:
    total: int
    hits: int
    recall_at_k: float
    failures: list[str]


DEFAULT_CASES = [
    RagEvalCase(
        name="tenant_a_pricing",
        tenant_id="tenant-a",
        query="How much is the team plan?",
        expected_chunk_id="a-pricing",
    ),
    RagEvalCase(
        name="tenant_a_support",
        tenant_id="tenant-a",
        query="Do you help with onboarding?",
        expected_chunk_id="a-pricing",
    ),
]


def build_demo_service() -> RagService:
    repo = InMemoryEmbeddingRepository(
        [
            EmbeddingChunk(
                chunk_id="a-pricing",
                tenant_id="tenant-a",
                cms_content_id="cms-a-pricing",
                title="Pricing",
                text="Team pricing starts at 49 dollars per month with onboarding support.",
                url="https://tenant-a.example/pricing",
            ),
            EmbeddingChunk(
                chunk_id="b-pricing",
                tenant_id="tenant-b",
                cms_content_id="cms-b-pricing",
                title="Tenant B Pricing",
                text="Tenant B enterprise pricing includes private support.",
                url="https://tenant-b.example/pricing",
            ),
        ]
    )
    return RagService(repo)


def run_eval(service: RagService, cases: list[RagEvalCase], *, top_k: int) -> RagEvalResult:
    hits = 0
    failures: list[str] = []
    for case in cases:
        result = service.search(
            {
                "tenant_id": case.tenant_id,
                "conversation_id": f"eval-{case.name}",
                "query": case.query,
                "top_k": top_k,
                "filters": {"published_only": True},
            }
        )
        chunk_ids = {citation.chunk_id for citation in result.citations}
        if case.expected_chunk_id in chunk_ids:
            hits += 1
        else:
            failures.append(case.name)
    total = len(cases)
    recall_at_k = hits / total if total else 0.0
    return RagEvalResult(total=total, hits=hits, recall_at_k=recall_at_k, failures=failures)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RAG golden-set eval.")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    result = run_eval(build_demo_service(), DEFAULT_CASES, top_k=args.top_k)
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"RAG recall@{args.top_k}: {result.recall_at_k:.2f} ({result.hits}/{result.total})")
        if result.failures:
            print("Failures: " + ", ".join(result.failures))
    return 0 if result.failures == [] else 1


if __name__ == "__main__":
    raise SystemExit(main())
