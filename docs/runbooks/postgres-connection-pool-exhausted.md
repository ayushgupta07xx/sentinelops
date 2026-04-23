---
title: "Postgres connection pool exhausted or DB unreachable"
service: users-service, orders-service
severity: critical
alert_names:
  - (derived: spike in 5xx + pod events on postgres-postgresql-0, or pool-exhausted log line)
slo: availability, latency (both services blocked when shared Postgres is unhealthy)
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
users-service and orders-service share a single Postgres instance (`postgres-postgresql-0`, Bitnami chart in `observashop` namespace, databases: `users` and `orders`). When the app-side connection pool is exhausted (too many concurrent queries, slow queries blocking returns) or the DB pod is down, both services return 5xx. Shared Postgres means this is the highest-blast-radius failure mode.

## Symptoms
- Service logs contain `timeout acquiring connection from pool` or `ECONNREFUSED`.
- Both `UsersServiceErrorBudgetFastBurn` AND `OrdersServiceErrorBudgetFastBurn` may fire simultaneously — a strong signal of shared-Postgres failure.
- Readiness probes start failing (they check the DB), so pods go Unready without crashing.

## Diagnosis
1. Is the Postgres pod up?
   ```bash
   kubectl -n observashop get pod postgres-postgresql-0
   kubectl -n observashop describe pod postgres-postgresql-0 | tail -30
   kubectl -n observashop logs postgres-postgresql-0 --tail=100
   ```
2. Pool saturation (Node.js `pg` pool metric if exposed; otherwise proxy via query latency):
   ```promql
   histogram_quantile(0.99, sum by (le) (rate(db_query_duration_seconds_bucket[5m])))
   ```
   Sudden jump from <50ms to >1s usually means pool wait time dominates.
3. Long-running queries (use `postgres-postgresql-0` as the shell):
   ```bash
   kubectl -n observashop exec -it postgres-postgresql-0 -- \
     psql -U observashop -d users -c \
     "SELECT pid, now()-query_start AS duration, state, query FROM pg_stat_activity WHERE state != 'idle' AND now()-query_start > interval '5 seconds' ORDER BY duration DESC;"
   ```
   Repeat against database `orders`.
4. PV usage (Postgres PVC is 1 GiB — tight):
   ```bash
   kubectl -n observashop exec postgres-postgresql-0 -- df -h /bitnami/postgresql
   ```

## Remediation
1. **If DB pod is down:** `kubectl -n observashop describe pod postgres-postgresql-0` → follow `pod-not-ready.md`. Both services will 5xx until restored.
2. **If pool exhausted due to a blocking query:** cancel with `SELECT pg_cancel_backend(<pid>);` (prefer `pg_cancel` over `pg_terminate` first).
3. **If sustained load:** raise `max_connections` on Postgres (chart value) AND app-side pool size; scale app replicas cautiously (more replicas = more connections per DB).
4. **If PV full (1 GiB is easy to exceed):** see `disk-full.md` — Postgres refuses writes at 100%. PVC expansion needs StorageClass `allowVolumeExpansion: true`.
5. **If recent app deploy added a slow query:** `argocd app rollback <svc>-app`.
6. **Post-Docker-Desktop-restart gotcha:** moving Docker Desktop's disk image (as happened on Day 4) can corrupt PVC ownership. If Postgres pod fails with "Permission denied" after restart, apply the same fix used for Grafana: delete and recreate the PVC.

## Escalation
Postgres down >10 min → page data-platform on-call. Data corruption suspected → stop traffic before investigating.

## Related
- `users-service-errors.md`, `orders-service-errors.md` (paired burn is the signal)
- `disk-full.md`
- `pod-not-ready.md`
