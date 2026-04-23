---
title: "Pod OOMKilled"
service: any
severity: warning
alert_names:
  - (derived: KubePodCrashLooping with reason=OOMKilled, or PodNotReady)
slo: availability
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
A container exceeded its memory limit and was killed by the kernel OOM killer. Pod restarts; may cascade into CrashLoopBackOff if the spike is reproducible on startup. Most likely on Node.js services (users, products, orders) because V8 heap + libuv threadpool can allocate aggressively under load.

## Symptoms
- `kubectl describe pod` shows `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`.
- `container_memory_working_set_bytes` approached `container_spec_memory_limit_bytes` just before termination.
- Pod restart count climbing on the Grafana "ObservaShop - Users Service" dashboard (healthy pods panel).

## Diagnosis
1. Identify OOMKilled pods:
   ```bash
   kubectl -n observashop get pods -o json | jq -r '.items[] | select(.status.containerStatuses[]?.lastState.terminated.reason=="OOMKilled") | .metadata.name'
   ```
2. Memory trajectory:
   ```promql
   max by (pod) (container_memory_working_set_bytes{namespace="observashop", pod=~"<svc>.*"})
   / on(pod)
   max by (pod) (container_spec_memory_limit_bytes{namespace="observashop", pod=~"<svc>.*"})
   ```
3. Is OOM at startup (bad — likely code issue) or under load (capacity issue)?
   ```bash
   kubectl -n observashop logs <pod> --previous --tail=100
   ```
4. Node.js heap specifically: services run with default heap unless `NODE_OPTIONS=--max-old-space-size` is set. Default can blow past container limit on a 512Mi container.

## Remediation
1. **Immediate:** raise `resources.limits.memory` in `charts/values/<svc>.yaml`; ArgoCD syncs. Typical bump: 1.5×.
2. **If OOM on startup after deploy:** likely memory leak or bad new dep → `argocd app rollback <svc>-app` + revert Git commit.
3. **If leak suspected:** capture heap snapshot via `--inspect`, compare across time. Fix in code; don't keep raising limits.
4. **If traffic spike:** raise `replicaCount` horizontally instead of per-pod limit.
5. **Align Node heap with container limit:** set `NODE_OPTIONS=--max-old-space-size=384` (MB) if container limit is 512Mi, via `env` in values file.

## Escalation
Raising limits doesn't stop OOM within one cycle → suspect leak, page service owner. Multiple services OOM simultaneously → node pressure, see `disk-full.md` + `kubectl top nodes`.

## Related
- `pod-not-ready.md`
- `deploy-rollback.md`
- `latency-slo-burn.md`
