"""Build SFT dataset for QLoRA fine-tuning from postmortem corpus.
Input:  data/processed/corpus.jsonl
Output: data/processed/sft_train.jsonl, sft_val.jsonl
"""
import json, random, re
from collections import Counter
from pathlib import Path

random.seed(42)

CORPUS = Path("data/processed/corpus.jsonl")
OUT_DIR = Path("data/processed")
MIN_WORDS, MAX_WORDS = 400, 3000     # quality floor + drop 42k-word outliers
OUTPUT_WORD_CAP = 1200               # fits in 2048 max_seq_length with prompt
SUMMARY_WORDS = 80                   # "brief summary" shown as input
VAL_FRAC = 0.10
NOISE_RE = re.compile(
    r"COLLECTED BY|Archive Team|web\.archive\.org|Wayback Machine|"
    r"Status Dashboard|Service Health|Search overlay|Jump to\b|"
    r"Contact sales|Try it free|System Metrics|Get email notifications|"
    r"Try Google Cloud",
    re.I,
)
STRONG_SIGNALS = [r"\bpostmortem\b", r"\bpost-?mortem\b", r"\broot cause\b", r"\bremediation\b"]
WEAK_SIGNALS = [
    r"\bincident\b", r"\boutage\b", r"\bimpacted?\b", r"\btimeline\b",
    r"\bdowntime\b", r"\baffected\b", r"\bresolved\b", r"\brollback\b",
    r"\bmitigat", r"\bfailure\b", r"\bdegraded\b", r"\brestored?\b",
]

def passes_quality(body: str) -> bool:
    if NOISE_RE.search(body):
        return False
    strong_hit = any(re.search(p, body, re.I) for p in STRONG_SIGNALS)
    weak_hits = sum(1 for p in WEAK_SIGNALS if re.search(p, body, re.I))
    return strong_hit or weak_hits >= 3

INSTRUCTION_TEMPLATES = [
    "You are a site reliability engineer. Given the following incident title and brief summary, write a detailed postmortem that covers what happened, the root cause, impact on users and services, and remediation actions taken.",
    "Act as an SRE writing an internal incident postmortem. Given the incident title and a short summary, produce a thorough postmortem including timeline of events, root cause analysis, customer impact, and follow-up actions.",
    "Write a public-facing incident postmortem blog post based on the title and summary below. Include what happened, when it happened, who was affected, the technical root cause, how the issue was mitigated, and what steps are being taken to prevent recurrence.",
    "Given the following incident title and initial summary, draft an engineering postmortem. Structure it with sections for incident overview, impact, root cause, timeline, resolution, and lessons learned.",
]

def clean_body(text: str) -> str:
    # strip "This post is also available in [langs]" line
    text = re.sub(r"This post is also available in[^.\n]*[.\n]", "", text, flags=re.I)
    # strip leading "N min read" / date-only lines
    text = re.sub(r"^\s*\d+\s*min read\s*$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def truncate_at_sentence(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    for end in [". ", "! ", "? ", ".\n"]:
        idx = truncated.rfind(end)
        if idx > len(truncated) * 0.7:
            return truncated[: idx + 1]
    return truncated + "..."

def extract_summary(body: str, n_words: int) -> str:
    words = body.split()
    summary = " ".join(words[:n_words])
    for end in [". ", "! ", "? "]:
        idx = summary.rfind(end)
        if idx > len(summary) * 0.5:
            return summary[: idx + 1]
    return summary

def main():
    rows = [json.loads(l) for l in open(CORPUS)]
    print(f"Loaded {len(rows)} rows")
    length_ok = [r for r in rows if MIN_WORDS <= len(r["body"].split()) <= MAX_WORDS]
    print(f"After length filter [{MIN_WORDS}, {MAX_WORDS}]: {len(length_ok)} rows")
    filtered = [r for r in length_ok if passes_quality(r["body"])]
    print(f"After quality filter (strong+weak signals, no noise): {len(filtered)} rows")
    print(f"  by source: {dict(Counter(r['source'] for r in filtered))}")

    pairs = []
    for r in filtered:
        title = r["title"].strip()
        body = clean_body(r["body"])
        summary = extract_summary(body, SUMMARY_WORDS)
        output = truncate_at_sentence(body, OUTPUT_WORD_CAP)
        input_text = f"Title: {title}\n\nSummary: {summary}"
        for tmpl in INSTRUCTION_TEMPLATES:
            pairs.append({
                "instruction": tmpl,
                "input": input_text,
                "output": output,
                "source": r["source"],
                "source_id": r["id"],
            })
    print(f"Built {len(pairs)} pairs ({len(INSTRUCTION_TEMPLATES)} templates/row)")

    # split by source_id so template dupes can't leak across train/val
    ids = sorted({p["source_id"] for p in pairs})
    random.shuffle(ids)
    n_val = max(1, int(len(ids) * VAL_FRAC))
    val_ids = set(ids[:n_val])
    train = [p for p in pairs if p["source_id"] not in val_ids]
    val   = [p for p in pairs if p["source_id"]     in val_ids]
    random.shuffle(train); random.shuffle(val)
    print(f"Train: {len(train)} pairs | Val: {len(val)} pairs ({len(val_ids)} unique val incidents)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "sft_train.jsonl", "w") as f:
        for p in train: f.write(json.dumps(p) + "\n")
    with open(OUT_DIR / "sft_val.jsonl", "w") as f:
        for p in val: f.write(json.dumps(p) + "\n")
    print(f"Wrote {OUT_DIR/'sft_train.jsonl'} and {OUT_DIR/'sft_val.jsonl'}")

    print("\n--- Sample train pair (truncated) ---")
    s = train[0]
    print(f"instruction: {s['instruction'][:100]}...")
    print(f"input: {s['input'][:200]}...")
    print(f"output: {s['output'][:300]}...")
    print(f"output word count: {len(s['output'].split())}")
    print(f"source: {s['source']} | id: {s['source_id']}")

if __name__ == "__main__":
    main()