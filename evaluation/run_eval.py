"""
evaluation/run_eval.py

Runs the SentinelOps agent over the golden set, captures eval tuples for Ragas.

Output: evaluation/golden_set/eval_inputs.jsonl
  one row per case: {id, question, answer, contexts, ground_truth}

Usage (from repo root, venv active, .env with MODAL_VLLM_* loaded):
    python evaluation/run_eval.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# Imports below this line need the env vars
from serving.agent.tools import (  # noqa: E402
    draft_postmortem,
    get_recent_alerts,
    query_prometheus,
    search_runbooks,
)

CASES_PATH = REPO_ROOT / "evaluation" / "golden_set" / "cases.jsonl"
OUT_PATH = REPO_ROOT / "evaluation" / "golden_set" / "eval_inputs.jsonl"


def alert_to_query(alert: dict) -> str:
    """Build the search query the agent uses to retrieve runbooks."""
    return f"{alert.get('alertname', '')} {alert.get('service', '')} {alert.get('summary', '')}"


def run_one(case: dict) -> dict:
    alert = case["alert"]
    query = alert_to_query(alert)

    # Tool 1: retrieve runbooks (top-5 after rerank)
    rb = search_runbooks(query, k=5)

    # Tools 2 + 3: mocked (Day 4)
    prom = query_prometheus(f"rate(http_requests_total{{service='{alert['service']}'}}[5m])")
    recents = get_recent_alerts(alert["service"])

    # Tool 4: real Modal vLLM call
    t0 = time.time()
    answer = draft_postmortem(alert, rb, prom, recents)
    elapsed = time.time() - t0

    contexts = [
        (c.get("text") or c.get("title") or "")[:1500]
        for c in rb
        if c.get("text") or c.get("title")
    ]

    return {
        "id": case["id"],
        "question": query,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": case["ground_truth"],
        "elapsed_sec": round(elapsed, 1),
    }


def main() -> None:
    cases = [json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip()]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"running agent on {len(cases)} cases...")
    with OUT_PATH.open("w") as f:
        for i, case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {case['id']} ({case['alert']['alertname']})...", flush=True)
            try:
                row = run_one(case)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"      ok ({row['elapsed_sec']}s, {len(row['contexts'])} ctx, {len(row['answer'])} chars)")
            except Exception as e:
                print(f"      FAILED: {type(e).__name__}: {e}")
                f.write(json.dumps({"id": case["id"], "error": str(e)}) + "\n")
                f.flush()

    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
