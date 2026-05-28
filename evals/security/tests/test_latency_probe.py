# Owner: Jana
"""T044 — pin the latency probe's percentile math.

Unit-tests the `_pct` helper directly so the assertion does not need a live
network round-trip; the probe's correctness is what we're pinning here, not
absolute latency numbers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "latency_probe.py"
_spec = importlib.util.spec_from_file_location("latency_probe", _PATH)
assert _spec and _spec.loader
latency_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(latency_probe)  # type: ignore[union-attr]


def test_percentiles_monotone():
    values = [float(i) for i in range(1, 101)]  # 1..100
    p50 = latency_probe._pct(values, 50)
    p95 = latency_probe._pct(values, 95)
    p99 = latency_probe._pct(values, 99)
    assert p50 <= p95 <= p99
    assert p50 == 51.0  # round(0.5 * 99) = 50 → index 50 → value 51
    assert p95 == 96.0
    assert p99 == 100.0


def test_pct_on_empty_returns_zero():
    assert latency_probe._pct([], 95) == 0.0
