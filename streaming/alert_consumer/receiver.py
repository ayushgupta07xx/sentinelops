"""
streaming/alert_consumer/receiver.py

FastAPI Alertmanager webhook receiver. Accepts Alertmanager v4 POST payload,
publishes each alert in the batch to Kafka topic `alerts`.

Run (from repo root, venv active):
    uvicorn streaming.alert_consumer.receiver:app --port 9000

Env:
    KAFKA_BOOTSTRAP   default localhost:9092
    ALERTS_TOPIC      default alerts
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alert_receiver")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
ALERTS_TOPIC = os.getenv("ALERTS_TOPIC", "alerts")

producer: AIOKafkaProducer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    log.info("producer connected bootstrap=%s topic=%s", KAFKA_BOOTSTRAP, ALERTS_TOPIC)
    try:
        yield
    finally:
        await producer.stop()
        log.info("producer stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "topic": ALERTS_TOPIC}


@app.post("/webhook")
async def webhook(req: Request):
    """Alertmanager webhook target. Splits the batch into one Kafka message per alert."""
    body = await req.json()
    alerts = body.get("alerts", []) or []
    published = 0
    for alert in alerts:
        # send_and_wait so we only 200 after the broker acks every alert.
        await producer.send_and_wait(  # type: ignore[union-attr]
            ALERTS_TOPIC,
            json.dumps(alert).encode("utf-8"),
        )
        published += 1
    log.info(
        "webhook received=%d published=%d status=%s",
        len(alerts),
        published,
        body.get("status"),
    )
    return {"received": len(alerts), "published": published}
