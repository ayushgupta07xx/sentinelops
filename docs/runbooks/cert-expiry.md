---
title: "TLS certificate expiry (planned work — cert-manager not yet installed)"
service: ingress (future — public traffic when GKE/cloud demo is live)
severity: warning (30d), critical (7d), page (2d)
alert_names:
  - CertManagerCertificateExpirySoon
  - CertManagerCertificateExpired
slo: availability (TLS handshake failure = full outage for affected hosts)
owner: platform-oncall
last_reviewed: 2026-04
---

## Summary
When cert-manager is installed (planned for cloud-demo phase), this runbook applies. Expired or failing-to-renew certs cause TLS handshake failures → full public outage. Until cert-manager is in the stack, this runbook describes the intended response pattern.

## Symptoms
- `CertManagerCertificateExpirySoon` firing.
- Users report `NET::ERR_CERT_DATE_INVALID` or `SSL_ERROR_BAD_CERT_DOMAIN`.
- `kubectl get certificate` shows `READY=False`.

## Diagnosis
1. List certificates:
   ```bash
   kubectl -n observashop get certificate
   kubectl -n observashop describe certificate <n>
   ```
2. Underlying CertificateRequest / Order / Challenge:
   ```bash
   kubectl -n observashop get certificaterequest,order,challenge
   kubectl -n observashop describe order <n>
   ```
3. cert-manager controller logs:
   ```bash
   kubectl -n cert-manager logs deploy/cert-manager --tail=200
   ```
4. Common failure modes:
   - ACME HTTP-01 challenge timing out → ingress path routing broken.
   - DNS-01 failing → DNS credentials expired.
   - Let's Encrypt rate limit (5 failures/hour/account).

## Remediation
1. **Challenge failing:** force re-issue by deleting the CertificateRequest; cert-manager recreates.
2. **DNS credentials expired:** rotate via the referenced Secret.
3. **Rate-limited:** wait for the window; use the staging issuer for testing.
4. **Controller stuck:** `kubectl -n cert-manager rollout restart deploy/cert-manager`.

## Escalation
Cert expires <24h and renewal blocked → page platform lead. Prolonged ACME outage → fall back to manually-issued cert.

## Related
- `deploy-rollback.md` (ingress config changes break ACME challenge routing)
- `pod-not-ready.md`
