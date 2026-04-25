"""
serving/api/smoke.py
Hits /healthz, /triage, /draft-postmortem, and /stream against a running server.

Usage (in a SECOND terminal, server running on :8000):
    python -m serving.api.smoke
"""

from __future__ import annotations

import asyncio
import json
import urllib.request

import websockets

BASE = "http://localhost:8000"
WS_URL = "ws://localhost:8000/stream"

ALERT = {
    "alertname": "OrdersServiceErrorBudgetBurning",
    "service": "orders-service",
    "severity": "critical",
    "summary": "5xx error rate spiked to 8% after deploy v2.3.1",
}


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


async def _ws_test() -> None:
    print("\n--- WS /stream ---")
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"alert": ALERT}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            if msg.get("event") == "done":
                print("  done")
                break
            node = msg.get("node")
            partial_keys = list((msg.get("partial") or {}).keys())
            print(f"  node={node:20s} keys={partial_keys}")


def main() -> None:
    print("--- GET /healthz ---")
    print(" ", _get("/healthz"))

    print("\n--- POST /triage ---")
    r = _post("/triage", ALERT)
    print(f"  runbooks: {len(r['runbook_chunks'])}, top1={r['runbook_chunks'][0].get('title') or r['runbook_chunks'][0].get('source')}")
    print(f"  draft length: {len(r['draft'])} chars")

    print("\n--- POST /draft-postmortem ---")
    r2 = _post(
        "/draft-postmortem",
        {
            "alert": ALERT,
            "runbook_chunks": r["runbook_chunks"][:2],
            "prom_results": r["prom_results"],
            "recent_alerts": r["recent_alerts"],
        },
    )
    print(f"  draft length: {len(r2['draft'])} chars")

    asyncio.run(_ws_test())


if __name__ == "__main__":
    main()
