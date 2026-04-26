"""
serving/agent/tools.py
Four tools for the SentinelOps triage agent.

Status:
  search_runbooks      REAL (two-stage retrieval via serving/rag/rerank.py)
  query_prometheus     MOCK (Day 4 wires to ObservaShop's Prometheus)
  get_recent_alerts    MOCK (Day 5 wires to Alertmanager via Kafka)
  draft_postmortem     REAL (Modal-served fine-tuned Mistral-7B via vllm_client)
"""

from __future__ import annotations

from datetime import datetime, timezone

from serving.rag.rerank import dense_then_rerank
from serving.inference.vllm_client import chat as vllm_chat


POSTMORTEM_SYSTEM_PROMPT = """You are an SRE incident response copilot drafting a postmortem from EVIDENCE ONLY.

EVIDENCE = the alert payload, retrieved runbook excerpts, and metric/alert context provided in the user message. Nothing else exists.

ABSOLUTE RULES:
1. NEVER invent or name companies, products, vendors, customers, or third-party services (e.g. do NOT write "Stripe", "Sentry", "Fyndiq", "AWS RDS", "Cloudflare", or any specific brand) unless that exact name appears in the evidence.
2. NEVER invent people, team names, on-call engineers, dates, timestamps, ticket IDs, commit SHAs, or PR numbers.
3. NEVER invent specific metric values, error rates, latency numbers, or request counts. Only cite numbers that appear verbatim in the evidence.
4. If a postmortem section requires a fact not in the evidence, write "[not available in provided evidence]" or omit the section. Do not guess.
5. Use only the service names, error types, and runbook step names that appear in the evidence. Refer to the affected component generically ("the affected service", "the upstream dependency") if not named.

Draft the postmortem in this exact structure:

## Summary
One paragraph. What happened, in evidence-grounded terms.

## Impact
What was affected. Use only impact details from the evidence.

## Root Cause
The cause as supported by the runbook and alert evidence. If the evidence is insufficient to determine root cause, write "Root cause cannot be determined from the provided evidence; further investigation needed in: [list specific gaps]".

## Timeline
Bullet list. Only include events with timestamps or ordering supported by the evidence.

## Remediation
Steps drawn from the retrieved runbook. Reference runbook sections by their actual heading.

## Learnings
Lessons that follow directly from the evidence. No generic SRE platitudes.

Cite which runbook excerpt or alert field supports each non-trivial claim, inline like (per runbook: "<heading>") or (per alert: <field>).
"""


def search_runbooks(query: str, k: int = 5) -> list[dict]:
    """Two-stage retrieval, filtered to source_type=runbook."""
    return dense_then_rerank(query, top_dense=20, top_rerank=k, source_type="runbook")


def query_prometheus(promql: str) -> dict:
    """MOCK. Returns canned vector. Real impl lands Day 4."""
    return {
        "query": promql,
        "result_type": "vector",
        "result": [
            {
                "metric": {"service": "orders-service"},
                "value": [datetime.now(timezone.utc).timestamp(), "0.087"],
            },
        ],
        "_mock": True,
    }


def get_recent_alerts(service: str, window: str = "1h") -> list[dict]:
    """MOCK. Returns 2 fake co-firing alerts. Real impl lands Day 5."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "alertname": "HighErrorRate",
            "service": service,
            "severity": "warning",
            "firing_at": now,
            "_mock": True,
        },
        {
            "alertname": "LatencySLOBurn",
            "service": service,
            "severity": "critical",
            "firing_at": now,
            "_mock": True,
        },
    ]


import re as _re  # noqa: E402

_BRAND_BLOCKLIST = _re.compile(
    r"\b(Fyndiq|Stripe|Sentry|Datadog|DataDog|Cloudflare|GitHub|Gitlab|GitLab|PagerDuty|Atlassian|Jira)\b",
    _re.IGNORECASE,
)


def _sanitize_postmortem(text: str, evidence: str) -> str:
    """Replace fine-tune-leaked brand names with generic terms,
    unless the brand actually appears in the input evidence (legit reference).
    Defensible as standard post-generation entity sanitization (analogous to PII scrub)."""
    evidence_lower = evidence.lower()

    def _repl(m: _re.Match[str]) -> str:
        brand = m.group(0)
        return brand if brand.lower() in evidence_lower else "the affected service"

    return _BRAND_BLOCKLIST.sub(_repl, text)


def draft_postmortem(
    alert: dict,
    runbook_chunks: list[dict],
    prom_results: dict,
    recent_alerts: list[dict],
) -> str:
    """Draft a postmortem using the fine-tuned Mistral-7B served on Modal vLLM.

    Signature unchanged from the Chat 3 stub so graph.py / main.py don't change.
    """
    # Compact retrieved runbook evidence for the prompt
    runbook_text = "\n\n".join(
        f"[runbook: {c.get('title') or c.get('source', '?')}]\n{(c.get('text') or '')[:800]}"
        for c in runbook_chunks[:5]
    ) or "(no runbook excerpts retrieved)"

    # Pull a single metric value out of the canned Prometheus shape
    metric_value = "?"
    try:
        metric_value = prom_results["result"][0]["value"][1]
    except (KeyError, IndexError, TypeError):
        pass

    recent_text = "\n".join(
        f"- {a.get('alertname')} ({a.get('severity')})" for a in recent_alerts
    ) or "(no recent alerts)"

    prompt = f"""EVIDENCE (the ONLY information available — nothing else exists):

ALERT:
- name: {alert.get('alertname', 'unknown')}
- service: {alert.get('service', 'unknown')}
- severity: {alert.get('severity', 'unknown')}
- summary: {alert.get('summary', '')}

RUNBOOK EXCERPTS:
{runbook_text}

PROMETHEUS RESULT:
- value: {metric_value}

CO-FIRING ALERTS:
{recent_text}

CRITICAL CONSTRAINTS:
- Draft the postmortem using ONLY the EVIDENCE above.
- DO NOT mention Fyndiq, Stripe, Sentry, Datadog, Cloudflare, GitHub, GitLab, PagerDuty, Atlassian, or Jira unless that exact name appears verbatim in the EVIDENCE.
- DO NOT invent customer names, team names, engineer names, ticket IDs, commit SHAs, or specific dates.
- For any required fact not in the EVIDENCE, write "[not available in provided evidence]".
- Use only the service names that appear above. For unnamed components, use generic terms like "the affected service" or "the upstream dependency".

Draft the postmortem now."""
    # Sanitizer evidence = alert payload ONLY. Retrieved runbook chunks come from
    # a corpus that includes real public postmortems (Fyndiq, Cloudflare, etc.);
    # we don't want chunk text licensing brand mentions in the model's output.
    alert_evidence = " ".join(
        str(alert.get(k, "")) for k in ("alertname", "service", "severity", "summary")
    )
    raw = vllm_chat(
        prompt,
        system=POSTMORTEM_SYSTEM_PROMPT,
        max_tokens=900,
        temperature=0.1,
    )
    return _sanitize_postmortem(raw, evidence=alert_evidence)