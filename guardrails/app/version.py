# Owner: Jana
"""RAILS_CONFIG_HASH / RAILS_VERSION.

In a built image the Dockerfile overwrites this file with the pinned values
from the build-time hash computation. For local dev + tests we compute the
same hash on first import from the on-disk `config/*.yaml` files so the
suite can run without the container build step.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _compute_hash() -> str:
    h = hashlib.sha256()
    for path in sorted(_CONFIG_DIR.glob("*.yaml")):
        h.update(path.name.encode("utf-8"))
        h.update(b":")
        h.update(path.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


RAILS_CONFIG_HASH: str = _compute_hash()
RAILS_VERSION: str = RAILS_CONFIG_HASH[:12]
