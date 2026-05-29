# Owner: Ali
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from json import JSONDecodeError
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


DATASET_DIR = Path(__file__).resolve().parent / "datasets"
DEFAULT_CORPUS_PATH = DATASET_DIR / "corpus.jsonl"
DEFAULT_GOLDEN_PATH = DATASET_DIR / "golden.jsonl"


class RagEvalDatasetError(ValueError):
    code = "rag_eval_dataset_error"


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


def load_corpus(path: Path) -> list[EmbeddingChunk]:
    rows = _load_jsonl(path, required_fields=("chunk_id", "tenant_id", "cms_content_id", "title", "text"))
    chunks: list[EmbeddingChunk] = []
    for row in rows:
        chunks.append(
            EmbeddingChunk(
                chunk_id=row["chunk_id"],
                tenant_id=row["tenant_id"],
                cms_content_id=row["cms_content_id"],
                title=row["title"],
                text=row["text"],
                url=row.get("url"),
                content_type=row.get("content_type"),
                page_id=row.get("page_id"),
                locale=row.get("locale"),
                published=bool(row.get("published", True)),
            )
        )
    return chunks


def load_cases(path: Path) -> list[RagEvalCase]:
    rows = _load_jsonl(path, required_fields=("name", "tenant_id", "query", "expected_chunk_id"))
    return [
        RagEvalCase(
            name=row["name"],
            tenant_id=row["tenant_id"],
            query=row["query"],
            expected_chunk_id=row["expected_chunk_id"],
        )
        for row in rows
    ]


def build_service(corpus_path: Path) -> RagService:
    return RagService(InMemoryEmbeddingRepository(load_corpus(corpus_path)))


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
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    try:
        result = run_eval(
            build_service(args.corpus),
            load_cases(args.golden),
            top_k=args.top_k,
        )
    except RagEvalDatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"RAG recall@{args.top_k}: {result.recall_at_k:.2f} ({result.hits}/{result.total})")
        if result.failures:
            print("Failures: " + ", ".join(result.failures))
    return 0 if result.failures == [] else 1


def _load_jsonl(path: Path, *, required_fields: tuple[str, ...]) -> list[dict]:
    if not path.exists():
        raise RagEvalDatasetError(f"{path} does not exist")

    rows: list[dict] = []
    with path.open(encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except JSONDecodeError as exc:
                raise RagEvalDatasetError(
                    f"{path}:{line_number} is not valid JSON: {exc.msg}"
                ) from exc
            if not isinstance(row, dict):
                raise RagEvalDatasetError(f"{path}:{line_number} must be a JSON object")
            _validate_required_fields(path, line_number, row, required_fields)
            rows.append(row)

    if not rows:
        raise RagEvalDatasetError(f"{path} must contain at least one data row")
    return rows


def _validate_required_fields(
    path: Path,
    line_number: int,
    row: dict,
    required_fields: tuple[str, ...],
) -> None:
    for field in required_fields:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RagEvalDatasetError(
                f"{path}:{line_number} missing required string field {field!r}"
            )
        row[field] = value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
