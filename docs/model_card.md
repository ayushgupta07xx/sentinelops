# Model Card — SentinelOps Mistral-7B (QLoRA)

| | |
| --- | --- |
| **Model name** | `sentinelops-mistral7b-merged` (full) / `sentinelops-mistral7b-awq` (served) / `sentinelops-mistral7b-qlora-adapter` (adapter only) |
| **Base model** | `mistralai/Mistral-7B-Instruct-v0.3` |
| **Fine-tuning method** | QLoRA — 4-bit NF4 quantization + LoRA adapters |
| **Task** | Drafting incident postmortems from sparse alert + retrieved-context inputs |
| **License** | Apache 2.0 (matches base model license) |
| **Faithfulness (canonical)** | **0.63** — 20-case golden set, `llama-3.3-70b-versatile` grader |
| **Faithfulness (CI baseline)** | **0.51** — 10-case fast set, `llama-3.1-8b-instant` grader |
| **Hardware** | Kaggle 2×T4 (single-T4 occupancy with QLoRA) |
| **Trained by** | Ayush Gupta, solo, 5-week project |
| **Repo** | https://github.com/ayushgupta07xx/sentinelops |

This card complements the [HuggingFace classifier card](https://huggingface.co/ayushgupta7777/sentinelops-classifier), which documents the non-generative DistilBERT baseline.

---

## 1. Intended use

**The model is intended as a drafting assistant for SREs writing incident postmortems.** Given a structured alert payload plus retrieved runbook chunks and historical incident summaries, it produces a postmortem skeleton with sections for root cause, impact, remediation, and learnings. The output is meant to be reviewed and edited by a human, not published unchanged.

The model is also a research / portfolio artefact demonstrating end-to-end QLoRA fine-tuning, retrieval-augmented agent integration, and production-shaped MLOps deployment on free compute.

### Out-of-scope use

The model **must not** be used for:

- Standalone, unattended generation of customer-facing postmortems or incident communications.
- Any automated decision with regulatory, safety, or financial consequences (compliance findings, root-cause attribution in legal contexts, blame assignment).
- Generation of factual claims about specific real-world incidents the model was not given evidence for — see Failure Modes below.
- Use against incidents involving named individuals, customer PII, or confidential infrastructure details. The training data was scrubbed for PII, but the scrub is not perfect (one known leak documented below) and untrusted PII at inference time has no guardrail.

---

## 2. Training data

### Sources

The corpus is built from four public sources, totalling **2,000+ postmortems** that yield ~2,500 instruction-format training pairs after preprocessing.

| Source | Approximate count | Notes |
| --- | --- | --- |
| [`danluu/post-mortems`](https://github.com/danluu/post-mortems) | ~1,200 | Curated index of public postmortems across vendors |
| Cloudflare blog (post-mortem tag) | ~120 | Cloudflare-authored incident reports |
| GitHub status (Atom feed) | ~600 | GitHub.com status incidents 2017→2024 |
| AWS post-event summaries | ~80 | AWS service event public summaries |

The corpus is biased toward **hyperscaler infrastructure incidents** because that is what is publicly available at scale. See Bias section below.

### Preprocessing

1. **HTML → text** with `trafilatura` for blog posts and Atom feeds.
2. **Deduplication** with MinHash (threshold 0.85, 5-word shingles, 128 permutations). MinHash chosen over exact-match because many postmortems are republished or excerpted across sites with minor edits.
3. **PII scrub** combining:
   - **Regex** for emails, IPv4/IPv6 addresses, opaque-looking tokens, credit card patterns.
   - **Microsoft Presidio** for personal names, phone numbers, location entities, dates of birth.
   - Detected entities are replaced with placeholders (`<PERSON>`, `<EMAIL>`, etc).
4. **Chunking** (for retrieval, not training): 400-word chunks with 80-word overlap, stored in `corpus_chunks.jsonl` and embedded into Qdrant.
5. **Instruction-format conversion** (for training): each postmortem becomes one SFT pair:
   - **Instruction:** "Given this incident summary and timeline, write a postmortem with root cause, impact, remediation, and learnings."
   - **Input:** extracted incident summary + timeline bullets.
   - **Output:** the original postmortem body.

The training pairs live in DuckDB and are exported as JSONL for the Kaggle training notebook.

### Provenance and licensing

- All sources are publicly accessible at the time of scraping.
- The corpus itself is not redistributed — only the trained adapter and merged model are published.
- The model is licensed Apache 2.0, matching the base Mistral-7B-Instruct-v0.3 license.
- Each source may have its own copyright on individual postmortem text. The training data is held privately; only model weights are released.

### Known data quality issues

- **Severity labelling is weak.** Of ~270 manually-labelled examples used by the [DistilBERT classifier](https://huggingface.co/ayushgupta7777/sentinelops-classifier), only the labelled subset has trustworthy severity tags. The remainder of the corpus has rule-based pseudo-labels.
- **Time skew.** GitHub status incidents are densest 2017→2024; Cloudflare's are denser 2019→2024. Older incidents are underrepresented.
- **PII leakage.** One unscrubbed Presidio placeholder leaks into the QLoRA model's outputs as a literal token (`<PERSON>-macbook-pro`). See Bias and Limitations sections.

---

## 3. Training procedure

### Hyperparameters

| Hyperparameter | Value |
| --- | --- |
| Base model | `mistralai/Mistral-7B-Instruct-v0.3` |
| Quantization | 4-bit NF4 with double quantization, `bnb_4bit_compute_dtype=bfloat16` |
| LoRA rank | 16 |
| LoRA alpha | 32 |
| LoRA dropout | 0.05 |
| Target modules | All linear layers (`q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`) |
| Optimizer | `paged_adamw_8bit` |
| Learning rate | 2e-4, cosine schedule, 3% warmup |
| Per-device batch size | 2 |
| Gradient accumulation | 8 (effective batch size 16) |
| Epochs | 3 |
| Sequence length | 2048 |
| Mixed precision | bfloat16 |
| Trainer | TRL `SFTTrainer` |
| Trainable parameters | ~30M (~0.4% of total) |

### Hardware and compute

- **Hardware:** Kaggle free tier, 2×T4 GPUs available; QLoRA training fits on one T4. The second T4 stays idle.
- **Wall-clock time:** ~7 hours per epoch at the above batch size. Total ~21 hours across two Kaggle sessions, since Kaggle's 9-hour session cap forces checkpoint-and-resume.
- **Checkpointing:** every 50 steps to `/kaggle/working/`, pushed to a dataset attached to the resumed notebook.
- **Tracking:** all runs logged to Weights & Biases under project `sentinelops`, job_type `qlora_sft`.

### Software stack (locked)

```
torch==2.5.1+cu124        # from pytorch.org index, NOT Kaggle default
transformers==4.46.3
peft==0.13.2
trl==0.12.2
accelerate==1.1.1
bitsandbytes==0.45.0
datasets==3.1.0
huggingface_hub==0.27.1
tokenizers==0.20.3
wandb==0.18.7
```

These versions are interlocked — Kaggle's base image churns weekly and partial pins cause `bitsandbytes` ABI breakage. The training notebook reinstalls the entire stack with `--force-reinstall --no-cache-dir` as cell 1.

### Post-training pipeline

1. **Merge.** The trained LoRA adapter is merged into the base model with `peft.PeftModel.merge_and_unload()`. Output: `sentinelops-mistral7b-merged` on HF (FP16, ~14 GB).
2. **AWQ quantize.** The merged model is quantised to 4-bit AWQ with `autoawq==0.2.7.post2` on a single T4. Calibration on 8 sequences of length 512 with single-parallel-sample (anything larger OOMs layer 0). Output: `sentinelops-mistral7b-awq` on HF (~4 GB).
3. **Adapter publish.** The standalone LoRA adapter is published separately as `sentinelops-mistral7b-qlora-adapter` for users who want to layer it on their own base copy.

The AWQ model is what vLLM serves on Modal in production.

---

## 4. Evaluation

The eval harness uses the **Ragas** framework with LLM-as-judge graders. Two evaluation tracks run in parallel:

- **Canonical track** — 20-case golden set graded by `llama-3.3-70b-versatile` (Groq Batch API). Slower, cheaper per-token, no rate limit. This produces the headline numbers.
- **CI fast track** — 10-case fast set graded by `llama-3.1-8b-instant` (Groq live API). Used as the per-PR gate; cheap to run on every commit but a weaker grader.

The grader models are **never the same architecture as the model under test** — using a Mistral-7B grader on a Mistral-7B subject would conflate model and grader biases.

### Canonical results (20-case, 70B grader)

| Metric | Value |
| --- | --- |
| Faithfulness | **0.6307** |

Faithfulness is computed by atomic-claim decomposition: each generated postmortem is broken into atomic factual claims, each claim is verified against the retrieved contexts, and the score is `supported / total`.

#### Score distribution (n = 20)

```
0.90 – 1.00  ▇▇▇▇▇                  5 rows
0.75 – 0.90  ▇▇▇▇▇▇                 6 rows  ← 11 rows already meet the 0.75 bar
0.50 – 0.75  ▇▇▇                    3 rows
0.25 – 0.50  ▇▇▇                    3 rows
0.00 – 0.25  ▇▇▇                    3 rows  ← three rows scored exactly 0.00
```

**Eleven of twenty rows already meet the 0.75 brief target.** The mean is dragged down by a heavy left tail of three score-0 rows where the model confabulated extensively under sparse retrieval. The shape of the distribution is more useful than the mean — see Failure Modes below.

### CI fast results (10-case, 8B grader)

The committed baseline at `evaluation/baselines/main_8b.json`:

| Metric | Value |
| --- | --- |
| Faithfulness | 0.5132 |
| Answer relevancy | 0.6563 |
| Context precision | 0.7918 |
| Context recall | 0.3368 |

These numbers are systematically lower than the 70B canonical numbers — the 8B grader is more aggressive about flagging claims as unsupported. The CI gate compares **PR delta vs this baseline**, not absolute values, so grader strictness is constant across the comparison.

### Methodology details

- **Golden set construction.** 20 alert→postmortem pairs sampled from a holdout slice that was excluded from the training corpus. The "answer" is the model's draft; the "ground truth" is the original postmortem; the "contexts" are the top-5 chunks retrieved by Qdrant + BGE reranker for that alert.
- **Atomic claim decomposition** is performed by the grader model itself with a single-shot prompt; see `evaluation/batch_eval/build_batch.py`.
- **Per-claim verification** is performed by the same grader against the retrieved contexts.
- **No data leakage.** Holdout cases were never seen during fine-tuning. The Qdrant corpus the agent retrieves over **does** include the source postmortems for these incidents, so context_recall measures how well the retriever surfaces the relevant chunks rather than testing whether the model has seen the answer (it has not been trained on these specific pairs).

---

## 5. Failure modes

The 0.63 number is below the brief's 0.75 target. The dominant failure mode is **specific-detail confabulation under sparse evidence**, and it is worth documenting precisely because it is a textbook artefact of fluency-trained generation under sparse RAG, not a tuning bug.

### The named failure mode

When the alert payload is one line — e.g. `KafkaConsumerLagHigh lag=15000` — and the retrieved runbook chunks describe **general** remediation steps rather than this specific incident, the fine-tuned model still produces a fully-formed postmortem with:

- **Invented timestamps** (`2022-08-02 14:25 UTC`)
- **Invented pod and node identifiers** (`kafka-consumer-7d8f4c-xyz on node ip-10-2-1-44`)
- **Invented root causes** (`a bug in the consumer group implementation caused an infinite loop in rebalance`)
- **Invented remediation steps** presented as historical fact

The grader correctly flags every one of these as unsupported. Worst-case rows score 0/16 and 0/19 supported claims.

### Why this happens

The model was QLoRA-fine-tuned on ~2,000 real public postmortems, **all of which contain specific timestamps, named services, and concrete root causes**. It learned that "postmortem" entails specifics. When the evaluation contexts don't supply those specifics, the model falls back on invention rather than abstention or placeholders.

This is a known and well-documented behaviour pattern for fluency-trained LLMs in sparse-RAG settings. The mitigations a production system would apply — abstention prompts, calibrated decoding, structured output forcing — are real research areas. None are quick wins on a 5-week timeline.

### What does *not* fail

- **No brand hallucination.** A brand-blocklist sanitizer (introduced in Week 3 Chat 5) plus an EVIDENCE-ONLY system prompt successfully prevent the model from inventing well-known company names in remediation suggestions. Faithfulness fails on incident-specific details, not on brand-name imagination.
- **Section structure is reliable.** Every output has the four expected sections (root cause, impact, remediation, learnings). The fine-tuning successfully transferred the postmortem genre.
- **Tool-call routing is reliable.** When wrapped in the LangGraph agent, the model correctly identifies which tool to call given a structured alert (~95% routing accuracy on a 30-case spot check, not formally graded).

### Why we accept 0.63 rather than chase a higher number

Two reasons:

1. **Honesty over hand-tuning.** The failure mode above is real and well-understood. A model card that names it precisely is more defensible in an interview than a marginally-higher score chased through prompt iterations against the same 20-case set. Score-chasing on the eval set is the textbook wrong move.
2. **Operational cost.** Tonight's 70B grading run consumed ~67K of the 100K-token rolling-24h Groq TPD budget. A second iteration would have to wait or move to the Batch API for canonical numbers — which is exactly where the canonical pipeline now lives.

The right next step is **expanding the golden set to 100 cases** and re-running canonical evals via the Batch API, not re-prompting the grader against the same 20.

---

## 6. Limitations

- **Tiny canonical eval set (n = 20).** Confidence intervals on the faithfulness mean are wide. A bootstrapped 95% CI is approximately ±0.10. Treat 0.63 as directional, not as a population estimate.
- **Tiny CI eval set (n = 10).** Same caveat, more pronounced. The CI gate works because it tests a relative delta against a fixed baseline, not an absolute threshold.
- **English only.** All training and eval data is English. Performance on non-English incident reports is undefined and likely poor.
- **Hyperscaler bias.** See Bias section.
- **No human-grader spot check at this size.** The brief plans for one — it's on the post-launch backlog.
- **Sparse-RAG confabulation.** The single most important limitation; see Failure Modes.
- **No factuality on novel incidents.** The model cannot verify claims against external systems. Even when an alert payload describes a real ongoing incident, the model's invented details will not match reality unless they happen to appear in retrieved context.
- **Single PII leak.** A `<PERSON>` placeholder was tokenised by the base model into a literal string `<PERSON>-macbook-pro` that leaks into outputs verbatim on row 006 of the canonical eval. The leak is documented and the audit-before-next-fine-tune action is on the project backlog.
- **Modal cold start.** Operational, not a model property: the first call after Modal scale-to-zero takes ~3 minutes to load the 7B weights. Documented in `demo.md`.

---

## 7. Bias considerations

- **Hyperscaler overrepresentation.** Roughly 95% of the corpus is from AWS, Cloudflare, GitHub, and the danluu index (which is itself biased toward large-tech outages). The model's notion of "what an incident looks like" is the public-blogosphere tech-vendor archetype — distributed systems, multi-region, with named SREs and structured timelines. Generalisation to small-org or on-prem incidents is unverified and likely worse.
- **Severity-label conventions vary across orgs.** What Cloudflare calls "P0" is not what AWS calls "Sev-1" is not what your company calls "P0". The model averages these conventions; do not treat its severity-related outputs as calibrated against your org's definitions.
- **Postmortem genre conventions vary.** Some orgs publish externally-facing summaries (sanitised, brief); others publish internally-styled reports (detailed, technical). The model leans toward the externally-facing style because that is what dominates the public corpus.
- **Time bias.** Incidents from 2017–2024 are densely represented; older and very recent incidents are underrepresented.
- **The PII leak (`<PERSON>-macbook-pro`).** During training, a Presidio placeholder appearing in a node-name string was tokenised and learned as a literal sequence. The model occasionally emits this string verbatim on incidents involving personal hardware — a tell that the original incident report named someone whose name was scrubbed but whose context wasn't. This is a data-quality issue, not a privacy disclosure (the original name is gone), but it is an artefact future fine-tunes should address by stricter cleanup of placeholder-adjacent context.

---

## 8. Environmental impact

Approximate values for the QLoRA training:

- **GPU-hours:** ~21 (single T4)
- **Estimated kgCO₂eq:** ~3 kg, assuming a typical Kaggle data centre carbon intensity. Computed via the Lacoste et al. ML CO2 calculator with `T4 / 21h / Kaggle US-Central`.
- **Inference compute** scales with usage; not material at demo volumes.

This figure is small because QLoRA's whole point is fitting a 7B fine-tune onto one T4 rather than a multi-A100 node. Full fine-tuning at 7B would have been ~10× higher.

---

## 9. How to use the model

```python
# Option A: serve the AWQ-quantised model with vLLM
# (recommended; ~4 GB VRAM, fits on one T4)

from vllm import LLM, SamplingParams

llm = LLM(
    model="ayushgupta7777/sentinelops-mistral7b-awq",
    quantization="awq",
    max_model_len=4096,
    dtype="float16",
)

prompt = """[INST] Given this incident summary and timeline, write a
postmortem with root cause, impact, remediation, and learnings.

Summary: ...
Timeline:
- ...
- ...
[/INST]"""

result = llm.generate([prompt], SamplingParams(temperature=0.2, max_tokens=1024))
print(result[0].outputs[0].text)
```

```python
# Option B: load the LoRA adapter on a base Mistral copy
# (for users who want to apply the adapter on their own base model)

from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base = AutoModelForCausalLM.from_pretrained(
    "mistralai/Mistral-7B-Instruct-v0.3",
    torch_dtype="bfloat16",
    device_map="auto",
)
model = PeftModel.from_pretrained(
    base, "ayushgupta7777/sentinelops-mistral7b-qlora-adapter"
)
tokenizer = AutoTokenizer.from_pretrained("mistralai/Mistral-7B-Instruct-v0.3")
```

Recommended generation settings: `temperature=0.2, top_p=0.9, max_tokens=1024`. The model is fine-tuned for short-form postmortem drafts, not chat or long-form generation.

---

## 10. Citation

This is engineering, not research — there is no paper. If you reference the project, use:

```
@misc{sentinelops_2026,
  author       = {Ayush Gupta},
  title        = {SentinelOps: An agentic LLM copilot for SRE incident response},
  year         = {2026},
  howpublished = {\url{https://github.com/ayushgupta07xx/sentinelops}},
}
```

## 11. Acknowledgments

- Mistral AI for releasing Mistral-7B-Instruct-v0.3 under Apache 2.0.
- The maintainers of `peft`, `trl`, `bitsandbytes`, `transformers`, `vllm`, and `autoawq`.
- Cloudflare, GitHub, AWS engineering teams for publishing transparent post-event reports.
- [`danluu/post-mortems`](https://github.com/danluu/post-mortems) for the curated postmortem index.
- BAAI for the BGE embedding + reranker series.
- Kaggle and Modal for free GPU compute.
- Groq for free LLM-as-judge inference.
- Anthropic for [Claude](https://claude.ai/), the build partner that paired through the architecture and most of the code.

## 12. Changelog

- **2026-04 v0.1** — initial release. 20-case canonical eval at faithfulness 0.6307. 10-case CI baseline committed.
