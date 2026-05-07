"""
evaluation/ragas_suite.py

Runs Ragas (faithfulness, answer_relevancy, context_precision, context_recall)
over evaluation/golden_set/eval_inputs.jsonl using a Groq judge model.

Design notes:
- Judge model is env-driven (JUDGE_MODEL); default = canonical 70B.
  Set JUDGE_MODEL=llama-3.1-8b-instant for the Path-C CI inner-loop.
- Embeddings = local bge-small-en-v1.5 (no remote calls, free).
- Groq 8B-instant has a 6K TPM hard cap — we keep max_workers=1 + max_tokens=4096
  + truncated inputs (run truncate_eval_inputs.sh first if needed).
- Chunked checkpointing: cases processed 5 at a time. Each chunk's aggregate
  scores are persisted to evaluation/.checkpoint/chunk_NN.json as it completes,
  so a mid-run crash only costs ~12 min, not the full ~60. On re-run, cached
  chunks are skipped. Delete evaluation/.checkpoint/ to force a clean re-run.

Output: evaluation/reports/ragas_<timestamp>.json + per-chunk CSVs + console summary.

Usage:
    JUDGE_MODEL=llama-3.1-8b-instant python evaluation/ragas_suite.py
    rm -rf evaluation/.checkpoint && python evaluation/ragas_suite.py   # clean re-run
"""

from __future__ import annotations

import json
import os
import shutil
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
CHECKPOINT_DIR = REPO_ROOT / "evaluation" / ".checkpoint"

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_SIZE = 5  # tune for crash blast radius vs setup overhead
METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


class GroqNClamp(ChatGroq):
    """ChatGroq subclass that forces n=1 on every request — Groq rejects n>1."""

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


def build_judge() -> LangchainLLMWrapper:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing from .env")
    return LangchainLLMWrapper(
        GroqNClamp(
            model=JUDGE_MODEL,
            temperature=0.0,
            api_key=api_key,
            max_retries=5,
            request_timeout=240,
            max_tokens=4096,
        )
    )


def build_run_config() -> RunConfig:
    return RunConfig(
        timeout=600,    # absorb Groq Retry-After waits
        max_retries=5,
        max_wait=60,
        max_workers=1,  # Groq 8B-instant 6K TPM ceiling; serial is the safe path
    )


def run_chunk(ds_chunk: Dataset, judge, embeddings, run_config) -> tuple[dict, "pd.DataFrame"]:
    """Grade one chunk. Returns (mean_scores_dict, per_case_df)."""
    result = evaluate(
        ds_chunk,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=judge,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=True,  # surface real errors instead of silent NaN
    )
    try:
        scores = {k: float(v) for k, v in result._repr_dict.items()}
    except AttributeError:
        scores = {k: float(v) for k, v in dict(result).items()}
    df = result.to_pandas()
    return scores, df


def aggregate(per_chunk: list[dict]) -> dict:
    """Weighted-mean aggregate across chunks. Equal chunk sizes => simple mean."""
    if not per_chunk:
        return {}
    total_n = sum(c["n"] for c in per_chunk)
    out = {}
    for metric in METRIC_NAMES:
        weighted = sum(c["scores"].get(metric, 0.0) * c["n"] for c in per_chunk)
        out[metric] = weighted / total_n if total_n else float("nan")
    return out


def main() -> None:
    ds = load_dataset()
    judge = build_judge()
    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=EMBED_MODEL))
    run_config = build_run_config()

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    n = len(ds)
    n_chunks = (n + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(
        f"grading with {JUDGE_MODEL} (Groq) — {len(METRIC_NAMES)} metrics x {n} cases "
        f"= {len(METRIC_NAMES) * n} judge calls, in {n_chunks} chunks of <={CHUNK_SIZE}"
    )
    print(f"checkpoints: {CHECKPOINT_DIR} (delete to force clean re-run)")

    per_chunk_records = []
    per_chunk_dfs = []
    t0 = time.time()

    for chunk_idx in range(n_chunks):
        cache_file = CHECKPOINT_DIR / f"chunk_{chunk_idx:02d}.json"
        cache_csv = CHECKPOINT_DIR / f"chunk_{chunk_idx:02d}.csv"
        start, end = chunk_idx * CHUNK_SIZE, min((chunk_idx + 1) * CHUNK_SIZE, n)

        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            print(f"  chunk {chunk_idx + 1}/{n_chunks} ({start}:{end}): cached "
                  f"(faithfulness={cached['scores'].get('faithfulness', 0):.3f})")
            per_chunk_records.append(cached)
            if cache_csv.exists():
                import pandas as pd
                per_chunk_dfs.append(pd.read_csv(cache_csv))
            continue

        print(f"  chunk {chunk_idx + 1}/{n_chunks} ({start}:{end}): grading...", flush=True)
        ds_chunk = ds.select(range(start, end))
        chunk_t0 = time.time()
        scores, df = run_chunk(ds_chunk, judge, embeddings, run_config)
        chunk_elapsed = time.time() - chunk_t0

        record = {
            "chunk_idx": chunk_idx,
            "start": start,
            "end": end,
            "n": end - start,
            "elapsed_sec": round(chunk_elapsed, 1),
            "scores": scores,
        }
        cache_file.write_text(json.dumps(record, indent=2))
        df.to_csv(cache_csv, index=False)
        per_chunk_records.append(record)
        per_chunk_dfs.append(df)

        print(f"    done in {chunk_elapsed:.1f}s — "
              f"faithfulness={scores.get('faithfulness', 0):.3f}, "
              f"answer_relevancy={scores.get('answer_relevancy', 0):.3f}")

    elapsed = time.time() - t0
    aggregate_scores = aggregate(per_chunk_records)

    print(f"\n=== RESULTS ({elapsed:.1f}s, {n} cases across {n_chunks} chunks) ===")
    for metric in METRIC_NAMES:
        score = aggregate_scores.get(metric, float("nan"))
        flag = " ✅" if metric == "faithfulness" and score >= 0.75 else ""
        print(f"  {metric:25s} {score:.3f}{flag}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": ts,
        "judge_model": JUDGE_MODEL,
        "n_cases": n,
        "n_chunks": n_chunks,
        "chunk_size": CHUNK_SIZE,
        "elapsed_sec": round(elapsed, 1),
        "scores": aggregate_scores,
        "per_chunk": per_chunk_records,
    }
    out = REPORTS_DIR / f"ragas_{ts}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")

    # Concat per-case CSVs across chunks
    try:
        import pandas as pd
        all_df = pd.concat(per_chunk_dfs, ignore_index=True) if per_chunk_dfs else None
        if all_df is not None:
            per_case = REPORTS_DIR / f"ragas_{ts}_per_case.csv"
            all_df.to_csv(per_case, index=False)
            print(f"wrote {per_case}")
    except Exception as e:
        print(f"(could not write per-case csv: {e})")

    # Clean up checkpoint dir on full success — fresh run next time
    print(f"\nrun complete; clearing {CHECKPOINT_DIR}")
    shutil.rmtree(CHECKPOINT_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
