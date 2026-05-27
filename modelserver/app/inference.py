# Owner: Jana
"""Inference backend protocol + implementations.

The orchestrator in `classifier.py` only knows about the `InferenceBackend`
Protocol — concrete backends are selected once at boot from `model_card.md`
and held on `app.state.backend`. The hot path never branches on backend type.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .schemas import IntentClass

CLASS_NAMES: tuple[IntentClass, ...] = (
    "SPAM",
    "FAQ",
    "ACCOUNT_OPS",
    "HARD_QUESTION",
    "UNKNOWN",
)


class InferenceBackend(Protocol):
    """A single-step, tenant-agnostic predictor."""

    def predict(self, message: str) -> tuple[IntentClass, float]: ...


class OnnxBackend:
    """ONNX runtime backend for `classifier.onnx` artifacts.

    Single-threaded session (latency over throughput at this scale —
    research.md Decision 2).
    """

    def __init__(self, artifact_path: Path) -> None:
        import onnxruntime as ort  # imported lazily so eval-only consumers can skip it

        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 1
        sess_options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(artifact_path), sess_options=sess_options, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name

    def predict(self, message: str) -> tuple[IntentClass, float]:
        import numpy as np

        # The exported model carries tokenization in-graph (a TfidfVectorizer or
        # an in-graph BPE) — input is a 1-element string tensor.
        inputs = np.array([[message]], dtype=object)
        outputs = self._session.run(None, {self._input_name: inputs})
        # Expected output: logits or probabilities of shape (1, 5).
        scores = np.asarray(outputs[0][0], dtype=np.float64)
        # Softmax if the model returns logits, identity if it already returns probabilities.
        if not (0.0 <= float(scores.min()) and float(scores.sum()) <= 1.0 + 1e-3):
            exp = np.exp(scores - scores.max())
            scores = exp / exp.sum()
        idx = int(np.argmax(scores))
        return CLASS_NAMES[idx], float(scores[idx])


class SklearnBackend:
    """Joblib + sklearn Pipeline backend for `classifier.joblib` artifacts."""

    def __init__(self, artifact_path: Path) -> None:
        import joblib

        self._pipeline = joblib.load(artifact_path)
        # The pipeline's `classes_` array gives the label order; if it differs
        # from CLASS_NAMES we still index off the pipeline's own order so we
        # don't silently mis-label.
        classes = getattr(self._pipeline, "classes_", None)
        if classes is not None:
            self._class_order: tuple[IntentClass, ...] = tuple(str(c) for c in classes)  # type: ignore[assignment]
        else:
            self._class_order = CLASS_NAMES

    def predict(self, message: str) -> tuple[IntentClass, float]:
        probs = self._pipeline.predict_proba([message])[0]
        idx = int(probs.argmax())
        label = self._class_order[idx]
        if label not in CLASS_NAMES:
            # Shipped artifact does not match the closed vocabulary — fail loud.
            raise RuntimeError(
                f"SklearnBackend produced class {label!r} not in {CLASS_NAMES!r}"
            )
        return label, float(probs[idx])  # type: ignore[return-value]


class HostedLlmBackend:
    """Hosted-LLM zero-shot backend (bake-off candidate C).

    Frozen prompt template + pinned hosted model identifier from `model_card.md`.
    Selected only when `artifact_type == "hosted_llm_prompt"`.
    """

    def __init__(self, prompt_path: Path, hosted_model_identifier: str) -> None:
        self._prompt_template = prompt_path.read_text(encoding="utf-8")
        self._model = hosted_model_identifier

    def predict(self, message: str) -> tuple[IntentClass, float]:
        # The actual provider SDK call is intentionally not wired here — the
        # team only selects this backend if the bake-off picks it; until then
        # the constructor remains importable but `predict` raises so the
        # orchestrator's fail-closed path engages on accidental selection.
        raise NotImplementedError(
            "HostedLlmBackend.predict is only wired once the bake-off (T036) picks candidate C"
        )
