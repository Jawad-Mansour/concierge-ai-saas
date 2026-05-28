# Owner: Jana
"""Held-out macro-F1 evaluator + CI gate.

Loads the shipped artifact via the same `modelserver.app.model_loader.load`
path the service uses (Principle II: only one hash-verified loader exists),
predicts over `evals/classifier/datasets/test.jsonl`, computes per-class
precision/recall + macro-F1, prints them as JSON, and exits non-zero if
macro-F1 falls below the threshold from `eval_thresholds.yaml`.

The dataset commit-SHA is printed so DECISIONS.md rows cite a reproducible
test set (research.md Decision 1 open risk: test-set leakage).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Resolve `app.model_loader` without forcing PYTHONPATH on the operator.
_MODELSERVER = Path(__file__).resolve().parent.parent.parent / "modelserver"
if str(_MODELSERVER) not in sys.path:
    sys.path.insert(0, str(_MODELSERVER))

import yaml
from sklearn.metrics import classification_report, f1_score


def compute_macro_f1(predictions: list[str], gold: list[str]) -> float:
    return float(f1_score(gold, predictions, average="macro", zero_division=0.0))


def _dataset_sha(dataset_path: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{dataset_path}"],
            cwd=dataset_path.parent.parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "uncommitted"


def evaluate(dataset_path: Path, threshold_path: Path) -> int:
    from app import model_loader

    loaded = model_loader.load()
    backend = loaded.backend

    predictions: list[str] = []
    gold: list[str] = []
    with dataset_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cls, _conf = backend.predict(row["message"])
            predictions.append(cls)
            gold.append(row["label"])

    macro_f1 = compute_macro_f1(predictions, gold)
    report = classification_report(gold, predictions, zero_division=0.0, output_dict=True)
    cfg = yaml.safe_load(threshold_path.read_text(encoding="utf-8"))
    threshold = float(cfg.get("macro_f1_min", 0.0))

    output = {
        "macro_f1": macro_f1,
        "threshold": threshold,
        "dataset_sha": _dataset_sha(dataset_path),
        "model_hash": loaded.model_hash_full,
        "per_class": report,
    }
    print(json.dumps(output, indent=2, sort_keys=True))

    return 0 if macro_f1 >= threshold else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent / "datasets" / "test.jsonl",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path(__file__).resolve().parent / "eval_thresholds.yaml",
    )
    args = parser.parse_args(argv)
    return evaluate(args.dataset, args.thresholds)


if __name__ == "__main__":
    sys.exit(main())
