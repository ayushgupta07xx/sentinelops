---
title: "orders-service: upstream dependency degraded"
service: orders-service
severity: warning
alert_names:
  - OrdersServiceUpstreamDegraded
slo: orders_service_dependencies
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
orders-service fans out to users-service and products-service on every order. When either upstream returns errors >5% over 5 min (measured via `http_client_requests_total` instrumented in orders-service), this alert fires — typically *before* orders-service's own error budget starts burning. This is the early-warning dependency pattern. Fix the upstream, not orders.

## Symptoms
- `OrdersServiceUpstreamDegraded` firing with `target_service` label = `users-service` or `products-service`.
- orders-service error rate may still look healthy — this alert is the leading indicator.
- User-visible: slow or failed checkout flows.

## Diagnosis
1. Identify the degraded upstream from the alert's `target_service` label.
2. Confirm from orders-service's perspective:
   ```promql
   sli:orders_service:upstream_error_ratio:rate5m
   ```
3. Cross-check from the upstream's own metrics:
   ```promql
   sum by (status_code) (rate(http_requests_total{service="<target_service>"}[5m]))
   ```
4. Upstream pod health:
   ```bash
   kubectl -n observashop get pods -l app.kubernetes.io/name=<target_service>
   ```
5. If upstream metrics look healthy but orders sees errors → suspect network/DNS:
   ```bash
   kubectl -n observashop exec deploy/orders-service -- wget -qO- http://<target_service>:80/healthz
   kubectl -n kube-system get pods -l k8s-app=kube-dns
   ```

## Remediation
1. **If upstream is the root cause:** pivot to that service's runbook (`users-service-errors.md` or investigate products-service). Fix there; this alert auto-resolves when upstream recovers.
2. **If upstream is healthy but orders sees errors:** check CoreDNS and any NetworkPolicy in the `observashop` namespace.
3. **If products-service is degraded and no runbook exists:** products-service is in-memory (no DB), so remediation is just pod restart or rollback — `argocd app rollback products-service-app`.

## Escalation
Upstream owner and orders owner differ → coordinate via incident channel. DNS/network root cause → cluster on-call.

## Related
- `users-service-errors.md`
- `orders-service-errors.md`
- `pod-not-ready.md`
