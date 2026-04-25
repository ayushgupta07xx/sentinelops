"""
serving/agent/graph.py
LangGraph state machine for incident triage.

v0 is deterministic-sequential:
  START -> search_runbooks -> query_prometheus -> get_recent_alerts -> draft_postmortem -> END

v1 (Day 4+) replaces the chain with an LLM-driven tool router using the
Modal-served Mistral-7B QLoRA endpoint. State shape stays the same.

Smoke test:
    python -m serving.agent.graph
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from serving.agent.tools import (
    draft_postmortem,
    get_recent_alerts,
    query_prometheus,
    search_runbooks,
)


class TriageState(TypedDict, total=False):
    alert: dict
    runbook_chunks: list[dict]
    prom_results: dict
    recent_alerts: list[dict]
    draft: str


# -----------------------------------------------------------------------------
# Nodes (each returns a partial state dict that LangGraph merges)
# -----------------------------------------------------------------------------
def _node_search(state: TriageState) -> dict:
    alert = state["alert"]
    query = " ".join(
        str(alert.get(k, "")) for k in ("alertname", "service", "summary")
    ).strip()
    return {"runbook_chunks": search_runbooks(query, k=5)}


def _node_prom(state: TriageState) -> dict:
    alert = state["alert"]
    promql = alert.get("promql") or (
        f'rate(http_requests_total{{service="{alert.get("service", "")}",status=~"5.."}}[5m])'
    )
    return {"prom_results": query_prometheus(promql)}


def _node_alerts(state: TriageState) -> dict:
    return {"recent_alerts": get_recent_alerts(state["alert"].get("service", ""))}


def _node_draft(state: TriageState) -> dict:
    return {
        "draft": draft_postmortem(
            alert=state["alert"],
            runbook_chunks=state.get("runbook_chunks", []),
            prom_results=state.get("prom_results", {}),
            recent_alerts=state.get("recent_alerts", []),
        )
    }


# -----------------------------------------------------------------------------
# Graph build (compiled once, cached)
# -----------------------------------------------------------------------------
def build_graph():
    g = StateGraph(TriageState)
    g.add_node("search_runbooks", _node_search)
    g.add_node("query_prometheus", _node_prom)
    g.add_node("get_recent_alerts", _node_alerts)
    g.add_node("draft_postmortem", _node_draft)
    g.add_edge(START, "search_runbooks")
    g.add_edge("search_runbooks", "query_prometheus")
    g.add_edge("query_prometheus", "get_recent_alerts")
    g.add_edge("get_recent_alerts", "draft_postmortem")
    g.add_edge("draft_postmortem", END)
    return g.compile()


_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------
SAMPLE_ALERT = {
    "alertname": "OrdersServiceErrorBudgetBurning",
    "service": "orders-service",
    "severity": "critical",
    "summary": "5xx error rate spiked to 8% after deploy v2.3.1",
}


def _smoke() -> None:
    final = get_app().invoke({"alert": SAMPLE_ALERT})

    print("=== runbook_chunks (top-3) ===")
    for i, c in enumerate(final["runbook_chunks"][:3], 1):
        title = c.get("title") or c.get("source")
        print(f"  {i}. rerank={c['rerank_score']:+.3f}  {title}")

    print("\n=== prom_results ===")
    print(f"  query: {final['prom_results']['query']}")
    print(f"  value: {final['prom_results']['result'][0]['value'][1]}  (mock)")

    print("\n=== recent_alerts ===")
    for a in final["recent_alerts"]:
        print(f"  - {a['alertname']} ({a['severity']})  (mock)")

    print("\n=== draft ===")
    print(final["draft"])


if __name__ == "__main__":
    _smoke()
