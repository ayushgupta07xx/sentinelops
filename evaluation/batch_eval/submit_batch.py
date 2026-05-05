"""
Submit batch_input.jsonl to Groq Batch API.

Saves batch_id + input_file_id to .batch_state.json so poll_and_parse.py can pick up.

Run:
    python evaluation/batch_eval/submit_batch.py

Requires GROQ_API_KEY env var (already set in ~/sentinelops/.env).
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

REPO = Path(__file__).resolve().parents[2]
INPUT_PATH = REPO / "evaluation" / "batch_eval" / "batch_input.jsonl"
STATE_PATH = REPO / "evaluation" / "batch_eval" / ".batch_state.json"

COMPLETION_WINDOW = "24h"  # Groq supports 24h..7d. 24h = fastest turnaround.


def submit():
    load_dotenv(REPO / ".env")
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY not set. Check .env")

    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing {INPUT_PATH}. Run build_batch.py first.")

    n_lines = sum(1 for _ in INPUT_PATH.open())
    print(f"Submitting {n_lines} requests from {INPUT_PATH}")

    client = Groq()

    # Step 1: upload JSONL with purpose=batch
    print("Uploading file...")
    with INPUT_PATH.open("rb") as f:
        file_obj = client.files.create(file=f, purpose="batch")
    print(f"  file_id = {file_obj.id}")

    # Step 2: create batch job
    print("Creating batch job...")
    batch = client.batches.create(
        input_file_id=file_obj.id,
        endpoint="/v1/chat/completions",
        completion_window=COMPLETION_WINDOW,
    )
    print(f"  batch_id   = {batch.id}")
    print(f"  status     = {batch.status}")
    print(f"  window     = {COMPLETION_WINDOW}")
    print(f"  expires_at = {batch.expires_at}")

    # Step 3: persist state for poll_and_parse.py
    state = {
        "batch_id": batch.id,
        "input_file_id": file_obj.id,
        "n_requests": n_lines,
        "status_at_submit": batch.status,
        "completion_window": COMPLETION_WINDOW,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2))
    print(f"\nState saved to {STATE_PATH}")
    print(f"\nNext step: python evaluation/batch_eval/poll_and_parse.py")


if __name__ == "__main__":
    submit()
