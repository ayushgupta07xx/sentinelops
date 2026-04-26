"""
evaluation/ragas_suite.py

Runs Ragas (faithfulness, answer_relevancy, context_precision, context_recall)
over evaluation/golden_set/eval_inputs.jsonl using Groq llama-3.3-70b-versatile
as judge. Embeddings = local bge-small-en-v1.5.

Output: evaluation/reports/ragas_<timestamp>.json + console summary.

Usage:
    python evaluation/ragas_suite.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from datasets import Dataset  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402
from langchain_huggingface import HuggingFaceEmbeddings  # noqa: E402
from ragas import evaluate  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

INPUTS_PATH = REPO_ROOT / "evaluation" / "golden_set" / "eval_inputs.jsonl"
REPORTS_DIR = REPO_ROOT / "evaluation" / "reports"

JUDGE_MODEL = "llama-3.1-8b-instant"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


class GroqNClamp(ChatGroq):
    """ChatGroq subclass that forces n=1 on every request, no matter what
    Ragas metric (e.g. answer_relevancy asks for n=3) passes in.

    Groq's API rejects n>1; the wrapper-level kwarg only covers the default,
    not metric-specific overrides at call time.
    """

    def _generate(self, *args: Any, **kwargs: Any):
        kwargs.pop("n", None)
        return super()._generate(*args, n=1, **kwargs)

    async def _agenerate(self, *args: Any, **kwargs: Any):
        kwargs.pop("n", None)
        return await super()._agenerate(*args, n=1, **kwargs)


def load_dataset() -> Dataset:
    rows = []
    for line in INPUTS_PATH.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "error" in r:
            print(f"  skipping {r['id']} (errored during run_eval)")
            continue
        rows.append(
            {
                "question": r["question"],
                "answer": r["answer"],
                "contexts": r["contexts"] or ["(none)"],
                "ground_truth": r["ground_truth"],
            }
        )
    print(f"loaded {len(rows)} eval rows")
    return Dataset.from_list(rows)


def main() -> None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing from .env")

    ds = load_dataset()

    judge = LangchainLLMWrapper(
        GroqNClamp(
            model=JUDGE_MODEL,
            temperature=0.0,
            api_key=api_key,
            max_retries=5,
            request_timeout=120,
        )
    )

    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    )

    run_config = RunConfig(
        timeout=180,
        max_retries=5,
        max_wait=60,
        max_workers=4,  # 30 RPM cap on Groq 70B
    )

    print(f"grading with {JUDGE_MODEL} (Groq) — 4 metrics x {len(ds)} cases = {4 * len(ds)} judge calls")
    t0 = time.time()
    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=judge,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=False,
    )
    elapsed = time.time() - t0

    try:
        scores = {k: float(v) for k, v in result._repr_dict.items()}
    except AttributeError:
        scores = {k: float(v) for k, v in dict(result).items()}

    print(f"\n=== RESULTS ({elapsed:.1f}s) ===")
    for metric, score in scores.items():
        flag = " ✅" if metric == "faithfulness" and score >= 0.75 else ""
        print(f"  {metric:25s} {score:.3f}{flag}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": ts,
        "judge_model": JUDGE_MODEL,
        "n_cases": len(ds),
        "elapsed_sec": round(elapsed, 1),
        "scores": scores,
    }
    out = REPORTS_DIR / f"ragas_{ts}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")

    try:
        df = result.to_pandas()
        per_case = REPORTS_DIR / f"ragas_{ts}_per_case.csv"
        df.to_csv(per_case, index=False)
        print(f"wrote {per_case}")
    except Exception as e:
        print(f"(could not write per-case csv: {e})")


if __name__ == "__main__":
    main()
