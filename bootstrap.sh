#!/usr/bin/env bash
# bootstrap.sh — one-shot bring-up of the SentinelOps Kubernetes stack.
#
# Idempotent — safe to re-run. Each step skips work that already exists.
# Total wall-clock on a fresh machine: ~12 minutes (mostly image pulls).
#
# Prereqs (verified up front): docker, kubectl, kind, helm.
# Out-of-scope (run separately): docker-compose services, Modal deploy, secrets.

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
CLUSTER_NAME="sentinelops"
REGISTRY_NAME="kind-registry"
REGISTRY_PORT="5001"
KIND_CONFIG="deploy/k8s/kind-config.yaml"
ARGOCD_VERSION="stable"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
log()  { printf "\n▶ %s\n" "$*"; }
ok()   { printf "✓ %s\n" "$*"; }
warn() { printf "⚠ %s\n" "$*" >&2; }
die()  { printf "✗ %s\n" "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "Missing prerequisite: $1"; }

# ─────────────────────────────────────────────────────────────────────────────
# 0. Prereq check
# ─────────────────────────────────────────────────────────────────────────────
log "Checking prerequisites"
require docker
require kubectl
require kind
require helm
docker info >/dev/null 2>&1 || die "Docker daemon not reachable"
[[ -f "$KIND_CONFIG" ]] || die "Missing $KIND_CONFIG — run from repo root"
ok "Prerequisites OK"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Local Docker registry (used by kind nodes for fast image pulls)
# ─────────────────────────────────────────────────────────────────────────────
log "Bringing up local registry on :${REGISTRY_PORT}"
if [[ "$(docker inspect -f '{{.State.Running}}' ${REGISTRY_NAME} 2>/dev/null || true)" != "true" ]]; then
    docker run -d --restart=always \
        -p "127.0.0.1:${REGISTRY_PORT}:5000" \
        --name "${REGISTRY_NAME}" \
        registry:2 >/dev/null
    ok "Registry container started"
else
    ok "Registry already running"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. kind cluster
# ─────────────────────────────────────────────────────────────────────────────
log "Creating kind cluster '${CLUSTER_NAME}'"
if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
    ok "Cluster already exists"
else
    kind create cluster --name "${CLUSTER_NAME}" --config "${KIND_CONFIG}"
    ok "Cluster created"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Connect registry to kind network (must run AFTER cluster create — the
#    'kind' Docker network is created by `kind create cluster`)
# ─────────────────────────────────────────────────────────────────────────────
log "Connecting registry to kind network"
if ! docker network inspect kind | grep -q "\"${REGISTRY_NAME}\""; then
    docker network connect kind "${REGISTRY_NAME}" 2>/dev/null || true
    ok "Registry connected to kind network"
else
    ok "Registry already connected"
fi

# Apply local-registry-hosting ConfigMap (Kubernetes convention for registry discovery)
log "Applying local-registry-hosting ConfigMap"
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:${REGISTRY_PORT}"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF
ok "ConfigMap applied"

# ─────────────────────────────────────────────────────────────────────────────
# 4. ArgoCD (server-side apply — manifest is too large for client-side)
# ─────────────────────────────────────────────────────────────────────────────
log "Installing ArgoCD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
    -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

log "Waiting for ArgoCD to become ready (this can take 2–3 minutes)"
kubectl -n argocd wait --for=condition=available --timeout=300s \
    deployment/argocd-server \
    deployment/argocd-repo-server \
    deployment/argocd-applicationset-controller
ok "ArgoCD ready"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Pre-create namespaces (the ArgoCD apps create them too via syncOptions,
#    but pre-creating avoids transient race warnings during first sync)
# ─────────────────────────────────────────────────────────────────────────────
log "Creating namespaces"
kubectl create namespace monitoring  --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace sentinelops --dry-run=client -o yaml | kubectl apply -f -
ok "Namespaces ready"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Apply ArgoCD Application manifests
#    argocd/ contains: kube-prometheus-stack-app, qdrant-app, sentinelops-api-app
# ─────────────────────────────────────────────────────────────────────────────
log "Applying ArgoCD Application manifests"
kubectl apply -f argocd/
ok "ArgoCD apps applied — sync in progress"

log "Waiting for ArgoCD apps to converge (kps + qdrant + sentinelops-api, can take 5–8 min on first run)"
sleep 10  # let ArgoCD pick up the new apps
kubectl -n argocd wait --for=jsonpath='{.status.sync.status}'=Synced \
    --timeout=600s applications.argoproj.io --all 2>/dev/null \
    || warn "Some apps not yet Synced — check 'kubectl get applications -n argocd'"

# ─────────────────────────────────────────────────────────────────────────────
# 8. Done
# ─────────────────────────────────────────────────────────────────────────────
cat <<EOF

✅ SentinelOps Kubernetes stack is up.

Next steps:

  1. Configure secrets:
       cp .env.example .env && \$EDITOR .env

  2. Deploy the fine-tuned model to Modal:
       modal deploy serving/inference/modal_vllm.py

  3. Bring up local docker-compose services:
       docker compose up -d redpanda postgres airflow

  4. Smoke-test /triage:
       kubectl -n sentinelops port-forward svc/sentinelops-api-microservice 8001:80 &
       curl -X POST http://localhost:8001/triage \\
         -H 'Content-Type: application/json' \\
         -d @docs/demo/sample_alert.json

  5. Open Grafana:
       kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
       # http://localhost:3000  (admin / prom-operator)

  6. Open ArgoCD:
       kubectl -n argocd port-forward svc/argocd-server 8080:443
       # https://localhost:8080  (admin / \$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d))

For the full reproduction walkthrough see docs/demo.md.
EOF
