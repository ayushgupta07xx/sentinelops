---
title: "Bad deploy — rollback via ArgoCD"
service: any
severity: critical when correlated with firing SLO alert
alert_names:
  - (derived: any SLO alert firing within 30m of ArgoCD sync or CI image push)
slo: availability, latency
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
A recent deploy correlates with a firing SLO alert. Rollback is the fastest mitigation — investigate root cause after stable. All ObservaShop services are ArgoCD Applications with auto-sync, self-heal, and prune enabled, so `kubectl` changes get reverted — rollback must happen via ArgoCD or by changing Git.

## Symptoms
- SLO alert (error budget or latency) fires within 30 min of ArgoCD sync or GitHub Actions image push.
- Pod restart count spikes right after image tag changes.
- ArgoCD UI shows recent sync with `Status: Healthy` while service metrics disagree.

## Diagnosis
1. Most recent deploy:
   ```bash
   kubectl -n observashop rollout history deployment/<svc>
   kubectl -n observashop describe deployment/<svc> | grep Image:
   argocd app history <svc>-app
   ```
2. Correlate alert start time with sync time — alerts within 30 min of sync strongly suggest the deploy.
3. Image details: CI tags with short commit SHA (`ghcr.io/ayushgupta07xx/observashop/<svc>:<sha>`), manual builds use semver.
4. Diff the failing commit vs last good:
   ```bash
   cd ~/projects/observashop
   git log --oneline <good-sha>..<bad-sha> -- services/<svc>/
   ```

## Remediation
1. **Preferred — ArgoCD rollback:**
   ```bash
   argocd app rollback <svc>-app <previous-revision-id>
   ```
   This pins the Application to a prior revision; self-heal won't fight it.
2. **Then revert the bad commit in Git:**
   ```bash
   git revert <bad-sha> && git push
   ```
   Without this, auto-sync will re-apply the broken state next time you un-pin.
3. **kubectl undo (fallback only if ArgoCD is down):** `kubectl -n observashop rollout undo deployment/<svc>`. Self-heal will revert this unless you also pause auto-sync: `argocd app set <svc>-app --sync-policy none`.
4. After rollback, confirm SLO alert clears within 5 min. If not, the deploy was not the root cause — re-diagnose.

## Escalation
Rollback doesn't clear the alert → follow SLO-specific runbook (`users-service-errors.md` etc.). ArgoCD itself can't sync (e.g., GHCR auth broken, or gotcha: ImagePullBackOff from localhost:5001 containerd misconfig) → platform on-call.

## Related
- `users-service-errors.md`
- `orders-service-errors.md`
- `pod-not-ready.md`
