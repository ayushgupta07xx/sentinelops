# Week 2 Status — QLoRA fine-tuning

## ✅ Done
- SFT dataset: 1,556 train / 28 val pairs from deduped postmortem corpus, instruction-formatted
- QLoRA training: Mistral-7B-Instruct-v0.3, 4-bit NF4, LoRA r=16/α=32, 3 epochs, cosine LR, checkpoint-and-resume across 2 Kaggle sessions. W&B run public.
- Merged adapter → fp16 → HF: `ayushgupta7777/sentinelops-mistral7b-merged` (14.5 GB)
- AWQ 4-bit quantize → HF: `ayushgupta7777/sentinelops-mistral7b-awq` (~4.2 GB)
- A/B sanity check (10 held-out): AWQ shows 2× ref Jaccard (0.238 vs 0.123) and in-distribution narrative style matching Cloudflare/GitLab training voice. Base Mistral scores higher on generic-template rubric but writes textbook-style; AWQ writes like real postmortems.

## 🟡 Accepted / deferred
- AWQ calib budget small (8 samples × 512 tokens) due to T4 VRAM ceiling. Document in Week 5 model card.
- HF model cards empty on both repos. Fill in Week 5.
- A/B rubric (section-coverage) penalizes style-transfer-correct outputs. Frame as "style match" metric in model card, not a regression.

## ⏭ Week 3 scope
- 8-10 SRE runbooks in docs/runbooks/
- Qdrant embed + two-stage retrieval (bge-small + bge-reranker-base)
- LangGraph agent with tool-use
- FastAPI triage + streaming endpoints
- Initial Ragas eval on 20 synthetic alerts

## 📂 Repo state
- Through Day 6: all Week 2 artifacts committed, tag week2-complete
- Commit: 501134c

## 🔑 Env / infra
- Kaggle quota: ~12/30 hrs remaining this week
- Modal credits: untouched, reserved for Week 4
- HF: merged + AWQ repos public
- W&B: QLoRA run public
