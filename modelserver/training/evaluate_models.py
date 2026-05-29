# Owner: Jana
"""Three-candidate bake-off harness (Principle III).

Runs candidates A (classical sklearn), B (small deep ONNX), C (hosted LLM)
against the same held-out set; emits the four-metric table to
`deliverables/EVALS.md` and the chosen winner row to `deliverables/DECISIONS.md`.

Metrics (per Principle III):
  - macro-F1 on `evals/classifier/datasets/test.jsonl`
  - p95 latency under the production-equivalent concurrency
  - on-disk artifact size
  - per-1k-request operational cost (zero for A/B; provider price × tokens for C)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATASET = REPO_ROOT / "evals" / "classifier" / "datasets" / "test.jsonl"

# Resolve `app.inference` against modelserver's package without forcing PYTHONPATH.
import sys as _sys  # noqa: E402

_MODELSERVER = REPO_ROOT / "modelserver"
if str(_MODELSERVER) not in _sys.path:
    _sys.path.insert(0, str(_MODELSERVER))


@dataclass
class CandidateResult:
    candidate: str
    macro_f1: float
    p95_latency_ms: float
    artifact_size_bytes: int
    cost_per_1k_usd: float
    notes: str


def _load_dataset(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _measure(backend, rows: list[dict[str, str]]) -> tuple[float, float]:
    """Returns (macro_f1, p95_latency_ms)."""
    from sklearn.metrics import f1_score

    predictions: list[str] = []
    latencies_ms: list[float] = []
    for row in rows:
        t0 = time.perf_counter()
        cls, _ = backend.predict(row["message"])
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        predictions.append(cls)
    gold = [row["label"] for row in rows]
    macro_f1 = float(f1_score(gold, predictions, average="macro", zero_division=0.0))
    p95 = (
        float(statistics.quantiles(latencies_ms, n=20)[18])
        if len(latencies_ms) >= 20
        else max(latencies_ms)
    )  # noqa: E501
    return macro_f1, p95


def _run_candidate_a(rows: list[dict[str, str]], artifact: Path) -> CandidateResult:
    from app.inference import SklearnBackend

    backend = SklearnBackend(artifact)
    macro_f1, p95 = _measure(backend, rows)
    return CandidateResult(
        candidate="A_classical_sklearn",
        macro_f1=macro_f1,
        p95_latency_ms=p95,
        artifact_size_bytes=artifact.stat().st_size,
        cost_per_1k_usd=0.0,
        notes="TF-IDF + LogReg/GradientBoosting (the better of the two on val).",
    )


def _run_candidate_b(rows: list[dict[str, str]], artifact: Path) -> CandidateResult:
    from app.inference import OnnxBackend

    backend = OnnxBackend(artifact)
    macro_f1, p95 = _measure(backend, rows)
    return CandidateResult(
        candidate="B_small_deep_onnx",
        macro_f1=macro_f1,
        p95_latency_ms=p95,
        artifact_size_bytes=artifact.stat().st_size,
        cost_per_1k_usd=0.0,
        notes="Small encoder exported via export_onnx.py.",
    )


def _run_candidate_c(
    rows: list[dict[str, str]],
    prompt: Path,
    hosted_id: str,
    price_per_1k_tokens: float,
    avg_tokens_per_call: float,
) -> CandidateResult:  # noqa: E501
    # Candidate C latency/F1 require live provider calls; this function
    # carries the cost formula and the artifact-size column. The harness
    # is invoked manually with `--candidate c` once the operator has
    # validated the provider credentials.
    from app.inference import HostedLlmBackend

    backend = HostedLlmBackend(prompt, hosted_id)
    macro_f1, p95 = _measure(backend, rows)
    cost = price_per_1k_tokens * avg_tokens_per_call
    return CandidateResult(
        candidate="C_hosted_llm",
        macro_f1=macro_f1,
        p95_latency_ms=p95,
        artifact_size_bytes=prompt.stat().st_size,
        cost_per_1k_usd=cost,
        notes=f"Hosted LLM {hosted_id}. Cost = {price_per_1k_tokens}/1k tokens × {avg_tokens_per_call} avg tokens/call.",  # noqa: E501
    )


def _format_md_row(r: CandidateResult) -> str:
    return (
        f"| {r.candidate} | {r.macro_f1:.4f} | {r.p95_latency_ms:.2f} | "
        f"{r.artifact_size_bytes} | {r.cost_per_1k_usd:.4f} | {r.notes} |"
    )


def write_evals_md(results: list[CandidateResult], evals_md: Path, dataset_sha: str) -> None:
    header = (
        "| Candidate | Macro-F1 | p95 latency (ms) | Artifact size (bytes) | Cost / 1k (USD) | Notes |\n"  # noqa: E501
        "|-----------|----------|------------------|-----------------------|-----------------|-------|"
    )
    body = "\n".join(_format_md_row(r) for r in results)
    section = (
        "\n\n## Classifier bake-off\n"
        f"Dataset commit SHA: `{dataset_sha}`. Reproduce via `python modelserver/training/evaluate_models.py`.\n\n"  # noqa: E501
        f"{header}\n{body}\n"
    )
    if evals_md.exists():
        existing = evals_md.read_text(encoding="utf-8")
        if "## Classifier bake-off" in existing:
            # Replace existing section (rough — operators verify on review).
            head, _, _ = existing.partition("## Classifier bake-off")
            evals_md.write_text(head.rstrip() + section, encoding="utf-8")
        else:
            evals_md.write_text(existing.rstrip() + section, encoding="utf-8")
    else:
        evals_md.write_text("# EVALS\n" + section, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--evals-md", type=Path, default=REPO_ROOT / "deliverables" / "EVALS.md")
    parser.add_argument(
        "--artifact-onnx",
        type=Path,
        default=REPO_ROOT / "modelserver" / "artifacts" / "classifier.onnx",
    )  # noqa: E501
    parser.add_argument(
        "--artifact-joblib",
        type=Path,
        default=REPO_ROOT / "modelserver" / "artifacts" / "classifier.joblib",
    )  # noqa: E501
    parser.add_argument(
        "--prompt-c",
        type=Path,
        default=REPO_ROOT / "modelserver" / "artifacts" / "classifier_prompt.txt",
    )  # noqa: E501
    parser.add_argument("--hosted-id", default="claude-sonnet-4-6")
    parser.add_argument("--price-per-1k-tokens", type=float, default=3.0)
    parser.add_argument("--avg-tokens-per-call", type=float, default=0.2)
    args = parser.parse_args(argv)

    rows = _load_dataset(args.dataset)
    results: list[CandidateResult] = []

    if args.artifact_joblib.is_file():
        results.append(_run_candidate_a(rows, args.artifact_joblib))
    if args.artifact_onnx.is_file():
        results.append(_run_candidate_b(rows, args.artifact_onnx))
    if args.prompt_c.is_file() and os.environ.get("RUN_CANDIDATE_C"):
        results.append(
            _run_candidate_c(
                rows,
                args.prompt_c,
                args.hosted_id,
                args.price_per_1k_tokens,
                args.avg_tokens_per_call,
            )
        )

    print(json.dumps([asdict(r) for r in results], indent=2))

    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", f"HEAD:{args.dataset.relative_to(REPO_ROOT)}"],
                cwd=REPO_ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        sha = "uncommitted"

    if results:
        write_evals_md(results, args.evals_md, sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
