"""
serving/api/main.py

FastAPI service for SentinelOps.

Endpoints:
  GET  /healthz            liveness probe
  POST /triage             full agent workflow on an alert payload
  POST /draft-postmortem   direct postmortem draft with caller-provided context
  WS   /stream             streams agent state transitions per-node

Run dev server (from repo root, venv active):
    uvicorn serving.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from serving.agent.graph import get_app
from serving.agent.tools import draft_postmortem
from serving.api.schemas import (
    AlertPayload,
    DraftRequest,
    DraftResponse,
    TriageResponse,
)

app = FastAPI(title="SentinelOps", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageResponse)
async def triage(alert: AlertPayload) -> TriageResponse:
    # graph.invoke is sync (sentence_transformers + Qdrant calls are blocking);
    # run in a thread so the event loop stays responsive.
    final = await asyncio.to_thread(get_app().invoke, {"alert": alert.model_dump()})
    return TriageResponse(
        alert=final["alert"],
        runbook_chunks=final.get("runbook_chunks", []),
        prom_results=final.get("prom_results", {}),
        recent_alerts=final.get("recent_alerts", []),
        draft=final.get("draft", ""),
    )


@app.post("/draft-postmortem", response_model=DraftResponse)
async def draft_endpoint(req: DraftRequest) -> DraftResponse:
    text = await asyncio.to_thread(
        draft_postmortem,
        req.alert,
        req.runbook_chunks,
        req.prom_results,
        req.recent_alerts,
    )
    return DraftResponse(draft=text)


@app.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Streams agent state transitions per-node.

    Day 3: emits one event per LangGraph node completion (search, prom, alerts, draft).
    Day 4: real token streaming arrives once Modal-served vLLM is wired (the draft
    node will yield tokens from vLLM's OpenAI-compatible stream endpoint instead
    of a single string).
    """
    await ws.accept()
    try:
        msg = await ws.receive_json()
        alert = msg.get("alert", {})
        graph_app = get_app()
        async for event in graph_app.astream({"alert": alert}):
            # event shape: {node_name: partial_state_dict}
            for node, partial in event.items():
                await ws.send_json(
                    {"event": "node", "node": node, "partial": _jsonable(partial)}
                )
        await ws.send_json({"event": "done"})
    except WebSocketDisconnect:
        return


def _jsonable(obj: Any) -> Any:
    """Best-effort coerce to JSON-safe (LangGraph state is usually fine already)."""
    return json.loads(json.dumps(obj, default=str))
