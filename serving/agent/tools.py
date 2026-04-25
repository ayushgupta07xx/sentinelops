"""
serving/agent/tools.py
Four tools for the SentinelOps triage agent.

Status:
  search_runbooks      REAL (two-stage retrieval via serving/rag/rerank.py)
  query_prometheus     MOCK (Day 4 wires to ObservaShop's Prometheus)
  get_recent_alerts    MOCK (Day 5 wires to Alertmanager via Kafka)
  draft_postmortem     STUB (Day 4 wires to Modal-served Mistral-7B QLoRA)
"""

from __future__ import annotations

from datetime import datetime, timezone

from serving.rag.rerank import dense_then_rerank


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


def draft_postmortem(
    alert: dict,
    runbook_chunks: list[dict],
    prom_results: dict,
    recent_alerts: list[dict],
) -> str:
    """STUB. Templated postmortem so the pipeline shape is testable end-to-end.
    Day 4: replace this body with a Modal vLLM call to the fine-tuned model."""
    rb_titles = (
        "\n".join(f"  - {c.get('title') or c.get('source')}" for c in runbook_chunks[:3])
        or "  (none)"
    )
    alerts_str = (
        "\n".join(f"  - {a['alertname']} ({a['severity']})" for a in recent_alerts)
        or "  (none)"
    )
    metric_value = "?"
    try:
        metric_value = prom_results["result"][0]["value"][1]
    except (KeyError, IndexError, TypeError):
        pass

    return f"""# Incident Draft (STUB — Modal wiring pending Day 4)

## Alert
- name: {alert.get('alertname', 'unknown')}
- service: {alert.get('service', 'unknown')}
- severity: {alert.get('severity', 'unknown')}
- summary: {alert.get('summary', '')}

## Relevant runbooks (top-3)
{rb_titles}

## Recent metric reading
{metric_value}

## Co-firing alerts
{alerts_str}

## Hypothesis
[Modal-served Mistral-7B QLoRA model will write this section]
"""
