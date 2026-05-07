"""
streaming/alert_consumer/consumer.py

Kafka consumer: reads `alerts`, transforms each Alertmanager alert into the
SentinelOps `/triage` payload, POSTs to the API, and publishes the response
to the `triage_results` topic.

Run (from repo root, venv active):
    python -m streaming.alert_consumer.consumer

Env:
    KAFKA_BOOTSTRAP        default localhost:9092
    ALERTS_TOPIC           default alerts
    RESULTS_TOPIC          default triage_results
    SENTINELOPS_API_URL    default http://localhost:8000
                           (port-forward: kubectl -n sentinelops
                            port-forward svc/sentinelops-api-microservice 8000:80)
    TRIAGE_TIMEOUT_S       default 180  (Modal cold-start + agent + LLM)
"""
from __future__ import annotationshand

import asyncio
import json
import logging
import os
import signal

import httpx
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from streaming.alert_consumer.transform import alertmanager_to_triage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alert_consumer")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
ALERTS_TOPIC = os.getenv("ALERTS_TOPIC", "alerts")
RESULTS_TOPIC = os.getenv("RESULTS_TOPIC", "triage_results")
API_URL = os.getenv("SENTINELOPS_API_URL", "http://localhost:8000").rstrip("/")
TRIAGE_TIMEOUT_S = float(os.getenv("TRIAGE_TIMEOUT_S", "180"))
GROUP_ID = os.getenv("CONSUMER_GROUP", "sentinelops-alert-consumer")


async def _process_one(client: httpx.AsyncClient, raw: bytes) -> dict:
    """Transform → POST /triage → build result dict for `triage_results`."""
    am_alert = json.loads(raw)
    payload = alertmanager_to_triage(am_alert)
    log.info(
        "triage start alertname=%s service=%s severity=%s",
        payload["alertname"],
        payload["service"],
        payload["severity"],
    )
    r = await client.post(f"{API_URL}/triage", json=payload)
    r.raise_for_status()
    result = r.json()
    log.info(
        "triage done  alertname=%s draft_len=%d chunks=%d",
        payload["alertname"],
        len(result.get("draft", "")),
        len(result.get("runbook_chunks", [])),
    )
    return {
        "input_alert": payload,
        "triage": {
            "draft": result.get("draft", ""),
            "runbook_chunks": result.get("runbook_chunks", []),
            "prom_results": result.get("prom_results", {}),
            "recent_alerts": result.get("recent_alerts", []),
        },
    }


async def run() -> None:
    consumer = AIOKafkaConsumer(
        ALERTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",   # friendly for first-run dev
        enable_auto_commit=True,
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await consumer.start()
    await producer.start()
    log.info(
        "ready bootstrap=%s in=%s out=%s api=%s group=%s",
        KAFKA_BOOTSTRAP, ALERTS_TOPIC, RESULTS_TOPIC, API_URL, GROUP_ID,
    )

    stop = asyncio.Event()

    def _on_signal(*_):
        log.info("shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, _on_signal)

    try:
        async with httpx.AsyncClient(timeout=TRIAGE_TIMEOUT_S) as client:
            while not stop.is_set():
                # getmany with a short timeout lets us check `stop` between batches.
                batch = await consumer.getmany(timeout_ms=1000, max_records=1)
                for _tp, msgs in batch.items():
                    for msg in msgs:
                        try:
                            out = await _process_one(client, msg.value)
                        except Exception as e:
                            log.exception("alert handling failed: %r", e)
                            out = {
                                "input_alert_raw": msg.value.decode(
                                    "utf-8", errors="replace"
                                ),
                                "error_type": type(e).__name__,
                                "error": repr(e),
                            }
                        await producer.send_and_wait(
                            RESULTS_TOPIC, json.dumps(out).encode("utf-8")
                        )
    finally:
        await consumer.stop()
        await producer.stop()
        log.info("clean shutdown")


if __name__ == "__main__":
    asyncio.run(run())
