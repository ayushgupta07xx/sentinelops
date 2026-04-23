---
title: "Service has fewer than 2 healthy pods"
service: users-service, orders-service
severity: critical
alert_names:
  - UsersServicePodNotReady
  - OrdersServicePodNotReady
slo: availability (HA requirement: min 2 ready replicas)
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
A service has dropped below 2 healthy replicas, violating HA. A single pod failure now causes full outage. This alert was verified during Day 4 chaos testing — scaling replicas to 1 → Pending → Firing in ~3 min as designed.

## Symptoms
- `UsersServicePodNotReady` or `OrdersServicePodNotReady` firing.
- `kubectl get pods` shows `CrashLoopBackOff`, `ImagePullBackOff`, `Pending`, or `Evicted`.
- Deployment `readyReplicas` < `replicas`.

## Diagnosis
1. Pod status and recent events:
   ```bash
   kubectl -n observashop get pods -l app.kubernetes.io/name=<svc> -o wide
   kubectl -n observashop describe pod <pod-name>
   kubectl -n observashop get events --sort-by=.lastTimestamp | tail -30
   ```
2. CrashLoopBackOff → read the previous crash:
   ```bash
   kubectl -n observashop logs <pod-name> --previous --tail=200
   ```
3. Pending → check scheduling (Insufficient cpu/mem, node selector mismatch, PV binding):
   ```bash
   kubectl -n observashop describe pod <pod-name> | grep -A5 Events
   ```
4. ImagePullBackOff → verify image in GHCR (`ghcr.io/ayushgupta07xx/observashop/<service>`) or local registry (`localhost:5001`). Check gotcha: if kind nodes can't resolve `localhost:5001`, the containerd `hosts.toml` + `config_path` append is missing.
5. Evicted → node pressure: `kubectl describe node <node>` → DiskPressure or MemoryPressure.
6. Liveness vs readiness: readiness probes DO check the DB; liveness does NOT. A failing DB causes `Unready` not `CrashLoopBackOff`. Both are correct and intentional.

## Remediation
1. **CrashLoopBackOff from bad deploy:** `argocd app rollback <svc>-app <previous-revision-id>` + revert the Git commit.
2. **Pending due to resources:** `kubectl top nodes` to see capacity; lower requests in values file or scale cluster.
3. **ImagePullBackOff on localhost:5001:** check `docker ps | grep kind-registry`; restart if missing with `docker start kind-registry`.
4. **ImagePullBackOff on GHCR:** confirm image exists at `ghcr.io/ayushgupta07xx/observashop/<svc>:<tag>`; check image pull secrets.
5. **Evicted from node pressure:** see `disk-full.md` or `oom-killed.md`.
6. **Liveness probe killing healthy pod:** increase `initialDelaySeconds` in values file; never add DB checks to liveness.

## Escalation
Replicas cannot be restored within 10 min → page platform on-call lead. Cluster-wide scheduling pressure → cluster on-call.

## Related
- `deploy-rollback.md`
- `oom-killed.md`
- `disk-full.md`
