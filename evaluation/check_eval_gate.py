"""
evaluation/check_eval_gate.py

CI gate: compares the latest ragas report in evaluation/reports/ against
the committed baseline in evaluation/baselines/main_8b.json. Exits 1 if
faithfulness drops by more than FAITHFULNESS_DROP_THRESHOLD points (0.05 = 5pts).

Used by .github/workflows/ci.yml to block PRs that regress LLM faithfulness.

Usage:
    python evaluation/check_eval_gate.py
    python evaluation/check_eval_gate.py --baseline evaluation/baselines/main_8b.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "evaluation" / "baselines" / "main_8b.json"
REPORTS_DIR = REPO_ROOT / "evaluation" / "reports"
FAITHFULNESS_DROP_THRESHOLD = 0.05  # 5 points


def latest_report() -> Path:
    reports = sorted(REPORTS_DIR.glob("ragas_*.json"))
    if not reports:
        sys.exit("FAIL: no ragas_*.json reports found in evaluation/reports/")
    return reports[-1]


def load_scores(path: Path) -> dict:
    data = json.loads(path.read_text())
    scores = data.get("scores", {})
    # Sanitize NaN -> None so downstream comparison fails loudly
    return {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
            for k, v in scores.items()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--threshold", type=float, default=FAITHFULNESS_DROP_THRESHOLD)
    args = p.parse_args()

    if not args.baseline.exists():
        sys.exit(f"FAIL: baseline not found at {args.baseline}. "
                 f"Generate one with: JUDGE_MODEL=llama-3.1-8b-instant "
                 f"python evaluation/ragas_suite.py && cp evaluation/reports/ragas_*.json {args.baseline}")

    report_path = latest_report()
    print(f"[gate] baseline:  {args.baseline}")
    print(f"[gate] candidate: {report_path}")

    base = load_scores(args.baseline)
    cand = load_scores(report_path)

    base_f = base.get("faithfulness")
    cand_f = cand.get("faithfulness")

    if base_f is None:
        sys.exit(f"FAIL: baseline faithfulness is null/NaN — invalid baseline.")
    if cand_f is None:
        sys.exit(f"FAIL: candidate faithfulness is null/NaN — judge calls failed. "
                 f"Re-run with raise_exceptions=True to debug.")

    drop = base_f - cand_f
    print(f"[gate] baseline.faithfulness  = {base_f:.3f}")
    print(f"[gate] candidate.faithfulness = {cand_f:.3f}")
    print(f"[gate] drop                   = {drop:+.3f} (threshold {args.threshold:.2f})")

    # Also report other metrics for visibility (no gating on these yet)
    for metric in ("answer_relevancy", "context_precision", "context_recall"):
        b, c = base.get(metric), cand.get(metric)
        if b is not None and c is not None:
            print(f"[gate]   {metric:20s} {b:.3f} -> {c:.3f} ({c-b:+.3f})")

    if drop > args.threshold:
        sys.exit(f"\nFAIL: faithfulness dropped {drop:.3f} > {args.threshold:.2f} — "
                 f"this PR regresses LLM quality.")
    print(f"\nPASS: faithfulness within {args.threshold:.2f} of baseline.")


if __name__ == "__main__":
    main()
