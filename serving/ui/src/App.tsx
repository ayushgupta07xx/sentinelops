import { useEffect, useMemo, useState } from 'react'

const DEFAULT_API_URL =
  (import.meta.env.VITE_SENTINELOPS_API_URL as string | undefined) ?? ''
const TRIAGE_TIMEOUT_MS = 600_000

type Severity = 'P0' | 'P1' | 'P2' | 'P3'

interface AlertPayload {
  alertname: string
  service: string
  severity: Severity
  summary: string
  labels: Record<string, string>
}

interface Sample {
  id: string
  title: string
  subtitle: string
  alert: AlertPayload
}

const SAMPLES: Sample[] = [
  {
    id: 'highdb',
    title: 'HighDatabaseLatency',
    subtitle: 'canonical · well-retrieved',
    alert: {
      alertname: 'HighDatabaseLatency',
      service: 'checkout-api',
      severity: 'P1',
      summary: 'p99 DB query latency 4.2s, breaching 500ms SLO for 12 min',
      labels: { region: 'us-east-1', db: 'orders-pg-primary' },
    },
  },
  {
    id: 'kafkalag',
    title: 'KafkaConsumerLagHigh',
    subtitle: 'sparse evidence · exposes failure mode',
    alert: {
      alertname: 'KafkaConsumerLagHigh',
      service: 'events-consumer',
      severity: 'P2',
      summary: 'Consumer lag 15000 messages, growing ~500/min',
      labels: { topic: 'orders.created', group: 'events-consumer-v2' },
    },
  },
  {
    id: 'podnotready',
    title: 'PodNotReady',
    subtitle: 'scheduling failure',
    alert: {
      alertname: 'PodNotReady',
      service: 'users-api',
      severity: 'P2',
      summary:
        'users-api pod stuck in Pending state for 8 min, no schedulable nodes',
      labels: { namespace: 'production', pod: 'users-api-7d4f-x2k4' },
    },
  },
  {
    id: 'diskfull',
    title: 'DiskFull',
    subtitle: 'imminent outage',
    alert: {
      alertname: 'DiskFull',
      service: 'kafka-broker-2',
      severity: 'P0',
      summary: 'Disk usage 96% on /var/lib/kafka, projected full in 47 min',
      labels: { node: 'kafka-2.prod', mountpoint: '/var/lib/kafka' },
    },
  },
]

const SEV_STYLES: Record<Severity, string> = {
  P0: 'bg-red-500/10 text-red-400 border-red-500/30',
  P1: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  P2: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  P3: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
}

type TabId = 'postmortem' | 'evidence' | 'trace' | 'raw'

// ---------------------------------------------------------------------------
// Defensive extractors — the API response shape may evolve; these try multiple
// field names so the UI keeps working without code changes.
// ---------------------------------------------------------------------------
function extractPostmortem(d: any): string | null {
  return (
    d?.postmortem ?? d?.draft ?? d?.response ?? d?.output ?? d?.answer ?? null
  )
}

function extractContexts(d: any): any[] {
  return (
    d?.retrieved_contexts ??
    d?.contexts ??
    d?.retrieved ??
    d?.evidence ??
    d?.runbook_chunks ??
    []
  )
}

function extractTrace(d: any): any[] {
  // Prefer an explicit trace if the API returns one
  const direct = d?.tool_trace ?? d?.tools_called ?? d?.trace ?? d?.steps
  if (Array.isArray(direct) && direct.length > 0) return direct

  // Otherwise synthesize from observed agent-output fields
  const steps: Array<Record<string, any>> = []
  if (Array.isArray(d?.recent_alerts)) {
    steps.push({
      name: 'get_recent_alerts',
      detail: `${d.recent_alerts.length} alert${d.recent_alerts.length === 1 ? '' : 's'} in window`,
      meta: d.recent_alerts[0]?._mock ? 'mock' : undefined,
    })
  }
  if (Array.isArray(d?.runbook_chunks) && d.runbook_chunks.length) {
    const top = Math.max(
      ...d.runbook_chunks.map(
        (c: any) => c?.rerank_score ?? c?.dense_score ?? 0,
      ),
    )
    steps.push({
      name: 'retrieve_runbooks',
      detail: `${d.runbook_chunks.length} chunks · BGE rerank · top ${top.toFixed(3)}`,
    })
  }
  if (d?.prom_results) {
    steps.push({
      name: 'query_prometheus',
      detail: d.prom_results.query || 'no query specified',
      meta: d.prom_results._mock ? 'mock' : undefined,
    })
  }
  if (typeof d?.draft === 'string') {
    steps.push({
      name: 'draft_postmortem',
      detail: `${d.draft.length.toLocaleString()} chars · Mistral-7B (AWQ)`,
    })
  }
  return steps
}

function extractText(c: any): string {
  if (typeof c === 'string') return c
  return c?.text ?? c?.content ?? c?.page_content ?? JSON.stringify(c, null, 2)
}

function extractTitle(c: any, i: number): string {
  if (typeof c === 'string') return `Chunk ${i}`
  return c?.title ?? c?.source ?? c?.source_type ?? c?.id ?? `Chunk ${i}`
}

function extractStepName(s: any, i: number): string {
  if (typeof s === 'string') return s
  return s?.tool ?? s?.name ?? s?.node ?? `Step ${i}`
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const [sampleId, setSampleId] = useState(SAMPLES[0].id)
  const sample = useMemo(
    () => SAMPLES.find((s) => s.id === sampleId) ?? SAMPLES[0],
    [sampleId],
  )

  const [alertname, setAlertname] = useState(sample.alert.alertname)
  const [service, setService] = useState(sample.alert.service)
  const [severity, setSeverity] = useState<Severity>(sample.alert.severity)
  const [summary, setSummary] = useState(sample.alert.summary)
  const [labelsText, setLabelsText] = useState(
    JSON.stringify(sample.alert.labels, null, 2),
  )
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL)

  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<any>(null)
  const [finalElapsed, setFinalElapsed] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('postmortem')

  // Reset form when sample changes
  useEffect(() => {
    setAlertname(sample.alert.alertname)
    setService(sample.alert.service)
    setSeverity(sample.alert.severity)
    setSummary(sample.alert.summary)
    setLabelsText(JSON.stringify(sample.alert.labels, null, 2))
  }, [sample])

  // Tick the live elapsed counter while loading
  useEffect(() => {
    if (!loading) return
    const t0 = performance.now()
    setElapsed(0)
    const id = setInterval(() => {
      setElapsed((performance.now() - t0) / 1000)
    }, 100)
    return () => clearInterval(id)
  }, [loading])

  async function triage() {
    setError(null)
    setResult(null)
    setFinalElapsed(null)

    let labels: Record<string, string>
    try {
      labels = labelsText.trim() ? JSON.parse(labelsText) : {}
    } catch (e) {
      setError(`Labels field is not valid JSON: ${(e as Error).message}`)
      return
    }

    const payload: AlertPayload = {
      alertname,
      service,
      severity,
      summary,
      labels,
    }

    setLoading(true)
    const t0 = performance.now()
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), TRIAGE_TIMEOUT_MS)

    try {
      const resp = await fetch(`${apiUrl.replace(/\/$/, '')}/triage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
      clearTimeout(timeoutId)

      const took = (performance.now() - t0) / 1000

      if (!resp.ok) {
        const text = await resp.text()
        setError(`HTTP ${resp.status} · ${text || 'no body'}`)
        setLoading(false)
        return
      }

      const data = await resp.json()
      setResult(data)
      setFinalElapsed(took)
      setActiveTab('postmortem')
    } catch (e) {
      clearTimeout(timeoutId)
      const msg = (e as Error).message
      if (msg.includes('aborted')) {
        setError(
          `Request timed out after ${TRIAGE_TIMEOUT_MS / 1000}s. Modal cold start; try again.`,
        )
      } else if (msg.toLowerCase().includes('failed to fetch')) {
        setError(
          `Could not reach ${apiUrl}. Is the API port-forward running?
  kubectl -n sentinelops port-forward svc/sentinelops-api-microservice 8001:80`,
        )
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative z-10 min-h-screen flex flex-col">
      <Header apiUrl={apiUrl} onApiUrlChange={setApiUrl} />

      <main className="flex-1 mx-auto w-full max-w-7xl px-6 py-10 lg:py-14">
        <div className="grid grid-cols-1 lg:grid-cols-[440px_1fr] gap-10 lg:gap-12">
          {/* ---- Left: alert form ---- */}
          <section className="space-y-6">
            <SectionHeader number="01" title="Alert payload" />

            <SampleSelector
              samples={SAMPLES}
              activeId={sampleId}
              onChange={setSampleId}
            />

            <div className="space-y-4">
              <Field label="Alert name">
                <input
                  type="text"
                  value={alertname}
                  onChange={(e) => setAlertname(e.target.value)}
                  className={inputClass + ' font-mono'}
                />
              </Field>

              <div className="grid grid-cols-[1fr_120px] gap-3">
                <Field label="Service">
                  <input
                    type="text"
                    value={service}
                    onChange={(e) => setService(e.target.value)}
                    className={inputClass + ' font-mono'}
                  />
                </Field>
                <Field label="Severity">
                  <SeveritySelect value={severity} onChange={setSeverity} />
                </Field>
              </div>

              <Field label="Summary">
                <textarea
                  value={summary}
                  onChange={(e) => setSummary(e.target.value)}
                  rows={2}
                  className={inputClass + ' resize-none'}
                />
              </Field>

              <Field label="Labels · JSON">
                <textarea
                  value={labelsText}
                  onChange={(e) => setLabelsText(e.target.value)}
                  rows={4}
                  className={inputClass + ' font-mono text-xs resize-none'}
                  spellCheck={false}
                />
              </Field>

              <button
                type="button"
                onClick={triage}
                disabled={loading}
                className="group relative w-full mt-2 px-4 py-2.5 bg-amber-500 hover:bg-amber-400 active:bg-amber-600 text-zinc-950 font-medium text-sm tracking-tight rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? 'Triaging…' : 'Triage alert'}
                <span className="ml-1 opacity-50 group-hover:opacity-100 group-hover:translate-x-0.5 inline-block transition">→</span>
              </button>

              <p className="text-[11px] text-zinc-500 leading-relaxed pt-1">
                First call after Modal scale-to-zero takes <span className="text-zinc-300">~3 min</span> (cold start, vLLM loads the 7B). Warm calls return in <span className="text-zinc-300">~30s</span>.
              </p>
            </div>
          </section>

          {/* ---- Right: result panel ---- */}
          <section className="space-y-6 min-w-0">
            <div className="flex items-baseline justify-between gap-4">
              <SectionHeader number="02" title="Triage result" />
              {finalElapsed != null && !loading && (
                <span className="font-mono text-xs text-zinc-500 tabular-nums">
                  completed · <span className="text-amber-500">{finalElapsed.toFixed(1)}s</span>
                </span>
              )}
            </div>

            {error && <ErrorState message={error} />}
            {!error && loading && <LoadingState elapsed={elapsed} />}
            {!error && !loading && !result && <EmptyState />}
            {!error && !loading && result && (
              <ResultTabs
                data={result}
                activeTab={activeTab}
                onTabChange={setActiveTab}
              />
            )}
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------
function Header({
  apiUrl,
  onApiUrlChange,
}: {
  apiUrl: string
  onApiUrlChange: (v: string) => void
}) {
  const [showSettings, setShowSettings] = useState(false)

  return (
    <header className="sticky top-0 z-20 border-b border-zinc-900 bg-zinc-950/80 backdrop-blur supports-[backdrop-filter]:bg-zinc-950/60">
      <div className="mx-auto max-w-7xl px-6 h-14 flex items-center justify-between">
        <div className="flex items-baseline gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse-soft" />
            <span className="font-semibold text-sm tracking-[0.18em] text-zinc-100">
              SENTINELOPS
            </span>
          </div>
          <span className="text-xs text-zinc-500 font-mono hidden sm:inline">
            v0.1 · mistral-7b-awq · 2,579 chunks
          </span>
        </div>

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/ayushgupta07xx/sentinelops"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-zinc-400 hover:text-zinc-100 transition"
          >
            GitHub
          </a>
          <span className="text-zinc-700">·</span>
          <a
            href="https://huggingface.co/ayushgupta7777/sentinelops-mistral7b-awq"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-zinc-400 hover:text-zinc-100 transition"
          >
            Model
          </a>
          <span className="text-zinc-700">·</span>
          <button
            onClick={() => setShowSettings((v) => !v)}
            className="text-xs text-zinc-400 hover:text-zinc-100 transition"
          >
            Settings
          </button>
        </div>
      </div>
      {showSettings && (
        <div className="border-t border-zinc-900 bg-zinc-950">
          <div className="mx-auto max-w-7xl px-6 py-3 flex items-center gap-3">
            <label className="text-xs text-zinc-500 font-mono">API_URL</label>
            <input
              value={apiUrl}
              onChange={(e) => onApiUrlChange(e.target.value)}
              className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-xs font-mono text-zinc-200 focus:border-amber-500/50"
            />
          </div>
        </div>
      )}
    </header>
  )
}

// ---------------------------------------------------------------------------
// Section header (numbered)
// ---------------------------------------------------------------------------
function SectionHeader({ number, title }: { number: string; title: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-xs font-mono text-amber-500 tabular-nums">
        {number}
      </span>
      <h2 className="text-base font-medium text-zinc-100 tracking-tight">
        {title}
      </h2>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sample selector — segmented row of cards
// ---------------------------------------------------------------------------
function SampleSelector({
  samples,
  activeId,
  onChange,
}: {
  samples: Sample[]
  activeId: string
  onChange: (id: string) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {samples.map((s) => {
        const active = s.id === activeId
        return (
          <button
            key={s.id}
            onClick={() => onChange(s.id)}
            className={
              'text-left px-3 py-2.5 rounded border transition ' +
              (active
                ? 'bg-amber-500/5 border-amber-500/40 ring-1 ring-amber-500/20'
                : 'bg-zinc-900/40 border-zinc-800 hover:border-zinc-700')
            }
          >
            <div className="text-xs font-mono text-zinc-100 truncate">
              {s.title}
            </div>
            <div
              className={
                'text-[10px] mt-0.5 truncate ' +
                (active ? 'text-amber-500/80' : 'text-zinc-500')
              }
            >
              {s.subtitle}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Form field wrapper
// ---------------------------------------------------------------------------
function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  )
}

const inputClass =
  'w-full bg-zinc-900/50 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-amber-500/50 focus:bg-zinc-900 transition'

// ---------------------------------------------------------------------------
// Severity select
// ---------------------------------------------------------------------------
function SeveritySelect({
  value,
  onChange,
}: {
  value: Severity
  onChange: (v: Severity) => void
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as Severity)}
      className={inputClass + ' font-mono cursor-pointer'}
    >
      <option value="P0">P0</option>
      <option value="P1">P1</option>
      <option value="P2">P2</option>
      <option value="P3">P3</option>
    </select>
  )
}

// ---------------------------------------------------------------------------
// Empty / Loading / Error states
// ---------------------------------------------------------------------------
function EmptyState() {
  return (
    <div className="rounded border border-dashed border-zinc-800 px-6 py-16 text-center">
      <div className="text-sm text-zinc-400">No triage yet</div>
      <div className="text-xs text-zinc-600 mt-1.5 font-mono">
        Pick a scenario · click <span className="text-zinc-400">Triage alert</span>
      </div>
    </div>
  )
}

function LoadingState({ elapsed }: { elapsed: number }) {
  const phase =
    elapsed < 5
      ? 'Connecting'
      : elapsed < 15
        ? 'Retrieving runbooks'
        : elapsed < 25
          ? 'Reranking · BGE cross-encoder'
          : elapsed < 60
            ? 'Generating draft · Mistral-7B'
            : elapsed < 180
              ? 'Modal cold start · loading 7B weights'
              : 'Still waiting · vLLM warmup'

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/30 px-6 py-12 text-center animate-fade-in">
      <div className="font-mono text-4xl font-medium text-amber-500 tabular-nums tracking-tightest">
        {elapsed.toFixed(1)}
        <span className="text-base text-zinc-600 ml-1">s</span>
      </div>
      <div className="mt-3 text-sm text-zinc-300">{phase}</div>
      <div className="mt-1.5 text-[11px] text-zinc-600 font-mono">
        warm ~30s · cold ~180s
      </div>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-500/30 bg-red-500/5 px-4 py-3 animate-fade-in">
      <div className="text-xs uppercase tracking-[0.12em] text-red-400 font-medium">
        Error
      </div>
      <pre className="mt-1.5 text-xs text-red-300/90 font-mono whitespace-pre-wrap break-words">
        {message}
      </pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Result tabs
// ---------------------------------------------------------------------------
function ResultTabs({
  data,
  activeTab,
  onTabChange,
}: {
  data: any
  activeTab: TabId
  onTabChange: (id: TabId) => void
}) {
  const postmortem = extractPostmortem(data)
  const contexts = extractContexts(data)
  const trace = extractTrace(data)

  const tabs: Array<{ id: TabId; label: string; count?: number }> = [
    { id: 'postmortem', label: 'Postmortem' },
    { id: 'evidence', label: 'Evidence', count: contexts.length },
    { id: 'trace', label: 'Tool trace', count: trace.length },
    { id: 'raw', label: 'Raw' },
  ]

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-6 border-b border-zinc-900">
        {tabs.map((t) => {
          const active = t.id === activeTab
          return (
            <button
              key={t.id}
              onClick={() => onTabChange(t.id)}
              className={
                'relative pb-3 text-sm transition ' +
                (active
                  ? 'text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-300')
              }
            >
              {t.label}
              {t.count != null && (
                <span className="ml-1.5 text-[10px] font-mono text-zinc-600 tabular-nums">
                  {t.count}
                </span>
              )}
              {active && (
                <span className="absolute left-0 right-0 -bottom-px h-px bg-amber-500" />
              )}
            </button>
          )
        })}
      </div>

      <div className="pt-6 min-h-[260px]">
        {activeTab === 'postmortem' && <PostmortemTab text={postmortem} />}
        {activeTab === 'evidence' && <EvidenceTab contexts={contexts} />}
        {activeTab === 'trace' && <TraceTab steps={trace} />}
        {activeTab === 'raw' && <RawTab data={data} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Postmortem tab
// ---------------------------------------------------------------------------
function PostmortemTab({ text }: { text: string | null }) {
  if (!text)
    return (
      <p className="text-sm text-zinc-500">
        No <code className="font-mono text-amber-500/80">postmortem</code> field in response. Check the Raw tab.
      </p>
    )
  return (
    <pre className="font-mono text-[13px] leading-relaxed text-zinc-200 whitespace-pre-wrap break-words">
      {text}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Evidence tab — retrieved contexts as cards
// ---------------------------------------------------------------------------
function EvidenceTab({ contexts }: { contexts: any[] }) {
  if (!contexts.length)
    return (
      <p className="text-sm text-zinc-500">
        No retrieved contexts in response.
      </p>
    )
  return (
    <div className="space-y-3">
      {contexts.map((c, i) => (
        <details
          key={i}
          className="group rounded border border-zinc-800 bg-zinc-900/30 open:bg-zinc-900/60"
        >
          <summary className="cursor-pointer list-none px-4 py-2.5 flex items-baseline gap-3 hover:bg-zinc-900/40 transition">
            <span className="font-mono text-xs text-amber-500/70 tabular-nums">
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className="font-mono text-sm text-zinc-200 truncate flex-1">
              {extractTitle(c, i + 1)}
            </span>
            {typeof c?.rerank_score === 'number' && (
              <span className="font-mono text-[10px] text-amber-500/80 tabular-nums shrink-0">
                {c.rerank_score.toFixed(3)}
              </span>
            )}
            {c?.source_type && (
              <span className="text-[10px] text-zinc-500 px-1.5 py-0.5 rounded border border-zinc-800 font-mono uppercase tracking-wider shrink-0">
                {c.source_type}
              </span>
            )}
          </summary>
          <div className="px-4 pb-3 pt-1 border-t border-zinc-900">
            <pre className="font-mono text-xs leading-relaxed text-zinc-300 whitespace-pre-wrap break-words">
              {extractText(c)}
            </pre>
          </div>
        </details>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Trace tab — vertical timeline
// ---------------------------------------------------------------------------
function TraceTab({ steps }: { steps: any[] }) {
  if (!steps.length)
    return <p className="text-sm text-zinc-500">No tool trace in response.</p>
  return (
    <div className="relative pl-6">
      {steps.map((s, i) => {
        const last = i === steps.length - 1
        const name = extractStepName(s, i + 1)
        const isObj = typeof s === 'object' && s !== null
        const detail = isObj ? (s as any).detail : null
        const meta = isObj ? (s as any).meta : null
        return (
          <div key={i} className="relative pb-5 last:pb-0">
            {!last && (
              <span className="absolute left-[-15px] top-3 bottom-0 w-px bg-zinc-800" />
            )}
            <span className="absolute left-[-19px] top-1.5 w-2 h-2 rounded-full bg-amber-500 ring-2 ring-zinc-950" />
            <div className="flex items-baseline gap-2.5">
              <div className="font-mono text-sm text-zinc-100">{name}</div>
              {meta && (
                <span className="text-[10px] text-zinc-500 px-1.5 py-0.5 rounded border border-zinc-800 font-mono uppercase tracking-wider">
                  {meta}
                </span>
              )}
            </div>
            {detail ? (
              <div className="mt-0.5 font-mono text-xs text-zinc-500 break-words">
                {detail}
              </div>
            ) : (
              isObj &&
              !detail && (
                <pre className="mt-1 font-mono text-[11px] leading-relaxed text-zinc-500 whitespace-pre-wrap break-words">
                  {JSON.stringify(s, null, 2)}
                </pre>
              )
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Raw tab — full JSON
// ---------------------------------------------------------------------------
function RawTab({ data }: { data: any }) {
  return (
    <pre className="font-mono text-[11px] leading-relaxed text-zinc-400 whitespace-pre-wrap break-words bg-zinc-900/30 border border-zinc-800 rounded p-4 overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------
function Footer() {
  return (
    <footer className="border-t border-zinc-900 mt-auto">
      <div className="mx-auto max-w-7xl px-6 h-12 flex items-center justify-between text-[11px] text-zinc-600 font-mono">
        <span>SentinelOps · Apache 2.0</span>
        <span>built solo · 5 weeks · ₹0 compute</span>
      </div>
    </footer>
  )
}
