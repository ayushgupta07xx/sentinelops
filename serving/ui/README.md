# SentinelOps UI

A Vite + React + TypeScript + Tailwind frontend for the `/triage` API. Dark, minimal, dev-tool aesthetic — Linear-style typography, amber accent, monospace for technical fields.

## Run

```bash
cd serving/ui
npm install
npm run dev
```

Vite serves on `http://localhost:5173`.

In a separate terminal, port-forward the API the UI talks to:

```bash
kubectl -n sentinelops port-forward svc/sentinelops-api-microservice 8001:80
```

To point at a different API, set `VITE_SENTINELOPS_API_URL` before `npm run dev`, or override at runtime via the Settings drawer in the header.

## What it does

The UI is a single-purpose tool: take an alert payload, post it to `/triage`, render the result.

- **Sample selector** (4 scenarios, including the canonical `HighDatabaseLatency` and `KafkaConsumerLagHigh` which exposes the model's documented sparse-evidence failure mode).
- **Live latency counter** during the request — shows real elapsed time, with phase hints (`Connecting` → `Retrieving runbooks` → `Reranking` → `Generating draft` → `Modal cold start`).
- **Four result tabs**: Postmortem (formatted), Evidence (retrieved chunks, expandable), Tool trace (vertical timeline of LangGraph nodes), Raw (full JSON).
- **Defensive about response shape** — tries multiple field names (`postmortem`/`draft`/`response`/`output`/`answer`) so it survives API evolution.
- **Severity-coloured pills** (P0 red, P1 amber, P2 sky, P3 zinc).

## Build

```bash
npm run build
# Output: serving/ui/dist/
```

The build is a static SPA (one HTML + one JS bundle). Deploy anywhere — Vercel, Cloudflare Pages, GitHub Pages, S3 + CloudFront, an Nginx ConfigMap in the cluster.

## Stack

- **Vite 5** for dev server + bundler
- **React 18** with strict mode
- **TypeScript 5** strict
- **Tailwind 3** with a custom config (Inter sans, JetBrains Mono mono, amber semantic accent)
- **No component library** — every component is hand-written in `src/App.tsx`. ~440 lines, single file, no abstractions until they earn their keep.

## Theme

| Token | Value |
| --- | --- |
| Background | `bg-zinc-950` |
| Surface | `bg-zinc-900/50` |
| Border | `border-zinc-800` |
| Text primary | `text-zinc-100` |
| Text secondary | `text-zinc-400` |
| Text muted | `text-zinc-600` |
| Accent | `bg-amber-500` / `text-amber-500` |
| Sans | Inter (cv02, cv03, cv04, cv11 features enabled) |
| Mono | JetBrains Mono |
| Selection | `rgba(245, 158, 11, 0.25)` |

The aesthetic is intentionally restrained: no gradients, no glassmorphism, sharp 3-4px radii, tight letter-spacing on caps, a single accent colour. Compared to default Streamlit / shadcn out-of-the-box, this looks bespoke.
