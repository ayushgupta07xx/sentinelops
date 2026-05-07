# streaming/alert_consumer

Alertmanager → Redpanda → consumer → /triage → `triage_results`.

```
Alertmanager  --POST /webhook-->  receiver.py  --kafka(alerts)-->  consumer.py
                                                                        |
                                                                  POST /triage
                                                                        |
                                                                        v
                                                            kafka(triage_results)
```

## Topics

Pre-create (idempotent — safe to re-run):

```bash
docker exec sentinelops-redpanda rpk topic create alerts triage_results
docker exec sentinelops-redpanda rpk topic list
```

## Local end-to-end demo

Four WSL terminals, all from `~/sentinelops` with `.venv` active.

**T1 — port-forward the API** (consumer reaches the in-cluster service this way):
```bash
kubectl port-forward svc/sentinelops-api-microservice -n sentinelops 8000:80
```

**T2 — receiver:**
```bash
uvicorn streaming.alert_consumer.receiver:app --port 9000
```

**T3 — consumer:**
```bash
python -m streaming.alert_consumer.consumer
```

**T4 — fire a synthetic alert + tail the result topic:**
```bash
# Fire one Alertmanager-shaped POST
curl -s -X POST http://localhost:9000/webhook \
  -H "Content-Type: application/json" \
  -d @streaming/alert_consumer/sample_alertmanager.json

# Watch the answer land (will block until consumer publishes)
docker exec -it sentinelops-redpanda rpk topic consume triage_results --num 1
```

Expect ~10–60s end-to-end depending on Modal warmth.

## Env knobs

| var                  | default                  | purpose                          |
|----------------------|--------------------------|----------------------------------|
| `KAFKA_BOOTSTRAP`    | `localhost:9092`         | Redpanda EXTERNAL listener       |
| `ALERTS_TOPIC`       | `alerts`                 | input topic                      |
| `RESULTS_TOPIC`      | `triage_results`         | output topic                     |
| `SENTINELOPS_API_URL`| `http://localhost:8000`  | API base (port-fwd or local)     |
| `TRIAGE_TIMEOUT_S`   | `180`                    | covers Modal cold start          |
| `CONSUMER_GROUP`     | `sentinelops-alert-consumer` | Kafka consumer group         |

## Notes

- `auto_offset_reset="earliest"` so first-run dev sees existing messages.
  After the group commits, this only matters on a fresh group_id.
- Field-name discipline: API expects `alertname` (one word). The transform
  enforces this — Alertmanager already uses the same convention.
- On any handling error the consumer still publishes a `{error, input_alert_raw}`
  doc to `triage_results` so failures are visible in the demo, not silent.
