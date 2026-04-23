---
title: "orders-service: Error budget burning"
service: orders-service
severity: critical
alert_names:
  - OrdersServiceErrorBudgetFastBurn
  - OrdersServiceErrorBudgetSlowBurn
slo: orders_service_availability (99.9%)
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
orders-service is returning 5xx fast enough to burn the 30-day budget. Because orders fans out to users-service and products-service on every request, errors here are often downstream symptoms — always check upstream health first.

## Symptoms
- `OrdersServiceErrorBudgetFastBurn` or `OrdersServiceErrorBudgetSlowBurn` firing.
- Often coincides with `OrdersServiceUpstreamDegraded` — if so, fix upstream first.
- Grafana shows orders-service error ratio above target.

## Diagnosis
1. **Check upstream health first** (cheapest diagnostic — orders has its own outbound-call SLI):
   ```promql
   sli:orders_service:upstream_error_ratio:rate5m
   ```
   Any `target_service` label >0.05 → root cause is upstream. Pivot to `upstream-degraded.md`.
2. Scope own errors by route:
   ```promql
   sum by (route) (rate(http_requests_total{service="orders-service",status_code=~"5.."}[5m]))
   ```
3. Pod health and logs:
   ```bash
   kubectl -n observashop get pods -l app.kubernetes.io/name=orders-service
   kubectl -n observashop logs -l app.kubernetes.io/name=orders-service --tail=200 | grep -iE "error|timeout"
   ```
   orders-service uses `AbortSignal.timeout(5000)` on outbound calls, so upstream slowness shows as timeouts in logs.
4. Database health (orders-service uses database `orders` on the shared `postgres-postgresql-0`):
   ```bash
   kubectl -n observashop get pod postgres-postgresql-0
   ```
5. Recent deploys:
   ```bash
   argocd app history orders-service-app
   ```

## Remediation
1. **If upstream degraded:** follow `upstream-degraded.md`. Do not rollback orders — it's a symptom.
2. **If recent orders deploy correlates:** `argocd app rollback orders-service-app <previous-revision-id>`, then revert the bad commit in Git.
3. **If Postgres is the cause:** see `postgres-connection-pool-exhausted.md`.
4. **If pod-specific:** `kubectl -n observashop delete pod <n>` — Deployment reschedules.
5. **If sustained traffic spike:** raise `replicaCount` in `charts/values/orders-service.yaml`, ArgoCD syncs.

## Escalation
Error ratio >1% for 15 min despite mitigation → page platform on-call lead. If upstream is root cause and owner is unclear, page both users-service and products-service on-call.

## Related
- `upstream-degraded.md`
- `users-service-errors.md`
- `postgres-connection-pool-exhausted.md`
- `latency-slo-burn.md`
