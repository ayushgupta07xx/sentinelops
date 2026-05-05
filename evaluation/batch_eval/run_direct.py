"""
Run batch_input.jsonl through Groq's regular /v1/chat/completions API, synchronously.

Same model, same prompts as Batch API path — just sync transport. Used because
Batch API is paid-tier-only on Groq.

Resume-safe: writes one line to batch_output.jsonl after each successful row.
On 429 (TPD exhausted), exits cleanly. Re-run picks up where it stopped.

Output format matches Groq Batch API output schema, so poll_and_parse.py
parses it identically.

Run:
    python evaluation/batch_eval/run_direct.py
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import APIError, Groq, RateLimitError

REPO = Path(__file__).resolve().parents[2]
INPUT_PATH = REPO / "evaluation" / "batch_eval" / "batch_input.jsonl"
OUTPUT_PATH = REPO / "evaluation" / "batch_eval" / "batch_output.jsonl"

# Free tier 70B: 30 RPM. 2.5s gap = 24 RPM. Comfortable margin.
SLEEP_BETWEEN_CALLS_S = 18  # ~3.5K tokens/row vs 12K TPM cap -> 18s minimum spacing
MAX_429_RETRIES = 2  # short bursty 429s — TPD exhaustion will exhaust these fast


def load_done_ids() -> set:
    """Successful rows already in output file. Failed rows get retried."""
    if not OUTPUT_PATH.exists():
        return set()
    done = set()
    with OUTPUT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                cid = rec.get("custom_id")
                ok = (
                    cid
                    and not rec.get("error")
                    and rec.get("response", {}).get("status_code") == 200
                )
                if ok:
                    done.add(cid)
            except json.JSONDecodeError:
                pass
    return done


def append_output(record: dict):
    with OUTPUT_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def call_with_retry(client, body):
    """Single completion call with exponential backoff on 429."""
    delay = 5
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            return client.chat.completions.create(**body)
        except RateLimitError:
            if attempt == MAX_429_RETRIES:
                raise
            print(f"\n    429, retrying in {delay}s (attempt {attempt + 1}/{MAX_429_RETRIES})", end="", flush=True)
            time.sleep(delay)
            delay *= 2


def to_batch_format(resp, custom_id: str) -> dict:
    """Convert SDK response to Groq Batch API output schema."""
    choice = resp.choices[0]
    return {
        "id": resp.id,
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "request_id": resp.id,
            "body": {
                "id": resp.id,
                "model": resp.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": choice.message.content,
                        },
                        "finish_reason": choice.finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "total_tokens": resp.usage.total_tokens,
                },
            },
        },
        "error": None,
    }


def main():
    load_dotenv(REPO / ".env")
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY not set")
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing {INPUT_PATH}. Run build_batch.py first.")

    inputs = []
    with INPUT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                inputs.append(json.loads(line))

    done = load_done_ids()
    todo = [r for r in inputs if r["custom_id"] not in done]
    print(f"Total rows:   {len(inputs)}")
    print(f"Already done: {len(done)}")
    print(f"To process:   {len(todo)}")
    if not todo:
        print("\nAll rows already scored. Run poll_and_parse.py to compute scores.")
        return

    client = Groq()
    n_ok = 0
    tokens_used = 0

    for i, req in enumerate(todo, 1):
        cid = req["custom_id"]
        print(f"[{i}/{len(todo)}] {cid} ... ", end="", flush=True)
        try:
            resp = call_with_retry(client, req["body"])
        except RateLimitError:
            print(f"\n\n429 — TPD likely exhausted. Stopping cleanly.")
            print(f"Progress this session: {n_ok} new rows, {tokens_used} tokens used")
            print(f"Total scored: {len(done) + n_ok}/{len(inputs)}")
            print(f"\nRe-run when TPD has decayed (a few hours):")
            print(f"  python evaluation/batch_eval/run_direct.py")
            sys.exit(2)
        except APIError as e:
            print(f"API error ({e.__class__.__name__}): {e}")
            continue  # don't write a record; let it retry next run
        except Exception as e:
            print(f"unexpected: {e}")
            continue

        append_output(to_batch_format(resp, cid))
        n_ok += 1
        tokens_used += resp.usage.total_tokens
        print(f"ok ({resp.usage.total_tokens} tokens, {tokens_used} cum)")
        time.sleep(SLEEP_BETWEEN_CALLS_S)

    total_done = len(done) + n_ok
    print(f"\nSession done. {n_ok} new rows, {tokens_used} tokens.")
    print(f"Total scored: {total_done}/{len(inputs)}")

    if total_done == len(inputs):
        print(f"\nNext: python evaluation/batch_eval/poll_and_parse.py")
    else:
        print(f"\nIncomplete. Re-run: python evaluation/batch_eval/run_direct.py")


if __name__ == "__main__":
    main()
