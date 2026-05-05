"""Prometheus metrics for SentinelOps serving layer.

Mounted at /metrics by serving/api/main.py.
Imported by api/main.py, agent/tools.py, rag/rerank.py to record values.
"""
from prometheus_client import Counter, Gauge, Histogram

# --- LLM serving metrics ---------------------------------------------------

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "End-to-end LLM request latency (Modal vLLM round-trip).",
    labelnames=("endpoint",),
    buckets=(0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60),
)

llm_time_to_first_token_seconds = Histogram(
    "llm_time_to_first_token_seconds",
    "Time from request sent to first token received (streaming only).",
    labelnames=("endpoint",),
    buckets=(0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10),
)

llm_tokens_per_second = Histogram(
    "llm_tokens_per_second",
    "Output token throughput per request (completion_tokens / generation_seconds).",
    labelnames=("endpoint",),
    buckets=(5, 10, 20, 40, 60, 80, 120, 200, 400),
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Cumulative USD cost of LLM inference, estimated per request from token counts.",
    labelnames=("model",),
)

# --- RAG metrics -----------------------------------------------------------

rag_cache_lookups_total = Counter(
    "rag_cache_lookups_total",
    "Total RAG retrieval cache lookups.",
)

rag_cache_hits_total = Counter(
    "rag_cache_hits_total",
    "RAG retrieval cache hits. cache_hit_ratio = rate(hits) / rate(lookups) in Grafana.",
)

rag_retrieval_precision_at_5 = Gauge(
    "rag_retrieval_precision_at_5",
    "Precision@5 from latest RAG eval pass (set by ragas suite, sampled).",
)

# --- Agent metrics ---------------------------------------------------------

agent_tool_call_total = Counter(
    "agent_tool_call_total",
    "LangGraph agent tool invocations.",
    labelnames=("tool", "outcome"),  # outcome: success | error
)

# --- Quality metric (sampled) ----------------------------------------------

hallucination_rate = Gauge(
    "hallucination_rate",
    "Hallucination rate from latest LLM-as-judge sampled grading (0=none, 1=all).",
)


def metrics_response():
    """Return (payload_bytes, content_type) for a Prometheus scrape.

    Use in a regular FastAPI route to avoid the 307 redirect that mounted
    ASGI sub-apps produce on /metrics → /metrics/.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return generate_latest(), CONTENT_TYPE_LATEST

# --- Helper: record a complete LLM call in one shot --------------------------

def record_llm_call(
    model: str,
    endpoint: str,
    completion_text: str,
    duration_seconds: float,
) -> None:
    """Record duration, output throughput, and estimated cost for one LLM call.

    Token count is char-based estimate (~4 chars/token, ±15%); replace with
    vLLM-reported usage when streaming tokens lands. Cost rate pinned to
    Modal T4 throughput (~$3.3e-6/output token at ~50 tok/s).
    """
    completion_tokens = max(1, len(completion_text) // 4)
    llm_request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)
    if duration_seconds > 0:
        llm_tokens_per_second.labels(endpoint=endpoint).observe(
            completion_tokens / duration_seconds
        )
    llm_cost_usd_total.labels(model=model).inc(completion_tokens * 3.3e-6)