# SentinelOps Demo Runbook

End-to-end reproduction of SentinelOps from a clean repository, plus a script for the recorded demo video.

If anything below diverges from observed behaviour, the [Week 4 DoD evidence](demo/week4_dod.md) is the canonical first-run reference.

---

## Video

📹 **2-minute walkthrough:** *(link goes here once recorded)*

The video shows: chaos triggered against the upstream ObservaShop platform → Alertmanager fires → alert lands on the Kafka `alerts` topic → the LangGraph agent retrieves runbooks and drafts a postmortem → result published to `triage_results` → Grafana dashboards update in real time.

Script for the recording is in [`docs/demo/video_script.md`](demo/video_script.md).

---

## Prereqs

Tested on Ubuntu 22.04 (WSL2 on Windows 11). Other Linux distributions should work; macOS is untested.

| Tool | Tested version | Purpose |
| --- | --- | --- |
| Docker Desktop | 4.x | Container runtime, kind backend |
| `kubectl` | ≥ 1.29 | Kubernetes CLI |
| `kind` | ≥ 0.23 | Local Kubernetes |
| `helm` | ≥ 3.14 | Chart installs |
| `python` | 3.11 | Project venv |
| `modal` CLI | latest | Inference serving |
| `gh` | latest | (Optional) GitHub Actions log inspection |

External accounts required:

- **Modal** (free tier — $30/month rolling credit) for inference serving.
- **Groq** (free tier) for the LLM-as-judge grader.
- **HuggingFace** (free) for model hosting access tokens.
- **Weights & Biases** (free) for training experiment tracking *(only needed if retraining)*.

---

## One-shot bring-up

From a clean clone:

```bash
git clone https://github.com/ayushgupta07xx/sentinelops.git
cd sentinelops

# 1. Python env
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Local services (Redpanda + Postgres + Airflow)
docker compose up -d redpanda postgres airflow

# 3. Kubernetes stack — see `bootstrap.sh` for the full sequence
./bootstrap.sh

# 4. Configure secrets
cp .env.example .env
$EDITOR .env   # MODAL_VLLM_API_KEY, GROQ_API_KEY, HF_TOKEN, etc.

# 5. Deploy fine-tuned model to Modal
modal deploy serving/inference/modal_vllm.py
```

Expected wall-clock time on a fresh machine: **~12 minutes** for the cluster bring-up plus **~2 minutes** for the Modal deploy. Most of the time is image pulls.

After bring-up, verify:

```bash
kubectl get pods -A | grep -E "argocd|monitoring|sentinelops"
docker compose ps
curl -s https://<your-modal-handle>--sentinelops-vllm-serve.modal.run/v1/models \
  -H "Authorization: Bearer $(grep MODAL_VLLM_API_KEY .env | cut -d= -f2)" \
  | python -m json.tool
```

You should see all pods `Running`, all compose services `Up (healthy)`, and the Modal endpoint returning a model list with `id: sentinelops-mistral7b`.

---

## Smoke test — single `/triage` call

Port-forward the API and POST a sample alert:

```bash
# Terminal 1
kubectl -n sentinelops port-forward svc/sentinelops-api-microservice 8001:80

# Terminal 2
curl -X POST http://localhost:8001/triage \
  -H 'Content-Type: application/json' \
  -d @docs/demo/sample_alert.json
```

### Or via the React UI

```bash
# Terminal 3 — Vite dev server
cd serving/ui
npm install        # first time only
npm run dev        # http://localhost:5173
```

The UI POSTs to `/triage` via the Vite dev proxy (avoids the WSL/Chrome localhost-bridging quirk and any CORS configuration on the FastAPI side). Pick a sample alert, click **Triage alert**, watch the live amber latency counter tick up while the agent runs.

The first call after Modal idle takes **~3 minutes** (cold start, vLLM loads the 7B). Subsequent warm calls return in **~120–140 seconds** — the LLM generation dominates. See [Latency expectations](#latency-expectations) below.

The response includes the drafted postmortem, the retrieved contexts, and the tool-call trace. To stream tokens instead, use `WS /stream` (the FastAPI WebSocket endpoint).

---

## End-to-end flow

This is the demo-video path. Assumes upstream ObservaShop is running on the same kind cluster (separate project — see https://github.com/ayushgupta07xx/observashop).

```bash
# 1. Trigger chaos in ObservaShop (latency injection on checkout)
kubectl -n observashop annotate deployment checkout-api \
  chaos.observashop/inject=latency --overwrite

# 2. Watch the alert land on Kafka
docker exec -it sentinelops-redpanda \
  rpk topic consume alerts --offset start --num 1

# 3. Watch the agent's response on triage_results
docker exec -it sentinelops-redpanda \
  rpk topic consume triage_results --offset 1 --num 1

# 4. Open Grafana to see the dashboards update
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# Browse http://localhost:3000  (admin / prom-operator)
# Dashboards: "SentinelOps — LLM Ops" and "SentinelOps — RAG Quality"
```

> **Demo replay note.** Offset 0 on `triage_results` holds an older `ReadTimeout` error from a development run. Real drafts start at **offset 1+**. Use `--offset 1` when consuming for demo replay.

### Evidence from earlier runs

- [`demo/week4_dod.md`](demo/week4_dod.md) — the original Definition-of-Done evidence (Week 4): cluster healthy, dashboards populated, CI green, eval gate blocks a bad PR.
- [`demo/grafana_llm_ops.png`](demo/grafana_llm_ops.png) — the LLM Ops dashboard during a triage call.
- [`demo/grafana_rag_quality.png`](demo/grafana_rag_quality.png) — the RAG Quality dashboard.
- [`demo/week5_chat1_llm_ops.png`](demo/week5_chat1_llm_ops.png), [`demo/week5_chat1_rag_quality.png`](demo/week5_chat1_rag_quality.png) — Week 5 streaming integration evidence.
- [`demo/gate_ci_pr.png`](demo/gate_ci_pr.png), [`demo/gate_ci_workflow.png`](demo/gate_ci_workflow.png), [`demo/gate_local_fail.png`](demo/gate_local_fail.png) — CI eval gate blocking a regression PR.

---

## Latency expectations

Honest numbers from observed behaviour, not aspirational targets:

| Stage | Cold (idle Modal) | Warm |
| --- | --- | --- |
| Modal vLLM cold start (load 7B AWQ) | ~3 min | — |
| Qdrant retrieval (top-20 dense) | ~50 ms | ~50 ms |
| BGE reranker (cross-encoder, 20 → 5) | ~600 ms | ~600 ms |
| Mistral-7B generation (~2,500 chars) | ~80 s | ~80 s |
| Agent orchestration + 2 mock tools | ~5 s | ~5 s |
| End-to-end `/triage` | ~3 min | ~120–140 s |

**Implications for orchestrators.** Any client that calls `/triage` indirectly — Kafka consumers, Airflow tasks, the demo curl — must set request timeout **≥ 600 s** to survive cold start, or pre-warm with a direct POST before the orchestrated run. The Modal app idles to zero after ~24 hours of inactivity; **redeploy** with `modal deploy serving/inference/modal_vllm.py` if `/v1/models` returns 404.

---

## Troubleshooting

### `kind` cluster won't start

> *"docker network kind not found"* during registry connect.

The local registry must be connected to the `kind` Docker network **after** `kind create cluster` runs (the cluster command creates the network). The `bootstrap.sh` ordering handles this; if you ran a custom sequence, retry:

```bash
docker network connect kind kind-registry || true
```

### ArgoCD install hits the 256KB annotation limit

> *"metadata.annotations: Too long: must have at most 262144 bytes"*

Use server-side apply:

```bash
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

### ArgoCD app stays `OutOfSync` even after `git push`

ArgoCD reads multi-source apps from the GitHub origin, not local commits. Force a sync:

```bash
kubectl patch application <app-name> -n argocd \
  --type=merge -p '{"operation":{"sync":{}}}'
```

### Grafana dashboards show "No data"

ServiceMonitor objects need the `release: kube-prometheus-stack` label to be discovered. Check:

```bash
kubectl get servicemonitor -n sentinelops -o yaml | grep -A1 labels:
```

If the label is missing, set `serviceMonitor.additionalLabels.release: kube-prometheus-stack` in the chart values and `helm upgrade`.

### Airflow UI returns connection refused on port 8081

The Airflow compose service binds `host:8081 → container:8080`. Host port 8080 is already held by the kind ingress for ObservaShop. Don't move the kind ingress; if 8081 is also taken, edit `docker-compose.yml`.

### Modal `/v1/models` returns 404

Modal apps auto-clean after ~24 hours of idle. Redeploy:

```bash
modal deploy serving/inference/modal_vllm.py
```

### `/triage` returns 502 / timeout on first call

Cold start. Wait the full 3 minutes; the request will eventually return. For demos, **always pre-warm** with a throwaway POST before recording.

### CI eval gate fails locally but passes on GitHub Actions (or vice versa)

The gate uses different judge models in CI (`llama-3.1-8b-instant`) than in canonical runs (`llama-3.3-70b-versatile` via Batch). Set the judge explicitly:

```bash
JUDGE_MODEL=llama-3.1-8b-instant python evaluation/ragas_suite.py
```

Force a clean re-run:

```bash
rm -rf evaluation/.checkpoint/
JUDGE_MODEL=llama-3.1-8b-instant python evaluation/ragas_suite.py
```

### Groq returns 429 mid-eval

The 70B `llama-3.3-70b-versatile` has a 100K-TPD rolling-24h cap. The 8B `llama-3.1-8b-instant` has a 6K-TPM **per-request** ceiling — `input_tokens + max_tokens` must stay under 6K. The committed `evaluation/ragas_suite.py` truncates contexts to 800 chars and answers to 1500 chars to stay safely under; if you bump these, you'll hit 429.

For canonical runs, use the Groq Batch API path documented in `evaluation/batch_eval/`.

---

## Cleanup

```bash
# Stop the kind cluster (preserves images and state)
kind delete cluster --name sentinelops

# Stop docker-compose services
docker compose down

# Remove the local registry container
docker rm -f kind-registry || true

# Stop Modal app (so it doesn't burn idle credit on warm-pool keepalive)
modal app stop sentinelops-vllm
```

A full re-bring-up after this is back to the **~12-minute** wall clock above.

---

## Hardware footprint

Tested on i7-12700H, 16 GB RAM, no GPU.

- **Cluster pods at idle:** ~1.4 GB RAM total across argocd + monitoring + sentinelops namespaces.
- **Compose services at idle:** ~600 MB (Redpanda 250 MB, Postgres 50 MB, Airflow 300 MB).
- **Peak during a `/triage` call:** ~2.0 GB on the host (the heavy lifting is on Modal, not local).

Modal handles all GPU compute. Nothing on the host needs CUDA.
