# SentinelOps Deploy

Local kind cluster + ArgoCD GitOps + Helm. Patterns reused from ObservaShop.

## Prerequisites

- Docker Desktop with WSL integration
- `kind`, `kubectl`, `helm`, `argocd` CLIs in PATH
- Local container registry on `localhost:5001` (use ObservaShop's `infra/scripts/setup-local-registry.sh`)

## Bring-up

### 1. Cluster

    kind create cluster --config deploy/k8s/kind-config.yaml
    kubectl config use-context kind-sentinelops

### 2. Build + push the API image

    docker build -f serving/api/Dockerfile -t localhost:5001/sentinelops/api:0.1.0 .
    docker push localhost:5001/sentinelops/api:0.1.0

### 3. Namespace + secrets (out-of-band; never commit)

    kubectl create namespace sentinelops
    kubectl -n sentinelops create secret generic sentinelops-secrets \
      --from-literal=MODAL_VLLM_BASE_URL="$MODAL_VLLM_BASE_URL" \
      --from-literal=MODAL_VLLM_API_KEY="$MODAL_VLLM_API_KEY" \
      --from-literal=QDRANT_API_KEY="localdev" \
      --from-literal=GROQ_API_KEY="$GROQ_API_KEY"

### 4. Install ArgoCD

    kubectl create namespace argocd
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
    kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

### 5. Apply ArgoCD Applications

Order matters: kube-prometheus-stack first (its ServiceMonitor CRD is needed by sentinelops-api), then qdrant, then API.

    kubectl apply -f argocd/kube-prometheus-stack-app.yaml
    kubectl wait --for condition=established --timeout=120s crd/servicemonitors.monitoring.coreos.com
    kubectl apply -f argocd/qdrant-app.yaml
    kubectl apply -f argocd/sentinelops-api-app.yaml

### 6. Verify

    kubectl get pods -A | grep -E "sentinelops|qdrant|prometheus|grafana"
    # Grafana: http://localhost:3000  (admin/admin via NodePort 30030)

## Helm-only path (skip ArgoCD)

    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add qdrant https://qdrant.github.io/qdrant-helm
    helm repo update

    kubectl create namespace monitoring
    helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
      -n monitoring -f deploy/helm/sentinelops/values/kube-prometheus-stack.yaml

    helm install qdrant qdrant/qdrant \
      -n sentinelops -f deploy/helm/sentinelops/values/qdrant.yaml

    helm install sentinelops-api deploy/helm/sentinelops/microservice \
      -n sentinelops -f deploy/helm/sentinelops/values/sentinelops-api.yaml
