# Owner: Jana
"""Cold-start probe — measures the wall-clock from `docker compose up modelserver`
to readiness-probe green. Prints the number for the DECISIONS.md "Cold-start
budget" row (plan.md §IV).

Usage:
    python evals/classifier/coldstart_probe.py
"""
from __future__ import annotations

import argparse
import subprocess
import time

import httpx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="modelserver")
    parser.add_argument("--health-url", default="http://localhost:8001/health")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    args = parser.parse_args(argv)

    subprocess.run(["docker", "compose", "rm", "-fsv", args.service], check=False)
    started = time.perf_counter()
    subprocess.run(["docker", "compose", "up", "-d", args.service], check=True)

    deadline = started + args.timeout_s
    while time.perf_counter() < deadline:
        try:
            r = httpx.get(args.health_url, timeout=1.0)
            if r.status_code == 200:
                elapsed = time.perf_counter() - started
                print({"service": args.service, "cold_start_s": round(elapsed, 3)})
                return 0
        except Exception:
            pass
        time.sleep(0.2)

    print({"service": args.service, "cold_start_s": "TIMEOUT", "budget_s": args.timeout_s})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
