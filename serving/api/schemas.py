"""
serving/api/schemas.py
Pydantic v2 models for the SentinelOps API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    alertname: str = Field(..., examples=["OrdersServiceErrorBudgetBurning"])
    service: str = Field(..., examples=["orders-service"])
    severity: str = Field("warning", examples=["critical", "warning"])
    summary: str = ""
    promql: str | None = None
    labels: dict = {}


class TriageResponse(BaseModel):
    alert: dict
    runbook_chunks: list[dict]
    prom_results: dict
    recent_alerts: list[dict]
    draft: str


class DraftRequest(BaseModel):
    alert: dict
    runbook_chunks: list[dict] = []
    prom_results: dict = {}
    recent_alerts: list[dict] = []


class DraftResponse(BaseModel):
    draft: str
