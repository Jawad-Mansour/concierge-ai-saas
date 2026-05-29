# Owner: Jana
"""Latency probe — fires N requests at /predict at the given concurrency, prints
p50/p95/p99. Records the methodology that DECISIONS.md cites.

Usage:
    python evals/classifier/latency_probe.py --requests 1000 --concurrency 16
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

REPRESENTATIVE_MESSAGES = [
    "What are your business hours?",
    "BUY CHEAP MEDS NOW!!!",
    "Can you call me at +1-555-0123?",
    "Can you compare your enterprise and team plans on SLA + EU residency?",
    "hey",
]


async def _hit(client: httpx.AsyncClient, url: str, headers: dict[str, str], i: int) -> float:
    payload = {
        "tenant_id": "tenant-acme",
        "message": REPRESENTATIVE_MESSAGES[i % len(REPRESENTATIVE_MESSAGES)],
    }
    started = time.perf_counter()
    await client.post(url, json=payload, headers=headers)
    return (time.perf_counter() - started) * 1000.0


async def _run(url: str, token: str, concurrency: int, requests: int) -> list[float]:
    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def worker(i: int) -> None:
            async with sem:
                latencies.append(await _hit(client, url, headers, i))

        await asyncio.gather(*(worker(i) for i in range(requests)))
    return latencies


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return s[k]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8001/predict")
    parser.add_argument("--token", default="test-token")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args(argv)

    latencies = asyncio.run(_run(args.url, args.token, args.concurrency, args.requests))

    print(
        {
            "n": len(latencies),
            "concurrency": args.concurrency,
            "p50_ms": _percentile(latencies, 50),
            "p95_ms": _percentile(latencies, 95),
            "p99_ms": _percentile(latencies, 99),
            "mean_ms": statistics.mean(latencies) if latencies else 0.0,
            "max_ms": max(latencies) if latencies else 0.0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
