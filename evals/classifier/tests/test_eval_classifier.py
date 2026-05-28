# Owner: Jana
"""T034 — pin `compute_macro_f1` against a hand-computed reference so a
future scikit-learn upgrade can't silently change the gate's behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "eval_classifier.py"
_spec = importlib.util.spec_from_file_location("eval_classifier", _MODULE_PATH)
assert _spec and _spec.loader
eval_classifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_classifier)  # type: ignore[union-attr]


def test_macro_f1_matches_hand_computed():
    # Two classes A and B, two examples per class.
    # Predictions: 3 correct (A,A,B,_), 1 wrong (B predicted as A).
    # Per-class:
    #   A:  precision = 2/3,    recall = 2/2 = 1,     F1 = 2 * (2/3) / (5/3) = 4/5 = 0.8
    #   B:  precision = 1/1 = 1, recall = 1/2 = 0.5, F1 = 2 * 0.5 / 1.5 = 2/3 ≈ 0.6667
    # macro = (0.8 + 0.6667) / 2 ≈ 0.7333
    predictions = ["A", "A", "B", "A"]
    gold = ["A", "A", "B", "B"]
    assert abs(eval_classifier.compute_macro_f1(predictions, gold) - 0.7333333333333334) < 1e-6
