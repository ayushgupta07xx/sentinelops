"""
Poll Groq batch until complete, download output, compute faithfulness.

Run:
    # default: poll every 60s until complete
    python evaluation/batch_eval/poll_and_parse.py

    # check once and exit
    python evaluation/batch_eval/poll_and_parse.py --once

Inputs:
    evaluation/batch_eval/.batch_state.json  (from submit_batch.py)
Outputs:
    evaluation/batch_eval/batch_output.jsonl  (raw Groq response file)
    evaluation/batch_eval/results.json        (parsed scores)
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

REPO = Path(__file__).resolve().parents[2]
STATE_PATH = REPO / "evaluation" / "batch_eval" / ".batch_state.json"
OUTPUT_JSONL = REPO / "evaluation" / "batch_eval" / "batch_output.jsonl"
RESULTS_PATH = REPO / "evaluation" / "batch_eval" / "results.json"

POLL_INTERVAL_S = 60
TERMINAL = {"completed", "failed", "expired", "cancelled"}


def load_state():
    if not STATE_PATH.exists():
        raise SystemExit(f"Missing {STATE_PATH}. Run submit_batch.py first.")
    return json.loads(STATE_PATH.read_text())


def fmt_counts(counts):
    if counts is None:
        return "(no counts yet)"
    # SDK returns a pydantic-ish object; both dict and attr access work
    if hasattr(counts, "model_dump"):
        counts = counts.model_dump()
    elif not isinstance(counts, dict):
        counts = {k: getattr(counts, k, None) for k in ("total", "completed", "failed")}
    return f"{counts.get('completed', '?')}/{counts.get('total', '?')} done, {counts.get('failed', '?')} failed"


def poll(client, batch_id, watch: bool):
    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        print(f"[{time.strftime('%H:%M:%S')}] status={status}  {fmt_counts(getattr(batch, 'request_counts', None))}")
        if status in TERMINAL or not watch:
            return batch
        time.sleep(POLL_INTERVAL_S)


def download_output(client, file_id: str) -> list:
    """Download output JSONL and return list of parsed lines."""
    print(f"Downloading output file {file_id}...")
    resp = client.files.content(file_id)
    text = resp.text if hasattr(resp, "text") else resp.read().decode("utf-8")
    OUTPUT_JSONL.write_text(text)
    print(f"  saved to {OUTPUT_JSONL}")
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    return lines


def parse_response_content(content: str) -> dict | None:
    """Parse model's JSON output. Returns dict with 'claims' or None on failure."""
    if not content:
        return None
    # JSON mode should give clean JSON, but be defensive
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Strip markdown fences if present
        cleaned = content.strip()
        for fence in ("```json", "```"):
            if cleaned.startswith(fence):
                cleaned = cleaned[len(fence):].lstrip()
            if cleaned.endswith("```"):
                cleaned = cleaned[: -3].rstrip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def compute_faithfulness(output_lines: list) -> dict:
    per_row = []  # (custom_id, supported, total, score)

    for line in output_lines:
        cid = line.get("custom_id", "?")
        err = line.get("error")
        if err:
            per_row.append({"custom_id": cid, "score": None, "error": str(err)})
            continue

        body = line.get("response", {}).get("body", {})
        content = (
            body.get("choices", [{}])[0].get("message", {}).get("content")
            if body.get("choices") else None
        )
        parsed = parse_response_content(content) if content else None

        if not parsed or "claims" not in parsed:
            per_row.append({
                "custom_id": cid,
                "score": None,
                "error": "could not parse claims",
                "raw_content": (content or "")[:200],
            })
            continue

        claims = parsed["claims"]
        total = len(claims)
        supported = sum(1 for c in claims if c.get("supported") is True)

        if total == 0:
            # No factual claims extracted -> ragas convention is NaN; we record None
            per_row.append({
                "custom_id": cid,
                "score": None,
                "supported": 0,
                "total": 0,
                "note": "no factual claims extracted",
            })
        else:
            per_row.append({
                "custom_id": cid,
                "score": supported / total,
                "supported": supported,
                "total": total,
                "claims": claims,
            })

    valid = [r for r in per_row if r.get("score") is not None]
    mean = sum(r["score"] for r in valid) / len(valid) if valid else 0.0
    n_no_claims = sum(1 for r in per_row if r.get("note") == "no factual claims extracted")
    n_errors = sum(1 for r in per_row if r.get("error"))

    summary = {
        "metric": "faithfulness",
        "model": "llama-3.3-70b-versatile",
        "via": "groq_batch_api",
        "n_rows": len(per_row),
        "n_scored": len(valid),
        "n_no_claims": n_no_claims,
        "n_errors": n_errors,
        "faithfulness_mean": round(mean, 4),
        "per_row": per_row,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="check status once and exit")
    args = ap.parse_args()

    load_dotenv(REPO / ".env")

    # Auto-detect: if .batch_state.json exists -> Batch API mode (poll + download).
    # Else if batch_output.jsonl exists -> direct mode (run_direct.py output).
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        batch_id = state["batch_id"]
        print(f"Polling batch {batch_id}")
        client = Groq()
        batch = poll(client, batch_id, watch=not args.once)
        if batch.status != "completed":
            print(f"\nBatch ended with status={batch.status}, not completed.")
            if getattr(batch, "errors", None):
                print(f"Errors: {batch.errors}")
            if getattr(batch, "error_file_id", None):
                print(f"Error file: {batch.error_file_id}")
                try:
                    err_text = client.files.content(batch.error_file_id).text
                    print("--- error file head ---")
                    print(err_text[:2000])
                except Exception as e:
                    print(f"  (could not download error file: {e})")
            sys.exit(1)
        output_file_id = batch.output_file_id
        if not output_file_id:
            raise SystemExit("Batch completed but no output_file_id?")
        lines = download_output(client, output_file_id)
    elif OUTPUT_JSONL.exists():
        print(f"Direct mode: parsing {OUTPUT_JSONL}")
        text = OUTPUT_JSONL.read_text()
        lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    else:
        raise SystemExit(
            f"Neither {STATE_PATH} nor {OUTPUT_JSONL} found.\n"
            "Run run_direct.py (free-tier) or submit_batch.py (Batch API) first."
        )
    print(f"  parsed {len(lines)} response lines")

    summary = compute_faithfulness(lines)
    RESULTS_PATH.write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 60)
    print(f"Faithfulness: {summary['faithfulness_mean']:.4f}")
    print(f"  scored:     {summary['n_scored']}/{summary['n_rows']}")
    print(f"  no claims:  {summary['n_no_claims']}")
    print(f"  errors:     {summary['n_errors']}")
    print("=" * 60)
    print(f"\nFull results: {RESULTS_PATH}")
    print(f"Day-4 DoD: faithfulness >= 0.75 -> {'PASS' if summary['faithfulness_mean'] >= 0.75 else 'FAIL'}")


if __name__ == "__main__":
    main()
