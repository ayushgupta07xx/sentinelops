---
title: "users-service: Error budget burning"
service: users-service
severity: critical
alert_names:
  - UsersServiceErrorBudgetFastBurn
  - UsersServiceErrorBudgetSlowBurn
slo: users_service_availability (99.9%)
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
users-service is returning 5xx at a rate that consumes the 30-day error budget faster than the SLO allows. Fast burn depletes the budget in ~2h (burn rate 14.4); slow burn in ~5h (burn rate 6). Alerts use multi-window (5m AND 1h, or 30m AND 6h) to confirm the burn is real before paging.

## Symptoms
- Alert `UsersServiceErrorBudgetFastBurn` or `UsersServiceErrorBudgetSlowBurn` firing in Alertmanager.
- Grafana "ObservaShop SLO" dashboard: users-service error ratio above the target line.
- orders-service may show a correlated `OrdersServiceUpstreamDegraded` within minutes (orders → users over HTTP).

## Diagnosis
1. Scope the errors by route:
   ```promql
   sum by (route) (rate(http_requests_total{service="users-service",status_code=~"5.."}[5m]))
   ```
2. Pod health and recent logs (logs go through Promtail → Loki):
   ```bash
   kubectl -n observashop get pods -l app.kubernetes.io/name=users-service
   kubectl -n observashop logs -l app.kubernetes.io/name=users-service --tail=200 | grep -iE "error|exception"
   ```
3. Database health (users-service uses the shared `postgres-postgresql-0` Bitnami instance, database `users`):
   ```bash
   kubectl -n observashop get pod postgres-postgresql-0
   ```
4. Check if chaos was left enabled from testing (users-service has `/chaos/error-rate` and `/chaos/latency`):
   ```bash
   observashop-cli chaos --help
   # or directly:
   kubectl -n observashop port-forward svc/users-service 3000:80
   curl http://localhost:3000/chaos/status
   ```
5. Recent deploys (ArgoCD is the source of truth after Day 5 — all changes flow through Git):
   ```bash
   kubectl -n observashop rollout history deployment/users-service
   argocd app history users-service-app
   ```

## Remediation
1. **If deploy in last 30 min correlates:** rollback via ArgoCD — `argocd app rollback users-service-app <previous-revision-id>`. After rollback, revert the bad commit in Git so auto-sync doesn't re-apply it.
2. **If single pod is the outlier:** `kubectl -n observashop delete pod <name>` — the Deployment reschedules.
3. **If chaos left on:**
   ```bash
   curl -X POST http://localhost:3000/chaos/error-rate -H 'Content-Type: application/json' -d '{"rate": 0}'
   curl -X POST http://localhost:3000/chaos/latency    -H 'Content-Type: application/json' -d '{"ms": 0}'
   ```
4. **If Postgres is the cause:** see `postgres-connection-pool-exhausted.md`.
5. **If resource-bound:** scale out by raising `replicaCount` in `charts/values/users-service.yaml` and letting ArgoCD sync. Do not `kubectl scale` directly — self-heal will revert it.

## Escalation
Error ratio >1% for 15 min after mitigation → page platform on-call lead. If Postgres is root cause, engage data-platform on-call.

## Related
- `orders-service-errors.md` (correlated burn via upstream dependency)
- `postgres-connection-pool-exhausted.md`
- `pod-not-ready.md`
- `deploy-rollback.md`
