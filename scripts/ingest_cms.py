# Owner: Ali
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.repositories.cms_repo import InMemoryCmsRepository  # noqa: E402
from app.repositories.embedding_repo import InMemoryEmbeddingRepository  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402


def load_pages(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("CMS input file must contain a JSON list of pages")
    return data


def run_ingest(*, tenant_id: str, pages: list[dict]) -> list[dict]:
    # Mocked Mohammad-owned persistence:
    # this script currently uses in-memory repositories until the tenant-scoped DB,
    # RLS policies, and pgvector repository are ready.
    cms_repo = InMemoryCmsRepository()
    embedding_repo = InMemoryEmbeddingRepository()
    service = EmbeddingService(
        cms_repository=cms_repo,
        embedding_repository=embedding_repo,
    )
    results = []
    for page in pages:
        result = service.ingest_content({"tenant_id": tenant_id, **page})
        results.append(asdict(result))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest tenant CMS content into RAG chunks.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--input", required=True, type=Path, help="Path to JSON list of CMS pages.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    results = run_ingest(tenant_id=args.tenant_id, pages=load_pages(args.input))
    if args.json:
        print(json.dumps({"results": results}, indent=2, sort_keys=True))
    else:
        for result in results:
            print(
                f"{result['tenant_id']} {result['content_id']}: "
                f"{result['chunk_count']} chunks"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
