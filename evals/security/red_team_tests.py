# Owner: Jana
"""Replay a probe-set JSON against a running guardrails sidecar.

Each probe in the input JSON is a dict with `message`, `expected_decision`,
and `expected_rule_name`. The script POSTs to /check/input, compares the
actual `(decision, rule_name)` against the expected, and exits non-zero if
any probe diverges.

Usage:
    python evals/security/red_team_tests.py \\
        --url http://localhost:8002 \\
        --token "$GUARDRAILS_SERVICE_CREDENTIAL" \\
        --probe-set evals/security/injection_cases.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def run(url: str, token: str, probe_set: Path) -> int:
    probes = json.loads(probe_set.read_text(encoding="utf-8"))
    failures: list[dict] = []
    with httpx.Client(base_url=url, timeout=10.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        for probe in probes:
            resp = client.post(
                "/check/input",
                json={
                    "tenant_id": "tenant-redteam",
                    "message": probe["message"],
                    "tenant_config": {},
                },
                headers=headers,
            )
            body = resp.json()
            actual_decision = body.get("decision")
            actual_rule = body.get("rule_name")
            expected_decision = probe["expected_decision"]
            expected_rule = probe["expected_rule_name"]
            if actual_decision != expected_decision or actual_rule != expected_rule:
                failures.append(
                    {
                        "message": probe["message"],
                        "expected": [expected_decision, expected_rule],
                        "actual": [actual_decision, actual_rule],
                    }
                )

    if failures:
        print(json.dumps({"failures": failures}, indent=2))
        return 1
    print(json.dumps({"probes": len(probes), "result": "pass"}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    parser.add_argument("--token", default="test-token")
    parser.add_argument("--probe-set", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.url, args.token, args.probe_set)


if __name__ == "__main__":
    sys.exit(main())
