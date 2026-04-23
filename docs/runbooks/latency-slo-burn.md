---
title: "Latency SLO burning (users-service or orders-service)"
service: users-service, orders-service
severity: critical
alert_names:
  - UsersServiceLatencySLOFastBurn
  - OrdersServiceLatencySLOFastBurn
slo: "latency_p999 (users <250ms, orders <500ms -- higher because orders fans out to 2 upstreams)"
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
Too many requests are exceeding the latency threshold. The SLO tracks the *fraction* of slow requests, not p99 directly — it fires when that fraction crosses 0.144% (burn rate 14.4 × 0.001 error budget) over both 5m and 1h windows.

## Symptoms
- `UsersServiceLatencySLOFastBurn` (users > 250ms) or `OrdersServiceLatencySLOFastBurn` (orders > 500ms) firing.
- User-visible slowness; for orders, timeouts propagating from upstream HTTP calls (5s `AbortSignal.timeout`).
- `http_request_duration_seconds` histogram shifted right in Grafana.

## Diagnosis
1. Route-level p99:
   ```promql
   histogram_quantile(0.99,
     sum by (le, route) (rate(http_request_duration_seconds_bucket{service="<svc>"}[5m]))
   )
   ```
2. For orders-service, check upstream latency:
   ```promql
   histogram_quantile(0.99,
     sum by (le, target_service) (rate(http_client_request_duration_seconds_bucket{service="orders-service"}[5m]))
   )
   ```
3. DB query latency (`db_query_duration_seconds` histogram, instrumented in both services):
   ```promql
   histogram_quantile(0.99, sum by (le) (rate(db_query_duration_seconds_bucket{service="<svc>"}[5m])))
   ```
4. CPU throttling:
   ```promql
   rate(container_cpu_cfs_throttled_seconds_total{pod=~"<svc>.*"}[5m])
   ```
5. Node pressure: `kubectl top nodes`, `kubectl top pods -n observashop`.
6. Check if chaos latency injection was left enabled on users-service:
   ```bash
   kubectl -n observashop port-forward svc/users-service 3000:80
   curl http://localhost:3000/chaos/status
   ```

## Remediation
1. **If CPU throttled:** raise `resources.limits.cpu` in `charts/values/<svc>.yaml`, ArgoCD syncs.
2. **If upstream slow (orders only):** fix users-service or products-service first.
3. **If DB is slow:** check `pg_stat_activity` for long queries, missing indexes.
4. **If traffic spike:** raise `replicaCount` in the values file, ArgoCD syncs.
5. **If chaos left on:** `curl -X POST http://localhost:3000/chaos/latency -d '{"ms": 0}'`.
6. **If GC pressure in Node.js:** bump `NODE_OPTIONS=--max-old-space-size` and memory limits; investigate allocations.

## Escalation
Latency fraction above target for 30 min despite mitigation → page platform on-call lead. Shared-infra root cause → engage cluster on-call.

## Related
- `users-service-errors.md`, `orders-service-errors.md`
- `postgres-connection-pool-exhausted.md`
- `oom-killed.md` (memory pressure often precedes latency)
- `upstream-degraded.md`
