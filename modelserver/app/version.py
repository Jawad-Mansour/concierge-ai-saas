# Owner: Jana
"""Model-hash holder. Set once at boot by `model_loader.load`."""

from __future__ import annotations

MODEL_HASH: str | None = None


def set_model_hash(value: str) -> None:
    global MODEL_HASH
    MODEL_HASH = value


def get_model_hash() -> str:
    if MODEL_HASH is None:
        raise RuntimeError("MODEL_HASH accessed before boot — model_loader.load() must run first")
    return MODEL_HASH
