## ADR-001 — Dual-framework classifier baseline (TF + PyTorch)

**Date:** Week 1, Day 6
**Status:** Accepted

**Context:** Original plan (Section 4) specified TensorFlow/Keras for the
DistilBERT baseline classifier. Mid-Week-1, Hugging Face's `transformers`
library on Kaggle's current image no longer exposes `TFAutoModel` — TF support
has been progressively deprecated, and pinning `transformers==4.40.2` to
restore it created cascading dependency conflicts (tokenizers, sentence-
transformers, tf-keras API drift).

**Decision:** Keep the TF/Keras implementation (`model.py`, `train.py`) as the
initial baseline artifact — it compiles, runs locally on CPU, and documents
the intended approach. Train the production baseline in PyTorch
(`model_pt.py`, `train_pt.py`) on Kaggle T4, which has no such issues. Both
live in the repo.

**Consequences:**
  for production after HF deprecated TF in transformers."
- Week 5 Airflow DAG will include a TF/Keras drift-detection MLP to keep TF
  as a live, serving component of the system.
- Unifies Week 1 (classifier) and Week 2 (QLoRA) on a single framework for
  the main ML pipeline, simplifying the project story.## ADR-002 — Two-tier eval grader (8B inner-loop, 70B canonical)
**Date:** Week 4
**Status:** Accepted
**Context:** Brief Section 5 specifies `llama-3.3-70b-versatile` via Groq's
free tier for LLM-as-judge grading, with a 100K-tokens-per-day rolling-24h
cap. A single ragas run (4 metrics × 20 cases) consumes ≈96K tokens and
just barely fits inside the wall — a second run inside 24h returns 429.
Running the 70B grader on every PR push, as the original CI plan implied,
would block CI within hours of the first merge of the day. Day-4
measurements established a faithfulness floor of 0.63 with the 70B grader.
**Decision:** Split the grader into two tiers. Use `llama-3.1-8b-instant`
(Groq free tier, 500K TPD) as the inner-loop CI grader for fast
feedback on PRs. Reserve `llama-3.3-70b-versatile` for canonical baseline
runs (model card publication, release tags), invoked manually or via
Groq's Batch API. `evaluation/ragas_suite.py` reads `JUDGE_MODEL` from the
environment; CI sets 8B explicitly, the default for local ad-hoc runs is
the 70B canonical.
**Consequences:**
- CI feedback loop is now bound by HTTP latency, not by Groq TPD windows.
- Two committed baselines: `evaluation/baselines/main_8b.json` is the
  operational gate floor; the 70B canonical baseline is generated for the
  model card.
- The 8B grader is slightly noisier and more lenient than the 70B; the
  model card cites the 70B number, the CI gate cites the 8B
  number. `evaluation/baselines/README.md` documents the rationale.

## ADR-002 — Two-tier eval grader (8B inner-loop, 70B canonical)
**Date:** Week 4
**Status:** Accepted
**Context:** Brief Section 5 specifies `llama-3.3-70b-versatile` via Groq's
free tier for LLM-as-judge grading, with a 100K-tokens-per-day rolling-24h
cap. A single ragas run (4 metrics × 20 cases) consumes ≈96K tokens and
just barely fits inside the wall — a second run inside 24h returns 429.
Running the 70B grader on every PR push, as the original CI plan implied,
would block CI within hours of the first merge of the day. Day-4
measurements established a faithfulness floor of 0.63 with the 70B grader.
**Decision:** Split the grader into two tiers. Use `llama-3.1-8b-instant`
(Groq free tier, 500K TPD) as the inner-loop CI grader for fast
feedback on PRs. Reserve `llama-3.3-70b-versatile` for canonical baseline
runs (model card publication, release tags), invoked manually or via
Groq's Batch API. `evaluation/ragas_suite.py` reads `JUDGE_MODEL` from the
environment; CI sets 8B explicitly, the default for local ad-hoc runs is
the 70B canonical.
**Consequences:**
- CI feedback loop is now bound by HTTP latency, not by Groq TPD windows.
- Two committed baselines: `evaluation/baselines/main_8b.json` is the
  operational gate floor; the 70B canonical baseline is generated for the
  model card.
- The 8B grader is slightly noisier and more lenient than the 70B; the
  model card cites the 70B number, the CI gate cites the 8B
  number. `evaluation/baselines/README.md` documents the rationale.

## ADR-003 — Truncated eval inputs for the 8B grader
**Date:** Week 4
**Status:** Accepted
**Context:** Even after picking the 8B-instant grader (ADR-002, 500K TPD
headroom), Groq enforces a hard 6,000-tokens-per-minute *per-request*
ceiling on the 8B model. `input_tokens + max_tokens` must stay strictly
below 6K for a single request. Realistic incident contexts (five
retrieved runbook chunks averaging ~1,800 chars each) plus a 4K-token
answer plus ragas's metric-prompt overhead pushed multiple cases over
the wall, returning 413s even on the inner loop.
**Decision:** Truncate eval inputs at the dataset level — contexts to
800 chars each, answers to 1500 chars — and pin
`max_tokens=4096, max_workers=1, RunConfig.timeout=600` in the suite.
Reduce the in-CI case count from 20 to 10 (chunk-3 verbose
ground-truth cases were the marginal failures). Grade in 5-case chunks
with `evaluation/.checkpoint/` resume so a single chunk failure does
not cost the whole run.
**Consequences:**
- The 10-case 8B configuration is the operational gate floor; the
  full 20-case canonical run is reserved for the 70B Batch API
  (ADR-004).
- `evaluation/golden_set/eval_inputs.jsonl` in the repo is the
  truncated 10-case file. `python evaluation/run_eval.py`
  regenerates the full 20-case version on demand.
- The chunked checkpoint cache key is `chunk_idx`, not a content
  hash — changing eval params requires `rm -rf evaluation/.checkpoint/`
  before re-running. Documented as a gotcha.

## ADR-004 — Groq Batch API as the canonical-eval path
**Date:** Week 4
**Status:** Accepted, Batch implementation deferred to Week 5
**Context:** Groq's free tier enforces *two* limits that interact
badly with CI:
1. `llama-3.3-70b-versatile`: 100K TPD rolling-24h (ADR-002).
2. `llama-3.1-8b-instant`: 6K TPM per-request hard ceiling (ADR-003).
Even with truncation, the 8B path occasionally fails in CI on
413 token-overflow because of subtle ragas / langchain-groq /
sentence-transformers version drift between the local pinned venv
and a fresh CI install — the same eval inputs that pass locally
land ~22 tokens above the wall in CI. There is no clean,
free-tier-only way to make CI deterministically green-bar on every
push.
**Decision:** Architecturally, the canonical eval path is **Groq's
Batch API** with the 70B grader — no rate limits, 50% off pricing,
24h-7d turnaround — exactly as the brief Section 5 anticipated.
The CI inner-loop runs the 8B grader as best-effort: when it
succeeds it gates the PR; when it 413s, the gate **logic** has
already been validated locally and the wiring is what CI proves.
Manual 70B Batch runs trigger before model card publication
(Week 5) and on release tags thereafter.
**Consequences:**
- The CI eval-gate is best-effort on the free tier. The
  demonstrable artifact is the gate *logic*, exhibited locally
  via a synthetic-bad ragas report
  (`docs/demo/gate_local_fail.png`) plus the CI workflow proving
  the wiring (`docs/demo/gate_ci_pr.png`,
  `docs/demo/gate_ci_workflow.png`).
- Week 5 model card cites the 70B Batch API canonical run, not
  the 8B 10-case baseline.
- `docs/demo/week4_dod.md` calls out this asymmetry explicitly so
  the project story is honest in interviews.
- A future paid-tier upgrade or Batch API integration in CI
  removes the asymmetry without changing any of the code paths
  built in Week 4.

  ## ADR-005 — Vite + React + TypeScript for the demo frontend (over Streamlit)

**Status:** Accepted, 2026-05-08.

**Context.** SentinelOps needs a clickable surface for the demo video and a reference UI for the `/triage` API. The default lazy choice for an ML demo is Streamlit — fastest to wire up, single-file, runs in the existing Python venv. Initial implementation went that direction.

**Decision.** Replaced Streamlit with a Vite + React + TypeScript + Tailwind SPA before the demo recording.

**Reasoning.**
1. **Aesthetic credibility.** Streamlit's default look is recognisable as "AI-generated demo" — the sidebar shape, default fonts, default accent colours. For a project meant to read as a real internal SRE tool, this signals the wrong genre.
2. **Skill alignment.** React + TypeScript + Tailwind is the project's frontend stack; the demo UI matches it.
3. **Deployment portability.** A built React SPA is one HTML + one JS bundle — deployable to Vercel, HF Spaces, Cloudflare Pages, or as static assets behind any API gateway. Streamlit needs a Python runtime everywhere it runs.
4. **Design discipline.** Hand-written Tailwind components carry intentional design tokens (amber accent, JetBrains Mono for technical fields, sharp corners, no gradients) that no off-the-shelf framework provides out of the box.

**Consequences.**
- The UI is a separate sub-project with its own toolchain (npm, Vite). The Python `pyproject.toml` extras are unchanged.
- A Vite dev proxy (`/triage` → `localhost:8001`) sidesteps the WSL/Chrome localhost-bridging quirk and avoids needing CORS configuration on the FastAPI side.
- A small CI job runs `npm ci && npm run build` on changes under `serving/ui/` to catch TypeScript regressions before merge.

**Rejected alternatives.**
- **Streamlit with heavy custom theming** — possible but the layout primitives still read as Streamlit.
- **Single-file HTML + Tailwind CDN** — looks identical on screen, but doesn't demonstrate frontend project structure.
- **shadcn/ui or another component library** — faster but the bespoke aesthetic was the point. ~440 lines of hand-rolled Tailwind components instead.