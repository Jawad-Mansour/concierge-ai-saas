# Owner: Jana
"""Boot-time hash verification + artifact load.

Refuses to start if the model card is malformed, the artifact is missing,
the on-disk SHA-256 differs from what the card declares, or the declared
artifact extension does not match the declared `artifact_type` (Principle II /
spec FR-007 / FR-008).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import version
from .inference import HostedLlmBackend, InferenceBackend, OnnxBackend, SklearnBackend

logger = logging.getLogger("modelserver.model_loader")

REQUIRED_FIELDS: tuple[str, ...] = (
    "artifact_filename",
    "artifact_type",
    "sha256",
    "training_data_revision",
    "training_script_revision",
    "intended_task",
    "unknown_threshold",
)

ARTIFACT_TYPES: dict[str, str] = {
    "onnx": ".onnx",
    "joblib": ".joblib",
    "hosted_llm_prompt": ".txt",
}

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)


@dataclass(frozen=True)
class LoadedArtifact:
    backend: InferenceBackend
    model_hash_full: str
    model_hash_short: str
    unknown_threshold: float
    artifact_type: str


def _structured(event: str, **fields: object) -> str:
    return json.dumps({"event": event, **fields}, sort_keys=True)


def _parse_card(card_path: Path) -> dict[str, str]:
    """Parse `key: value` lines (optionally inside `---` front-matter).

    The card is intentionally simple — full YAML parsing would pull in an
    extra runtime dep for no gain.
    """
    if not card_path.is_file():
        logger.error(_structured("model_card_missing", path=str(card_path)))
        sys.exit(1)
    raw = card_path.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(raw)
    body = m.group(1) if m else raw
    fields: dict[str, str] = {}
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(artifacts_dir: Path | None = None) -> LoadedArtifact:
    """Verify the artifact, instantiate the backend, set version.MODEL_HASH."""
    artifacts_dir = artifacts_dir or Path(__file__).resolve().parent.parent / "artifacts"
    card_path = artifacts_dir / "model_card.md"
    card = _parse_card(card_path)

    missing = [f for f in REQUIRED_FIELDS if f not in card]
    if missing:
        logger.error(_structured("model_card_invalid", missing_fields=missing))
        sys.exit(1)

    artifact_type = card["artifact_type"]
    if artifact_type not in ARTIFACT_TYPES:
        logger.error(_structured("model_card_invalid", reason="unknown artifact_type", value=artifact_type))
        sys.exit(1)

    artifact_path = artifacts_dir / card["artifact_filename"]
    expected_ext = ARTIFACT_TYPES[artifact_type]
    if artifact_path.suffix != expected_ext:
        logger.error(
            _structured(
                "model_card_invalid",
                reason="artifact_filename extension does not match artifact_type",
                filename=card["artifact_filename"],
                artifact_type=artifact_type,
                expected_ext=expected_ext,
            )
        )
        sys.exit(1)

    if not artifact_path.is_file():
        logger.error(_structured("artifact_missing", path=str(artifact_path)))
        sys.exit(1)

    expected_hash = card["sha256"].lower()
    actual_hash = _sha256_file(artifact_path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        logger.error(_structured("model_card_invalid", reason="sha256 not 64-hex"))
        sys.exit(1)

    if actual_hash != expected_hash:
        logger.error(
            _structured(
                "model_hash_mismatch",
                expected=expected_hash[:12],
                actual=actual_hash[:12],
                artifact=card["artifact_filename"],
            )
        )
        sys.exit(1)

    try:
        threshold = float(card["unknown_threshold"])
    except ValueError:
        logger.error(_structured("model_card_invalid", reason="unknown_threshold not float"))
        sys.exit(1)

    backend: InferenceBackend
    if artifact_type == "onnx":
        backend = OnnxBackend(artifact_path)
    elif artifact_type == "joblib":
        backend = SklearnBackend(artifact_path)
    else:  # hosted_llm_prompt
        hosted_id = card.get("hosted_model_identifier")
        if not hosted_id:
            logger.error(_structured("model_card_invalid", reason="hosted_model_identifier missing"))
            sys.exit(1)
        backend = HostedLlmBackend(artifact_path, hosted_id)

    short_hash = actual_hash[:12]
    version.set_model_hash(short_hash)
    logger.info(
        _structured(
            "model_hash_verified",
            sha256=actual_hash,
            artifact=card["artifact_filename"],
            artifact_type=artifact_type,
        )
    )
    return LoadedArtifact(
        backend=backend,
        model_hash_full=actual_hash,
        model_hash_short=short_hash,
        unknown_threshold=threshold,
        artifact_type=artifact_type,
    )
