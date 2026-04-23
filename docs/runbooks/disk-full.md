---
title: "Node or PersistentVolume disk full"
service: node-level (Postgres PV is highest-risk due to 1 GiB initial sizing)
severity: critical
alert_names:
  - NodeFilesystemAlmostOutOfSpace
  - KubePersistentVolumeFillingUp
slo: availability
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
A node's filesystem or a PersistentVolume is approaching full. Node-level DiskPressure evicts pods. PV-full breaks stateful writes — Postgres refuses all writes when its data disk is full, cascading to 5xx across both app services (shared Postgres).

## Symptoms
- `NodeFilesystemAlmostOutOfSpace` or `KubePersistentVolumeFillingUp` firing.
- `kubectl describe node <node>` shows `DiskPressure=True` → pods evicted.
- For PV-full: Postgres logs show `could not write to file: No space left on device`.

## Diagnosis
1. Which node or PV?
   ```promql
   (node_filesystem_size_bytes - node_filesystem_avail_bytes) / node_filesystem_size_bytes > 0.85
   kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85
   ```
2. Node-level:
   ```bash
   kubectl top nodes
   kubectl describe node <node> | grep -A10 Conditions
   ```
3. For Postgres PV specifically (default 1 GiB — easy to fill):
   ```bash
   kubectl -n observashop exec postgres-postgresql-0 -- df -h /bitnami/postgresql
   kubectl -n observashop exec -it postgres-postgresql-0 -- \
     psql -U observashop -d users -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
   ```

## Remediation
1. **Node full from image layers:** prune unused images via crictl on the kind node:
   ```bash
   docker exec -it observashop-worker crictl rmi --prune
   ```
2. **Node full from logs:** check `/var/log` — verify log rotation; truncate if urgent.
3. **Postgres PV full:** expand the PVC (StorageClass must allow):
   ```bash
   kubectl -n observashop patch pvc data-postgres-postgresql-0 \
     -p '{"spec":{"resources":{"requests":{"storage":"5Gi"}}}}'
   ```
   Restart postgres pod to pick up new size.
4. **Postgres WAL runaway:** check for stuck replication slot — `SELECT * FROM pg_replication_slots WHERE active=false;` then `SELECT pg_drop_replication_slot('<n>');`.
5. **Grafana PVC corruption after Docker Desktop restart** (recurring gotcha #7): scale Grafana to 0, delete its PVC, `helm upgrade kps ... --reuse-values`. Loses Grafana state; dashboards/datasources reload from ConfigMaps.
6. **Temporary:** `kubectl cordon <node>` + drain non-critical pods.

## Escalation
PV cannot expand online, or Postgres refusing writes → page data-platform on-call. Sustained node DiskPressure → cluster on-call.

## Related
- `pod-not-ready.md` (evicted pods land here)
- `postgres-connection-pool-exhausted.md`
- `oom-killed.md`
