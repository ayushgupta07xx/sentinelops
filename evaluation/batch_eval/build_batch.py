"""
Build Groq Batch API input JSONL from eval_inputs.jsonl.

Each row -> one batch request that asks llama-3.3-70b-versatile to:
  1. Decompose the answer into atomic claims
  2. Verify each claim against the contexts
  3. Return strict JSON

Faithfulness score = supported_claims / total_claims (computed in poll_and_parse.py).

Run:
    python evaluation/batch_eval/build_batch.py

Inputs:
    evaluation/golden_set/eval_inputs.jsonl
Outputs:
    evaluation/batch_eval/batch_input.jsonl
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INPUT_PATH = REPO / "evaluation" / "golden_set" / "eval_inputs.jsonl"
OUTPUT_PATH = REPO / "evaluation" / "batch_eval" / "batch_input.jsonl"

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are an expert RAG faithfulness grader.

Your job: given a question, an answer, and the contexts that the answer was supposedly based on, decide which claims in the answer are actually supported by the contexts.

Procedure:
1. Decompose the answer into atomic factual claims. A claim is a single, verifiable assertion of fact (e.g. "The outage lasted 47 minutes", "The root cause was a misconfigured load balancer"). Skip generic filler ("the team investigated", "we apologize"), opinions, hedges, and section headers.
2. For each claim, judge whether it is directly supported by the provided contexts. A claim is "supported" only if a reasonable reader could verify it from the contexts alone, without external knowledge or guessing.
3. If the answer makes no extractable factual claims, return an empty claims array.

Output STRICT JSON in this exact schema and nothing else:
{
  "claims": [
    {"claim": "<short paraphrase>", "supported": true, "reason": "<one short sentence>"},
    {"claim": "<short paraphrase>", "supported": false, "reason": "<one short sentence>"}
  ]
}

Do not wrap the JSON in markdown fences. Do not add commentary before or after."""

USER_TEMPLATE = """Question:
{question}

Answer:
{answer}

Contexts:
{contexts}

Grade the answer's faithfulness against the contexts above. Return JSON only."""


def get_field(row: dict, *names: str, default=None):
    """Try multiple field names (ragas v0.1 vs v0.2 schemas)."""
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return default


def format_contexts(contexts) -> str:
    """ragas accepts list[str]; some pipelines use list[dict] or single str."""
    if isinstance(contexts, str):
        return contexts
    if isinstance(contexts, list):
        out = []
        for i, c in enumerate(contexts, 1):
            if isinstance(c, dict):
                c = c.get("page_content") or c.get("text") or json.dumps(c)
            out.append(f"[Context {i}]\n{c}")
        return "\n\n".join(out)
    return str(contexts)


def build():
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing input: {INPUT_PATH}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with INPUT_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    print(f"Loaded {len(rows)} rows from {INPUT_PATH}")
    if not rows:
        raise SystemExit("eval_inputs.jsonl is empty")

    # Sanity peek at fields on row 0
    print(f"Row 0 keys: {sorted(rows[0].keys())}")

    written = 0
    with OUTPUT_PATH.open("w") as out:
        for i, row in enumerate(rows):
            q = get_field(row, "question", "user_input", "query")
            a = get_field(row, "answer", "response", "generated")
            ctx = get_field(row, "contexts", "retrieved_contexts", "context", default=[])

            if not q or not a:
                print(f"  row {i}: missing question/answer, skipping")
                continue

            user_msg = USER_TEMPLATE.format(
                question=q,
                answer=a,
                contexts=format_contexts(ctx) or "(no contexts provided)",
            )

            request = {
                "custom_id": f"faithfulness-row-{i:03d}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": MODEL,
                    "temperature": 0.0,
                    "max_tokens": 1500,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                },
            }
            out.write(json.dumps(request) + "\n")
            written += 1

    print(f"Wrote {written} batch requests to {OUTPUT_PATH}")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"File size: {size_kb:.1f} KB (Groq limit is 200 MB)")


if __name__ == "__main__":
    build()
