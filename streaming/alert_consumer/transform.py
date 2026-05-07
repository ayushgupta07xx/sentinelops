"""
streaming/alert_consumer/transform.py

Map a single Alertmanager v4 alert (an entry from `alerts[]`) to the
SentinelOps API `AlertPayload` shape.

Field-name discipline: API expects `alertname` (one word). Pydantic enforces
this — `alert_name` will return 422.
"""
from __future__ import annotations

from typing import Any


def alertmanager_to_triage(am_alert: dict[str, Any]) -> dict[str, Any]:
    """Convert one Alertmanager alert dict to AlertPayload kwargs."""
    labels = am_alert.get("labels") or {}
    annotations = am_alert.get("annotations") or {}

    # Prefer `summary` annotation; fall back to `description`.
    summary = annotations.get("summary") or annotations.get("description") or ""

    # Service: explicit `service` label, else common Prometheus `job` label,
    # else fingerprint-friendly fallback so the API still accepts the payload.
    service = labels.get("service") or labels.get("job") or "unknown"

    return {
        "alertname": labels.get("alertname", "Unknown"),
        "service": service,
        "severity": labels.get("severity", "warning"),
        "summary": summary,
        # promql is optional in AlertPayload; pull from annotation if Alertmanager
        # was configured to inject the originating expression.
        "promql": annotations.get("promql"),
        "labels": labels,
    }
