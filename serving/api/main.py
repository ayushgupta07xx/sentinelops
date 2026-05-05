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

# Load .env (MODAL_VLLM_BASE_URL / MODAL_VLLM_API_KEY) BEFORE any module that reads them.
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect

from serving.agent.graph import get_app
from serving.agent.tools import draft_postmortem
from serving.api.metrics import (
    llm_time_to_first_token_seconds,
    metrics_response,
    record_llm_call,
)
from serving.api.schemas import (
    AlertPayload,
    DraftRequest,
    DraftResponse,
    TriageResponse,
)

app = FastAPI(title="SentinelOps", version="0.1.0")


@app.get("/metrics")
def metrics() -> Response:
    payload, content_type = metrics_response()
    return Response(content=payload, media_type=content_type)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageResponse)
async def triage(alert: AlertPayload) -> TriageResponse:
    # graph.invoke is sync (sentence_transformers + Qdrant calls are blocking);
    # run in a thread so the event loop stays responsive.
    t0 = time.perf_counter()
    final = await asyncio.to_thread(get_app().invoke, {"alert": alert.model_dump()})
    record_llm_call(
        model="sentinelops-mistral7b",
        endpoint="triage",
        completion_text=final.get("draft", ""),
        duration_seconds=time.perf_counter() - t0,
    )
    return TriageResponse(
        alert=final["alert"],
        runbook_chunks=final.get("runbook_chunks", []),
        prom_results=final.get("prom_results", {}),
        recent_alerts=final.get("recent_alerts", []),
        draft=final.get("draft", ""),
    )


@app.post("/draft-postmortem", response_model=DraftResponse)
async def draft_endpoint(req: DraftRequest) -> DraftResponse:
    t0 = time.perf_counter()
    text = await asyncio.to_thread(
        draft_postmortem,
        req.alert,
        req.runbook_chunks,
        req.prom_results,
        req.recent_alerts,
    )
    record_llm_call(
        model="sentinelops-mistral7b",
        endpoint="draft-postmortem",
        completion_text=text,
        duration_seconds=time.perf_counter() - t0,
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
        t0 = time.perf_counter()
        first_event_seen = False
        async for event in graph_app.astream({"alert": alert}):
            if not first_event_seen:
                llm_time_to_first_token_seconds.labels(endpoint="stream").observe(
                    time.perf_counter() - t0
                )
                first_event_seen = True
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
