# Owner: Jana
"""T031 — model_loader.load() refuses to start on hash mismatch / missing / truncated artifact."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app import model_loader


def _write_card(dir_: Path, *, sha256: str, artifact_type: str = "joblib", filename: str = "classifier.joblib") -> None:
    (dir_ / "model_card.md").write_text(
        f"""---
artifact_filename: {filename}
artifact_type: {artifact_type}
sha256: {sha256}
training_data_revision: abc123
training_script_revision: def456
intended_task: 5-class intent classification
unknown_threshold: 0.25
---
""",
        encoding="utf-8",
    )


def test_load_succeeds_when_hash_matches(tmp_path: Path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = b"\x80\x04\x95"  # arbitrary bytes — joblib backend instantiation is patched below
    artifact = artifacts / "classifier.joblib"
    artifact.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    _write_card(artifacts, sha256=digest)

    monkeypatch.setattr(model_loader, "SklearnBackend", lambda path: object())
    loaded = model_loader.load(artifacts_dir=artifacts)
    assert loaded.model_hash_full == digest


def test_load_exits_on_hash_mismatch(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "classifier.joblib").write_bytes(b"not the expected bytes")
    _write_card(artifacts, sha256="0" * 64)

    with pytest.raises(SystemExit) as excinfo:
        model_loader.load(artifacts_dir=artifacts)
    assert excinfo.value.code == 1


def test_load_exits_on_missing_artifact(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _write_card(artifacts, sha256="0" * 64)
    # artifact file deliberately absent
    with pytest.raises(SystemExit) as excinfo:
        model_loader.load(artifacts_dir=artifacts)
    assert excinfo.value.code == 1


def test_load_exits_on_truncated_artifact(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    full = b"the complete artifact body" * 64
    truncated = full[:64]
    (artifacts / "classifier.joblib").write_bytes(truncated)
    _write_card(artifacts, sha256=hashlib.sha256(full).hexdigest())

    with pytest.raises(SystemExit) as excinfo:
        model_loader.load(artifacts_dir=artifacts)
    assert excinfo.value.code == 1


def test_load_exits_on_missing_card_fields(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "classifier.joblib").write_bytes(b"x")
    (artifacts / "model_card.md").write_text("---\nartifact_filename: classifier.joblib\n---\n")
    with pytest.raises(SystemExit):
        model_loader.load(artifacts_dir=artifacts)


def test_load_exits_on_artifact_extension_mismatch(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "classifier.bin").write_bytes(b"x")
    _write_card(
        artifacts, sha256=hashlib.sha256(b"x").hexdigest(), filename="classifier.bin"
    )
    with pytest.raises(SystemExit):
        model_loader.load(artifacts_dir=artifacts)
