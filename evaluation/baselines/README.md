# Eval baselines

`main_8b.json` is the reference faithfulness score from current `main` graded by
**llama-3.1-8b-instant** (Path-C fast inner-loop). The CI eval gate compares
candidate PRs against this. Update on merge to `main` whenever:

- the fine-tuned model changes (re-train, re-quantize, new HF revision)
- prompts in `serving/agent/tools.py` change
- retrieval changes (Qdrant collection, embedder, runbooks)
- `evaluation/golden_set/` changes

## How to regenerate

```bash
# 1. Refresh agent outputs (calls Modal vLLM, ~5-15 min for 20 cases)
python evaluation/run_eval.py

# 2. Grade with 8B (Path-C inner-loop, ~3 min)
JUDGE_MODEL=llama-3.1-8b-instant python evaluation/ragas_suite.py

# 3. Promote to baseline
cp $(ls -t evaluation/reports/ragas_*.json | head -1) \
   evaluation/baselines/main_8b.json

# 4. Commit
git add evaluation/baselines/main_8b.json evaluation/golden_set/eval_inputs.jsonl
git commit -m "eval: refresh main_8b baseline"
```

## Why 8B not 70B for the gate?

70B llama-3.3-70b-versatile is the canonical grader (used for the model card +
release notes). It has a 100K TPD rolling-24h cap that a single full eval run
(~96K tokens) almost saturates — unfit for CI which may run several times a day.

8B llama-3.1-8b-instant has a 500K TPD cap, costs less, and gives a stable
relative signal for catching regressions. Validated against 70B on ~20 cases
(Chat 6/7 spot-check) — they correlate strongly within the threshold band,
which is what the gate actually needs.

The 70B canonical re-grade runs **only** before model card publish (or whenever
prompts/model change significantly). It is not part of CI.
