# SentinelOps — Project Brief

**Owner:** Ayush Gupta
**Goal:** Ship a deep, interview-defensible AI/ML flagship project in 5 weeks that anchors an AI/ML-focused resume and clears 90+ ATS on AI Engineer / ML Engineer / AI/ML Engineer roles.
**Status:** Architecture locked. Ready to build.

---

## 0. For Claude on claude.ai — how to work from this document

You are the build partner. The user (Ayush) has agreed on this architecture. Your job is to execute week by week, not re-litigate it.

**Working context:**
- Environment: claude.ai (not Claude Code). User is on Pro plan.
- User's top priority: maximize forward progress per message, minimize token usage. Every response should earn its tokens.
- User's skill level: can follow a tutorial, can debug, cannot write from scratch. Explain just enough to run/paste/debug — no essays.
- User's hardware: Windows 11, i7-12700H, 16 GB RAM, no usable GPU. All GPU work goes to Kaggle (training) and Modal (serving).
- Budget: ₹0. Every tool has a free-tier alternative.

**Response rules:**
1. **Brief explanations only.** One or two sentences of what a file does + where to paste it. No deep tutorials unless Ayush explicitly asks.
2. **Files as artifacts.** When outputting code, use artifacts so Ayush can copy cleanly. One artifact per logical file/module.
3. **Don't re-output unchanged files.** If a file works, it works. Only produce edits for files that need changing, using precise diffs or "replace lines X-Y with…".
4. **Batch related answers.** If Ayush asks three questions, answer all three in one response.
5. **Assume paste-and-run workflow.** Ayush saves files to the paths you specify, runs them locally, reports errors. You don't have filesystem access.
6. **End-of-week status.** At the end of each week, produce a ≤10-line status note: what works, what's flaky, what's deferred.
7. **Hold the architecture.** Don't pivot scope without Ayush's explicit approval. Don't add tools not in Section 4.
8. **One week per chat.** A new chat starts for each week. Ayush will paste a short "where we are" summary at the top.

**Do not:**
- Write essays when two sentences suffice.
- Train on Ayush's laptop.
- Re-output files that haven't changed.
- Add interview prep or deep conceptual explanations unless asked — that phase comes after the project ships.

---

## 1. Project identity

**Name:** SentinelOps

**One-line pitch:** An agentic LLM copilot for SRE incident response, built as an end-to-end MLOps platform — fine-tuned on real public postmortems, retrieval-augmented with live runbooks and metrics, served with production-grade observability on Kubernetes.

**Why this project, for this candidate:** Ayush has an existing DevOps/SRE flagship (ObservaShop). SentinelOps sits on top of that infrastructure and tells a unique story no other AI/ML fresher can tell: "I build reliable systems, and I build AI systems for reliability." The two projects compound each other.

**What it is not:**

- Not a chatbot demo. It's a production-shaped MLOps system.
- Not an API wrapper around a closed model. The core LLM is fine-tuned by us.
- Not a research project. Evaluation is pragmatic (Ragas + LLM-as-judge), not novel.

---

## 2. Constraints (read before every week)

| Constraint | Value | Implication |
|---|---|---|
| Budget | ₹0 | Every tool must have a free tier that lasts the project lifetime. |
| Hardware | 16 GB RAM, no GPU | All training and inference on remote free compute. |
| Skill level | Tutorial-follower, debugger, not from-scratch coder | Code with extensive comments + plain-English summaries. |
| Timeline | 5 weeks | Aggressive. Anything non-critical gets cut, not extended. |
| Interview defense | Every component must be defensible | No cargo-culted tech. Every decision has a documented reason. |

---

## 3. Architecture

Four-layer system, top-to-bottom data flow:

**Layer 1 — Data platform:** Stream (Kafka) + batch (Airflow) ingestion of postmortems and live alerts. DuckDB as local warehouse.

**Layer 2 — ML training:** TensorFlow DistilBERT classifier (incident severity + category) as baseline. PyTorch + QLoRA fine-tuning of Mistral-7B-Instruct on postmortem corpus.

**Layer 3 — Serving and agent:** vLLM serves the fine-tuned model on Modal. Qdrant holds runbook + postmortem embeddings. LangGraph agent orchestrates tool calls (runbook search, Prometheus query, postmortem drafting). FastAPI exposes REST + WebSocket streaming.

**Layer 4 — Observability:** Prometheus + Grafana instrument LLM-specific metrics (tokens/sec, TTFT, hallucination rate, retrieval precision). Ragas + LLM-as-judge run in CI on every PR. GitHub Actions eval gate blocks PRs that degrade model quality.

The whole stack runs on a local kind Kubernetes cluster via Helm, on the same cluster setup reused from ObservaShop.

---

## 4. Tech stack with justifications

For each tool, the interview answer is in bold. Memorize these.

### Languages
- **Python** (primary): ML, data, serving, agent.
- **Go** (minor): one CLI tool for in-cluster operations, reusing the pattern from ObservaShop.
- **Bash, YAML**: infra.
- **SQL**: DuckDB transformations.

### Data layer
- **Kafka** (via Redpanda locally — Kafka API-compatible, lighter weight). **"Alerts are naturally streaming; Kafka decouples alerting from ML inference so one can fail without taking down the other."**
- **Airflow** (running in Docker). **"Re-training is scheduled, not one-shot. Airflow handles retries, backfills, and dependency management."**
- **DuckDB** (embedded, no server). **"I needed a local SQL warehouse for incident analytics without running Postgres. DuckDB is columnar and fast for analytical queries on the postmortem corpus."**

### ML training
- **TensorFlow 2.x + Keras** (DistilBERT classifier). **"Strong non-generative baseline to benchmark the LLM against. BERT-family classifiers are still SOTA for discriminative NLP tasks."**
- **PyTorch + Transformers + PEFT** (QLoRA on Mistral-7B-Instruct). **"QLoRA lets me fine-tune a 7B model on a single T4 with 4-bit NF4 quantization + LoRA adapters. Full fine-tuning is impossible on free compute; QLoRA is the standard approach in 2025 and produces production-quality adapters."**
- **Hugging Face Hub** (model + dataset hosting). Free, public.
- **Weights & Biases** (experiment tracking). Free personal tier.
- **MLflow** (model registry, runs locally). **"W&B for experiment tracking, MLflow for the model registry — it's the canonical lifecycle split in most ML teams."**

### Retrieval and agent
- **Qdrant** (vector DB, local + free cloud tier). **"Qdrant has payload filtering, a permissive free tier, Rust performance, and runs identically local and cloud."**
- **BAAI/bge-small-en-v1.5** (embeddings). **"Small enough to embed locally, top of MTEB for its size class."**
- **BAAI/bge-reranker-base** (reranker). **"Two-stage retrieval: dense recall, then cross-encoder reranking, cuts irrelevant context by ~30% in my evals."**
- **LangGraph** (agent framework). **"Incident response is multi-step with state — the agent needs to remember what it tried. LangGraph's graph-based state is the right primitive; LangChain's basic chains aren't."**

### Serving
- **vLLM** on **Modal** (free tier credits). **"vLLM's PagedAttention + continuous batching gives 2–5× throughput over naive HF inference. Modal's free credit covers the demo lifetime."**
- **FastAPI** + **WebSockets** for streaming tokens. **"Async framework with streaming support; standard choice for ML inference APIs."**
- **4-bit AWQ quantization** at inference. **"Shrinks the 7B model to ~4 GB VRAM so it fits on a cheap T4, with <1% quality loss."**

### Evaluation
- **Ragas** (RAG eval: faithfulness, answer relevance, context precision, context recall).
- **LLM-as-judge** (llama-3.3-70b-versatile via Groq free tier, acts as the grader). **"I can't hire human annotators. LLM-as-judge with a stronger model grading my fine-tuned model is standard; I validate the grader with a small human-labeled spot-check."**
- **Custom eval harness**: ~100 held-out incidents with ground-truth postmortems for factuality checks.

### Observability
- **Prometheus + Grafana** (reused from ObservaShop). Custom dashboards for LLM: tokens/sec, TTFT, p99 latency, cost/request, retrieval precision@k, hallucination rate (via LLM-as-judge).
- **Loki** for log aggregation.

### Deploy and CI
- **kind** (local K8s), **Helm** (single reusable chart), **ArgoCD** (GitOps). Reuses ObservaShop patterns.
- **GitHub Actions** CI/CD with **Trivy** CVE scanning and a **Ragas eval gate** that blocks PRs dropping faithfulness > 5%.

---

## 5. Free-compute strategy

| Need | Free tier | Limits | Lifetime |
|---|---|---|---|
| GPU training | Kaggle notebooks | 30 hr/week, 2×T4, **9-hr session cap** | Forever |
| GPU inference (demo) | Modal | $30/mo starter credit (resets monthly) | Rolling |
| GPU inference (fallback) | HF Inference Endpoints | Serverless tier | Forever |
| LLM-as-judge grader | Groq (`llama-3.3-70b-versatile`) | 30 RPM, 6K TPM, **1,000 RPD** | Forever |
| Model hosting | HuggingFace Hub | Unlimited public | Forever |
| Vector DB (cloud) | Qdrant Cloud | 1 GB free cluster, AWS Frankfurt | Forever |
| Experiment tracking | Weights & Biases | 30-day Pro trial, then free tier | Forever |
| Demo frontend | HF Spaces OR Vercel | Free tier | Forever |
| Kafka | Redpanda (local Docker) | Self-hosted | Forever |
| Airflow | Local Docker Compose | Self-hosted | Forever |

**Day-1 setup: COMPLETE.** All six accounts created. Credentials in local `sentinelops.env` (not in repo). Mistral-7B-Instruct-v0.3 license accepted on HF.

**Known constraints to design around:**
- Kaggle's 9-hour session cap means Week 2 QLoRA training needs checkpoint-and-resume. Training script must save adapter checkpoints every N steps and be able to resume from the latest.
- Groq's 1,000 RPD cap on the 70B model means Week 3/4 eval runs need batching across multiple days, OR use Groq's Batch API (50% off, doesn't count against rate limits, 24h–7d turnaround).

---

## 6. Repository structure

```
sentinelops/
├── README.md
├── docker-compose.yml          # local dev: Redpanda, Qdrant, Prometheus, Grafana, Airflow
├── pyproject.toml              # Python deps (uv or poetry)
├── .github/workflows/          # CI with Ragas eval gate + Trivy
├── data/
│   ├── scrapers/               # postmortem scrapers (danluu, Cloudflare, GitHub, AWS)
│   ├── preprocessing/          # clean, dedupe, PII scrub, instruction-format
│   └── warehouse/              # DuckDB schema + load scripts
├── training/
│   ├── classifier/             # TensorFlow DistilBERT baseline
│   │   ├── train.py
│   │   ├── eval.py
│   │   └── configs/
│   ├── llm/                    # PyTorch QLoRA fine-tuning
│   │   ├── sft_dataset.py
│   │   ├── train_qlora.py      # Kaggle-ready
│   │   ├── merge_adapters.py
│   │   ├── quantize_awq.py
│   │   └── configs/
│   └── notebooks/              # exported Kaggle notebooks
├── serving/
│   ├── api/                    # FastAPI app
│   ├── agent/                  # LangGraph agent + tool definitions
│   ├── rag/                    # Qdrant client, embeddings, reranker
│   └── inference/              # vLLM config + Modal deployment
├── streaming/
│   └── alert_consumer/         # Alertmanager webhook → Kafka → agent
├── orchestration/
│   └── airflow/
│       └── dags/               # weekly_retrain_dag.py
├── evaluation/
│   ├── ragas_suite.py
│   ├── llm_judge.py
│   ├── golden_set/             # 100 held-out incidents
│   └── reports/
├── observability/
│   ├── prometheus/
│   │   ├── prometheus.yml
│   │   └── alert_rules.yml
│   └── grafana/
│       └── dashboards/
│           ├── llm_ops.json
│           └── rag_quality.json
├── deploy/
│   ├── helm/
│   │   └── sentinelops/        # single reusable chart
│   └── k8s/
│       └── kind-config.yaml
├── cli/
│   └── sentinelctl/            # Go CLI (cobra)
└── docs/
    ├── architecture.md
    ├── model_card.md
    ├── decisions.md            # ADRs
    ├── runbooks/               # the agent retrieves these
    │   ├── high_latency.md
    │   ├── database_down.md
    │   └── ...
    ├── postmortem_template.md
    └── demo.md                 # how to reproduce end-to-end
```

---

## 7. Week-by-week plan

**Pace assumption:** 6–8 hrs/day, 6 days/week. If Week N slips, cut scope *within* Week N+1, do not push weeks.

### Week 1 — Data platform and classifier baseline

**Goal:** Clean postmortem corpus in DuckDB + working TensorFlow DistilBERT classifier.

- [ ] Repo scaffold, `pyproject.toml`, `docker-compose.yml` (Redpanda + Qdrant + Postgres for Airflow + Grafana + Prometheus).
- [ ] Scrape corpus:
  - [ ] `danluu/post-mortems` repo (has curated links to ~400+ postmortems).
  - [ ] Cloudflare blog (public post-mortem tag).
  - [ ] GitHub status incidents (public, via Atom feed).
  - [ ] AWS public post-event summaries.
  - Target: 2,000–3,000 incidents with title, body, date, service, severity (if labeled).
- [ ] Preprocessing: HTML-to-text, dedupe (MinHash), PII scrub (regex + Presidio), normalize.
- [ ] Load into DuckDB with a star schema: `fact_incidents`, `dim_services`, `dim_categories`.
- [ ] Label a subset (~500) with severity (P0/P1/P2/P3) and category (networking, database, deploy, capacity, auth). Use weak labeling (regex + keyword rules) for the rest.
- [ ] TensorFlow DistilBERT classifier on Kaggle:
  - [ ] Tokenize with HF tokenizer.
  - [ ] Fine-tune on labeled set.
  - [ ] Eval: precision/recall/F1 per class, confusion matrix.
  - [ ] Publish to HF Hub as a model card.

**Definition of done:** `duckdb corpus.db` with ≥2,000 rows; classifier achieves ≥0.75 macro-F1 on held-out test set; model pushed to HF.

### Week 2 — QLoRA fine-tuning

**Goal:** Fine-tuned Mistral-7B-Instruct adapter that writes incident postmortems in the right style.

- [ ] Build SFT dataset: convert each postmortem into an instruction-format pair. Example:
  - Instruction: "Given this incident summary and timeline, write a postmortem with root cause, impact, remediation, and learnings."
  - Input: extracted incident summary + timeline bullets.
  - Output: original postmortem body.
- [ ] Aim for 1,500–2,500 training pairs.
- [ ] QLoRA training on Kaggle (2×T4):
  - [ ] 4-bit NF4 quantization, LoRA rank 16, alpha 32, target modules = all linear layers.
  - [ ] TRL `SFTTrainer`.
  - [ ] Log everything to W&B.
  - [ ] 3 epochs, batch size 2, grad accumulation 8, cosine LR schedule.
  - [ ] **Checkpoint every 50 steps + resume-from-checkpoint logic** (Kaggle 9-hr session cap — training will span 2–3 sessions).
- [ ] Merge adapter into base + push merged model to HF Hub.
- [ ] AWQ quantize the merged model for serving.
- [ ] Sanity-check generation quality vs base Mistral on 10 held-out examples.

**Definition of done:** Adapter trained, W&B run public, merged model on HF, AWQ-quantized model on HF, manual A/B shows clear improvement over base on incident-writing task.

### Week 3 — RAG, agent, FastAPI

**Goal:** Working agent that takes an alert and drafts an incident response plan using runbook retrieval + Prometheus query tools.

- [ ] Write 8–10 realistic SRE runbooks in `docs/runbooks/` (high latency, DB down, OOM, deployment failure, etc.). Reuse what you already have from ObservaShop.
- [ ] Embed runbooks + historical postmortems into Qdrant using `bge-small-en-v1.5`. Payload = {source, date, service, severity, url}.
- [ ] Two-stage retrieval: top-20 dense, then rerank to top-5 with `bge-reranker-base`.
- [ ] LangGraph agent with tools:
  - `search_runbooks(query) -> list[chunk]`
  - `query_prometheus(promql) -> result` (mock against ObservaShop's Prometheus)
  - `get_recent_alerts(service, window) -> list[alert]`
  - `draft_postmortem(context) -> str` (calls the fine-tuned model)
- [ ] FastAPI service:
  - `POST /triage` — full agent workflow on an alert payload.
  - `POST /draft-postmortem` — direct postmortem generation.
  - `WS /stream` — streaming token output.
- [ ] Initial Ragas eval on 20 synthetic alert cases.

**Definition of done:** FastAPI up locally, agent routes a real sample alert through retrieval + draft, Ragas faithfulness ≥ 0.75 on the 20-case set.

### Week 4 — Serving, observability, K8s deploy

**Goal:** Production-shaped deployment on kind cluster with full LLM observability.

- [ ] Deploy fine-tuned model to Modal with vLLM (AWQ-quantized). Expose as OpenAI-compatible endpoint.
- [ ] Point FastAPI serving at Modal endpoint (or HF Inference endpoint as fallback).
- [ ] Instrument FastAPI with Prometheus metrics:
  - `llm_tokens_per_second`, `llm_time_to_first_token_seconds`, `llm_request_duration_seconds`, `llm_cost_usd_total`, `rag_retrieval_precision_at_5`, `rag_cache_hit_ratio`, `agent_tool_call_total{tool=...}`, `hallucination_rate` (sampled via LLM-as-judge).
- [ ] Grafana dashboards: `llm_ops.json` (latency/throughput/cost) and `rag_quality.json` (retrieval + faithfulness trends).
- [ ] Helm chart for SentinelOps (one chart, values per service). Reuse ObservaShop patterns.
- [ ] Deploy to local kind cluster via ArgoCD GitOps.
- [ ] SLOs: availability ≥99%, p99 end-to-end triage latency <8s, faithfulness ≥0.75. Multi-burn-rate alerts on each.
- [ ] GitHub Actions CI:
  - Lint, test, Trivy scan.
  - Ragas eval gate: block PR if faithfulness drops >5 points vs main.
  - Path-filtered matrix builds.

**Definition of done:** `kubectl get pods -n sentinelops` shows everything Running, Grafana dashboards populated with real data, CI is green, eval gate demonstrably blocks a bad PR (create one intentionally to prove it).

### Week 5 — Kafka streaming, Airflow, polish, docs

**Goal:** Full end-to-end streaming demo + complete documentation.

- [ ] Kafka integration:
  - Alertmanager webhook receiver (FastAPI) → publishes to Kafka topic `alerts`.
  - Consumer service → enriches alert → calls agent's `/triage` → writes response to `triage_results` topic.
- [ ] Airflow DAG `weekly_retrain_dag.py`:
  - Tasks: scrape new postmortems → preprocess → load to DuckDB → evaluate current model → if drift detected, trigger QLoRA retrain notebook via Kaggle API → register new model in MLflow.
- [ ] TF/Keras drift detector (small MLP, ~80 lines) integrated into the Airflow `weekly_retrain_dag` as the drift-check task. Standalone — no dependency on `transformers` TF support. Rationale: keeps TensorFlow as a live, serving component of the system after the Week 1 classifier pivoted to PyTorch (see `docs/decisions.md` ADR-001).

- [ ] Docs:
  - `README.md` with architecture diagram, quickstart, demo GIF.
  - `architecture.md` — the full breakdown.
  - `model_card.md` — training data, metrics, limitations, intended use, bias notes.
  - `decisions.md` — the ADRs accumulated across all weeks.
  - `demo.md` — exact reproduction steps.
- [ ] 2-minute demo video: trigger an ObservaShop chaos, watch the alert flow through Kafka → agent → drafted postmortem → Grafana dashboards updating.
- [ ] Resume bullets (see Section 11).
- [ ] LinkedIn post draft.

**Definition of done:** One-command bootstrap (`./bootstrap.sh`) brings the whole stack up; the demo video works end-to-end; README renders cleanly on GitHub; model card is complete and honest.

---

## 8. Success criteria (definition of done)

Project ships if all of these are true:

- [ ] Fine-tuned Mistral-7B adapter published on HF Hub with model card.
- [ ] TensorFlow DistilBERT classifier published on HF Hub with ≥0.75 macro-F1.
- [ ] W&B project public with training runs.
- [ ] FastAPI service deployed via Helm to kind cluster.
- [ ] Grafana dashboards showing real LLM telemetry.
- [ ] CI with Ragas eval gate green on main.
- [ ] Kafka → agent end-to-end streaming demo works.
- [ ] Airflow DAG runnable (doesn't have to have actually retrained — demonstrably triggers the chain).
- [ ] GitHub repo is public, README is strong, demo video is linked.

---

## 9. Rejected alternatives (keep in your head)

If an interviewer asks "why didn't you use X?" — these are the rehearsed answers.

| Alternative | Why we rejected |
|---|---|
| Apache Spark | Corpus is 2–3k incidents, not billions. Spark adds complexity without depth on an AI/ML project. Moved to a future dedicated data-engineering project. |
| Snowflake | Free tier is 30-day time-limited. DuckDB gives us the same SQL experience locally, forever, and dbt compiles to both. |
| dbt | Lightweight enough that inline Python SQL is sufficient at this scale; dbt's value kicks in at 20+ models, we have ~5. |
| LangChain basic chains | Incident response is multi-step with state; `Chain` objects don't express that cleanly. LangGraph's state graph is the right abstraction. |
| Full fine-tuning | Impossible on free compute for 7B. QLoRA is the industry-standard alternative and produces production-quality adapters. |
| Llama-3.1-8B (instead of Mistral-7B) | Either works. Mistral-7B is slightly smaller, has a cleaner base model, and its license is Apache 2.0. Llama's license is more restrictive. |
| GPT-4 / Claude via API | Defeats the project's purpose — we want to demonstrate training, not calling. API models appear only as the LLM-as-judge grader. |
| Pinecone / Weaviate / Chroma | Qdrant has a better free cloud tier than Pinecone, better performance than Chroma at scale, and simpler operations than Weaviate. |
| TGI / Triton | vLLM's PagedAttention is best-in-class for throughput. TGI is catching up, Triton is more config-heavy. |
| Human annotators for eval | No budget. LLM-as-judge with a stronger model + a small human spot-check is the standard workaround. |

---

## 10. Resume bullets (draft — refine in Week 5)

Use these as a starting point. Tune quantified numbers in Week 5 based on actual runs.

**SentinelOps — Agentic LLM Copilot for SRE Incident Response | PyTorch, TensorFlow, QLoRA, LangGraph, vLLM, Kubernetes**

- Engineered an end-to-end MLOps platform fine-tuning Mistral-7B-Instruct with **QLoRA (4-bit NF4, rank-16 LoRA adapters)** on a self-compiled 2,500-incident public postmortem corpus, trained across **Kaggle T4 GPUs using PyTorch + PEFT + TRL**, with full experiment tracking in **Weights & Biases** and model registry in **MLflow**; achieved [X]% improvement in faithfulness over base model as graded by a Llama-3.1-70B LLM-as-judge harness.
- Built a two-stage **retrieval-augmented agent** using **LangGraph** with tool-use (Prometheus query, runbook search, postmortem drafting) backed by **Qdrant vector DB**, **BGE embeddings**, and a **BGE cross-encoder reranker**, improving retrieval precision@5 by [Y]% over single-stage dense retrieval; served via **FastAPI + WebSockets** with **vLLM** AWQ-quantized inference on Modal for 2–5× throughput.
- Shipped a **TensorFlow + Keras DistilBERT** baseline classifier for incident severity and category achieving [Z] macro-F1, published with a complete **Hugging Face model card**; built a **Ragas + LLM-as-judge evaluation suite** integrated into a **GitHub Actions CI eval gate** that blocks PRs dropping faithfulness >5 points.
- Deployed the full stack to **Kubernetes via Helm + ArgoCD GitOps**, instrumented with **Prometheus + Grafana** dashboards for LLM-specific metrics (tokens/sec, TTFT, p99 latency, hallucination rate, retrieval precision) and SLO-based multi-burn-rate alerts; streaming alerts ingested via **Kafka (Redpanda)** and weekly retraining orchestrated via **Airflow**.

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Kaggle GPU queue delays training | Medium | Kick off every training run end-of-day; let it run overnight. |
| QLoRA run doesn't converge | Medium | Have 3 configs ready (rank 8/16/32). Pick the one with best loss curve. |
| Modal free credit exhausted mid-demo | Low | HF Inference Endpoints as fallback; document switchover. |
| Fine-tuned model is worse than base | Low-Medium | Smaller LR, more epochs, cleaner data. If still bad by end of Week 2, reduce scope to "style transfer" framing (measurable style match) instead of factual improvement. |
| kind cluster OOMs locally (16 GB RAM) | Medium | Scale down replicas, skip non-essential services locally, full stack only on demo day. |
| User doesn't understand QLoRA conceptually after Week 2 | Medium | End-of-Week-2 sanity check: Ayush(user) explains QLoRA back to Claude in 3–5 sentences. If unclear, pause Week 3 and re-explain. (Understanding matters for debugging too, not just interviews.) |
| Scope creep | High | This brief is the contract. Any addition goes to a "v2" doc, not this project. |

---

## End of brief

When a new week's chat starts, Claude should confirm:

1. The brief is loaded from project knowledge.
2. Which week we're on and its Definition of Done.
3. Any status notes or blockers from the previous week.

Then begin work.