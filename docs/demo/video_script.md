# Demo video script

**Target length:** 2:00–2:15 (under 2:30 absolute max — attention drops sharply after that on LinkedIn).

**Frame:** SentinelOps as a real internal SRE tool. The viewer should see (a) a working product, (b) the AI/ML behind it, (c) the operational scaffolding that makes it production-shaped.

---

## What it must communicate

In priority order:

1. **The fine-tuned LLM is real and works.** A drafted postmortem appears, grounded in retrieved evidence, in front of the camera.
2. **The training was real.** W&B charts show 21 GPU-hours of QLoRA fine-tuning.
3. **The eval is real.** The CI gate blocks a regression PR.
4. **The observability is real.** Grafana panels respond to live traffic.
5. **The system is production-shaped.** Kafka ingestion + Airflow retraining + Kubernetes deployment exist and are visible.

Everything else is editorial.

---

## Pre-stage checklist

Do all of this *before* pressing record. The 2 minutes assume zero fumbling.

### Infra (allow ~10 min)

```bash
# 1. Modal redeploy + warm-up (~5 min)
modal deploy serving/inference/modal_vllm.py
curl -s https://ayushgupta07xx--sentinelops-vllm-serve.modal.run/v1/models \
  -H "Authorization: Bearer $(grep MODAL_VLLM_API_KEY .env | cut -d= -f2)" \
  > /dev/null && echo "Modal up"

# 2. Port-forward (Terminal A — leave running)
kubectl -n sentinelops port-forward svc/sentinelops-api-microservice 8001:80

# 3. Pre-warm /triage so the recording isn't blocked on cold start
curl -X POST http://localhost:8001/triage \
  -H 'Content-Type: application/json' \
  -d @docs/demo/sample_alert.json --max-time 240 > /dev/null
# After this, subsequent calls are warm (~140s)

# 4. Vite UI (Terminal B — leave running)
cd serving/ui && npm run dev

# 5. Grafana port-forward (Terminal C — leave running)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80

# 6. ArgoCD port-forward (Terminal D — leave running)
kubectl -n argocd port-forward svc/argocd-server 8080:443

# 7. Compose services
docker compose ps  # confirm redpanda + postgres + airflow are up
```

### Browser tabs (set up in this exact order, in one Chrome window)

1. **localhost:5173** — the React UI (sample = HighDatabaseLatency, fields populated, ready to click Triage)
2. **W&B run page** — your QLoRA training run, scrolled to the **Charts** view filtered to `gpu.0` so the GPU SM clock + Power Usage panels are visible
3. **localhost:3000** — Grafana, on the **SentinelOps — LLM Ops** dashboard, time range "Last 1 hour"
4. **Grafana tab #2** — separate browser tab on **SentinelOps — RAG Quality** dashboard
5. **github.com/ayushgupta07xx/sentinelops/actions** — pinned to a workflow run where the **eval gate failed** (have one ready; if not, open a throwaway PR that breaks the agent and let CI fail it)
6. **localhost:8081** — Airflow UI, opened to `weekly_retrain_dag` graph view, with one prior successful run visible in the calendar

### Terminals to capture (any tiling layout)

- A small terminal showing `docker exec -it sentinelops-redpanda rpk topic consume triage_results --offset 1 --num 1` already executed, with one drafted postmortem visible.

### Display setup

- **Resolution:** 1920×1080 minimum. Higher is fine if your editor scales output back to 1080p.
- **Browser zoom:** 110%. The default 100% looks tiny on video; 110% fills the frame without clipping the UI.
- **Cursor:** enable a cursor-highlight tool (PointerFocus / OBS plugin). Without it, viewers lose track of clicks.
- **Notifications:** all off. Slack, Discord, system update banners — kill them.

### Audio

- USB mic plugged in, levels checked at -12 dB peak in Audacity.
- Quiet room. Close window, kill fan.
- Drink water before recording — saliva clicks ruin takes.

---

## Tools

| Tool | Purpose | Free |
| --- | --- | --- |
| **OBS Studio** | Screen capture (1080p, 30 fps) | Yes |
| **Audacity** | Narration recording | Yes |
| **DaVinci Resolve** *(or)* **Clipchamp** | Editing | Yes |
| **PointerFocus** *(Windows)* | Cursor highlight | 30-day trial; or use OBS's built-in cursor effects |
| **Inkscape** | Title cards / closing card | Yes |

**OBS settings** that matter:
- Output → Recording → Format `mp4`, Encoder `x264`, Rate Control `CRF`, CRF `18`.
- Video → Base Resolution 1920×1080, Output Resolution 1920×1080, FPS 30.

---

## Scene-by-scene timeline

Total: **~2:00**. All times approximate; cut tight.

| # | Time | Duration | Screen | Action | Narration |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00 | 8 s | Title card | Black background, amber accent line, white text:<br>**SENTINELOPS**<br>An agentic LLM copilot for SRE incident response | *"It's 3 AM. An SRE gets paged. They have five minutes to start writing a postmortem."* |
| 2 | 0:08 | 5 s | UI (clean state) | Cursor hovers on `HighDatabaseLatency` sample tile | *"SentinelOps takes the alert…"* |
| 3 | 0:13 | 35 s | UI (loading + result) | Click **Triage alert**. Live amber counter ticks up. Edit in post: speed up the wait 4×–6×. End on the rendered postmortem in the Postmortem tab. | *"…retrieves runbooks and historical incidents from a vector index, queries the agent's tools, and drafts the postmortem with a fine-tuned 7-billion-parameter LLM. End-to-end: under three minutes."* |
| 4 | 0:48 | 12 s | UI — Evidence tab | Click **Evidence**. Hover over the rerank scores (0.771 → 0.030). Expand the top chunk briefly. | *"The retrieval is two-stage. BGE embeddings, then a cross-encoder reranker. The model sees evidence, not just the alert."* |
| 5 | 1:00 | 10 s | UI — Tool trace tab | Click **Tool trace**. Pan slowly down the vertical timeline of tool calls. | *"Behind the UI is a LangGraph agent. Multi-step, with state. Recent alerts, runbook search, Prometheus, then draft."* |
| 6 | 1:10 | 12 s | W&B Charts | Pan slowly across **Training loss**, **GPU SM Clock Speed**, **GPU Power Usage**. | *"The model is fine-tuned with QLoRA — 4-bit NF4 quantisation, rank-16 LoRA — on twenty-one GPU-hours across two Kaggle T4 sessions. Roughly 2,500 real public postmortems."* |
| 7 | 1:22 | 13 s | GitHub Actions failed run | Show the failed workflow page, mouse over the red "ragas-eval-gate" step. Click into the step log, scroll to the line `Faithfulness regression: 0.51 → 0.41 (Δ = −10 pts)` or equivalent. | *"Every pull request runs Ragas with an LLM-as-judge. A faithfulness regression greater than five points fails the build — the same way a unit test would."* |
| 8 | 1:35 | 10 s | Grafana — LLM Ops + RAG Quality | Quick cuts: latency p99, request rate, cost — then RAG dashboard's tool-call panel and hallucination rate. | *"In production: Prometheus + Grafana, with LLM-specific dashboards. Tokens per second. Faithfulness. Cost. Live."* |
| 9 | 1:45 | 8 s | Terminal — `rpk topic consume` | Show alerts on the `alerts` topic, then triage_results. | *"Alerts ingested via Kafka. Decoupled from inference — the SRE alerting path never blocks on the model."* |
| 10 | 1:53 | 5 s | Airflow DAG graph | Show `weekly_retrain_dag` with all-green tasks. | *"Weekly retrain through Airflow. A Keras drift detector decides when to retrain."* |
| 11 | 1:58 | 7 s | Closing card | Black with white + amber:<br>**Built solo · 5 weeks · ₹0 compute**<br>github.com/ayushgupta07xx/sentinelops<br>huggingface.co/ayushgupta7777 | *"SentinelOps. Built solo, in five weeks, on free compute. Open source."* |

---

## Narration as a continuous script

Use this as your teleprompter. Read once aloud at conversational pace and time it — should land at 1:50–2:00 of speech, with screen action filling the gaps.

> **It's 3 AM.** An SRE gets paged. They have five minutes to start writing a postmortem.
>
> SentinelOps takes the alert, retrieves runbooks and historical incidents from a vector index, queries the agent's tools, and drafts the postmortem with a fine-tuned 7-billion-parameter LLM. End-to-end: under three minutes.
>
> The retrieval is two-stage. BGE embeddings, then a cross-encoder reranker. The model sees evidence, not just the alert.
>
> Behind the UI is a LangGraph agent. Multi-step, with state. Recent alerts, runbook search, Prometheus, then draft.
>
> The model is fine-tuned with QLoRA — 4-bit NF4 quantisation, rank-16 LoRA — on twenty-one GPU-hours across two Kaggle T4 sessions. Roughly 2,500 real public postmortems.
>
> Every pull request runs Ragas with an LLM-as-judge. A faithfulness regression greater than five points fails the build — the same way a unit test would.
>
> In production: Prometheus + Grafana, with LLM-specific dashboards. Tokens per second. Faithfulness. Cost. Live.
>
> Alerts ingested via Kafka. Decoupled from inference — the SRE alerting path never blocks on the model.
>
> Weekly retrain through Airflow. A Keras drift detector decides when to retrain.
>
> **SentinelOps.** Built solo, in five weeks, on free compute. Open source.

Word count: ~210. At 150 wpm conversational pace = 84 seconds of speech. Leaves room for screen-action beats and pauses.

---

## Editing notes

### Pace
- **Cut every 2–4 seconds.** Long takes = boring. Even within a single browser, cut between clicks/scrolls.
- **Speed up the /triage wait** in scene 3. Real wait is ~140 s; on screen it should be ~20 s, sped 6×–7× with the counter still readable.
- **Don't speed up narration.** Sped-up speech sounds amateurish.

### Visual treatment
- **Subtle zoom-and-pan (Ken Burns)** on static-looking shots: the W&B charts (scene 6), the Grafana dashboard (scene 8). Not aggressive — 5–8% scale change over the full duration.
- **Cursor highlight** at all times.
- **Match cuts** between scenes 3 and 4 (UI → UI tab change) — keep the same window framing.
- **Title overlays** for each "real" claim:
  - Scene 6: `21 GPU-hours · QLoRA · 4-bit NF4 · rank-16 LoRA`
  - Scene 7: `Ragas · faithfulness · CI eval gate`
  - Scene 8: `Prometheus · Grafana · LLM-specific metrics`
  - Scene 10: `Airflow · drift detector · weekly retrain`

### Audio
- **No background music.** Music in dev-tool demos signals "trying too hard". Voice-only with a tight room tone is more credible.
- **Or** if you must: an extremely subtle ambient pad at -28 dB. Not a track with melody.
- **Cut all "uhm"s and breath spikes** in Audacity before exporting narration.
- **Loudness target:** -16 LUFS integrated (LinkedIn standard).

### Transitions
- **Hard cuts** between scenes. No fades except into the title card and out of the closing card.
- **One transition exception:** a 0.3-second fade-to-black between scenes 5 (Tool trace) and 6 (W&B). The shift from UI to charts deserves a beat.

---

## Thumbnail

For LinkedIn / GitHub README embed:

- **1920 × 1080**, black background.
- **Top-left:** amber dot + `SENTINELOPS` in spaced caps, JetBrains Mono.
- **Center:** the rendered postmortem in monospace, partially visible (~10 lines), with a gradient fade-out at the bottom.
- **Bottom-right:** `Mistral-7B · QLoRA · LangGraph · Kubernetes` as a small footer in zinc-500.
- **No play-button overlay** — LinkedIn / GitHub add their own.

---

## Metadata for sharing

**LinkedIn post copy** lives in a separate doc — see `docs/launch/linkedin_post.md` *(generated separately)*.

**GitHub README embed:**

```markdown
[![SentinelOps demo](docs/demo/thumbnail.png)](https://www.youtube.com/watch?v=YOUR_VIDEO_ID)
```

(or a Loom / direct MP4 link if you don't want to use YouTube)

**Video description (YouTube / Vimeo):**

```
SentinelOps — agentic LLM copilot for SRE incident response.
Mistral-7B-Instruct fine-tuned with QLoRA on 2,000+ real public postmortems,
served via vLLM on Modal, retrieval-augmented over Qdrant + BGE,
deployed end-to-end on Kubernetes with Prometheus + Grafana observability
and a Ragas-based CI eval gate.

Built solo in 5 weeks on free compute. Open source.

Repo: https://github.com/ayushgupta07xx/sentinelops
Model: https://huggingface.co/ayushgupta7777/sentinelops-mistral7b-awq
Architecture: https://github.com/ayushgupta07xx/sentinelops/blob/main/docs/architecture.md
```

---

## If something goes wrong on recording day

| Problem | Fast fix |
| --- | --- |
| Modal cold-starts mid-take | Pre-warm with a `curl` before pressing record. Always. |
| `/triage` timeouts | Confirm the API pod is Running, then re-warm. If still failing, redeploy Modal. |
| UI layout looks broken in OBS but fine in browser | Browser zoom is at 100%. Set to 110%. Hard-refresh (Ctrl+Shift+R). |
| GitHub Actions failed-run page is missing | Open a throwaway PR that breaks `evaluation/golden_set/eval_inputs.jsonl` (delete a few lines so the agent's outputs no longer match) and let CI fail. |
| Grafana panels show "No data" | Hit `/triage` once to generate fresh metrics, wait 30 s for Prometheus scrape. |

---

## Definition of done for the video

- [ ] One single MP4, 1080p, under 50 MB if possible (re-encode at CRF 22 if larger).
- [ ] Captions burned in **or** uploaded as `.srt` alongside (LinkedIn auto-mutes).
- [ ] Thumbnail PNG separate (don't rely on the video frame).
- [ ] Linked from `README.md` (one line under the Demo section), `docs/demo.md` (Video section), and the LinkedIn post.

After the video is recorded and posted, this script is no longer load-bearing — feel free to delete `docs/demo/video_script.md` from the repo or keep it as documentation of the recording process.
