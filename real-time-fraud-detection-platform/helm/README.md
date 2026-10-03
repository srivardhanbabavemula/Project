# Fraud Guard -- Kubernetes Deployment

Deploy the full Fraud Guard stack to a managed Kubernetes cluster (GKE or EKS) using Helm.

## Architecture

```
                         ┌──────────────────────┐
                         │  Ingress (nginx)      │
                         │  TLS via cert-manager │
                         └──────┬───────────────┘
                  ┌─────────────┴──────────────┐
                  ▼                            ▼
         ┌────────────────┐          ┌──────────────┐
         │ FastAPI Serving │          │   Grafana    │
         │ (HPA 2-5 pods) │          │              │
         └───┬────────────┘          └──────┬───────┘
             │                              │
     ┌───────┴───────┐              ┌───────┴───────┐
     ▼               ▼              ▼               │
┌──────────┐  ┌───────────┐  ┌────────────┐        │
│ Postgres │  │   Kafka   │  │ Prometheus │        │
│ (PVC)    │  │ (KRaft)   │  │            │        │
└──────────┘  └─────┬─────┘  └────────────┘        │
                    │                               │
              ┌─────┴─────┐                         │
              │   Spark   │                         │
              │ master +  │─────────────────────────┘
              │ worker    │
              └───────────┘
```

## Prerequisites

- `kubectl` configured for your cluster
- `helm` v3.12+
- A container registry (Docker Hub, GCR, ECR) to push the FastAPI image
- (Optional) A domain name pointed at your cluster's load balancer IP

## 1. Create a Cluster

### GKE (Google Kubernetes Engine)

```bash
# Create cluster (e2-medium nodes are free-tier eligible)
gcloud container clusters create fraud-guard \
  --zone us-central1-a \
  --num-nodes 3 \
  --machine-type e2-medium \
  --disk-size 30

# Get credentials
gcloud container clusters get-credentials fraud-guard --zone us-central1-a
```

### EKS (Amazon Elastic Kubernetes Service)

```bash
# Create cluster with eksctl
eksctl create cluster \
  --name fraud-guard \
  --region us-east-1 \
  --nodegroup-name workers \
  --node-type t3.medium \
  --nodes 3 \
  --nodes-min 2 \
  --nodes-max 4

# kubeconfig is auto-configured by eksctl
```

## 2. Install Ingress Controller & cert-manager

### NGINX Ingress Controller

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

### cert-manager (for TLS)

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
```

Create a Let's Encrypt ClusterIssuer:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
EOF
```

## 3. Build & Push the FastAPI Image

```bash
# From the project root
docker build -t your-registry/fraud-guard-api:latest .
docker push your-registry/fraud-guard-api:latest
```

## 4. Deploy with Helm

### Basic Install

```bash
helm install fraud-guard ./helm/fraud-guard \
  --namespace fraud-guard --create-namespace \
  --set fastapi.image.repository=your-registry/fraud-guard-api \
  --set fastapi.image.tag=latest
```

### Production Install (with custom domain and secrets)

```bash
helm install fraud-guard ./helm/fraud-guard \
  --namespace fraud-guard --create-namespace \
  --set fastapi.image.repository=your-registry/fraud-guard-api \
  --set fastapi.image.tag=latest \
  --set ingress.host=fraud-guard.yourdomain.com \
  --set postgres.auth.password=YOUR_SECURE_PASSWORD \
  --set grafana.auth.adminPassword=YOUR_GRAFANA_PASSWORD
```

### Upgrade

```bash
helm upgrade fraud-guard ./helm/fraud-guard \
  --namespace fraud-guard \
  --set fastapi.image.tag=v2.0.0
```

## 5. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n fraud-guard

# Expected output:
# NAME                                              READY   STATUS    RESTARTS   AGE
# fraud-guard-fraud-guard-fastapi-xxxxxxxxxx-xxxxx  1/1     Running   0          2m
# fraud-guard-fraud-guard-fastapi-xxxxxxxxxx-xxxxx  1/1     Running   0          2m
# fraud-guard-fraud-guard-kafka-0                   1/1     Running   0          2m
# fraud-guard-fraud-guard-postgres-0                1/1     Running   0          2m
# fraud-guard-fraud-guard-spark-master-xxxxx-xxxxx  1/1     Running   0          2m
# fraud-guard-fraud-guard-spark-worker-xxxxx-xxxxx  1/1     Running   0          2m
# fraud-guard-fraud-guard-prometheus-xxxxx-xxxxx    1/1     Running   0          2m
# fraud-guard-fraud-guard-grafana-xxxxx-xxxxx       1/1     Running   0          2m

# Check services
kubectl get svc -n fraud-guard

# Check HPA status
kubectl get hpa -n fraud-guard

# Check ingress
kubectl get ingress -n fraud-guard

# Tail FastAPI logs
kubectl logs -f -l app.kubernetes.io/component=fastapi -n fraud-guard

# Port-forward to test locally (if no Ingress/domain)
kubectl port-forward svc/fraud-guard-fraud-guard-fastapi 8000:8000 -n fraud-guard
kubectl port-forward svc/fraud-guard-fraud-guard-grafana 3000:3000 -n fraud-guard
```

## 6. Test the API

```bash
# Health check
curl https://fraud-guard.yourdomain.com/health

# Score a transaction
curl -X POST https://fraud-guard.yourdomain.com/score \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "amount": 125.50,
    "currency": "USD",
    "merchant_id": "Amazon",
    "merchant_category": "online_retail",
    "country": "US",
    "device_id": "device_12345",
    "cvv_match": true,
    "billing_zip_match": true
  }'
```

## Configuration Reference

All values are configurable via `values.yaml` or `--set` flags:

| Parameter | Default | Description |
|---|---|---|
| `fastapi.image.repository` | `fraud-guard/api` | FastAPI container image |
| `fastapi.hpa.minReplicas` | `2` | Minimum FastAPI replicas |
| `fastapi.hpa.maxReplicas` | `5` | Maximum FastAPI replicas |
| `fastapi.hpa.targetCPUUtilization` | `70` | HPA CPU target % |
| `postgres.auth.password` | `fraudpass123` | PostgreSQL password |
| `postgres.storage.size` | `10Gi` | Postgres PVC size |
| `kafka.storage.size` | `5Gi` | Kafka PVC size |
| `grafana.auth.adminPassword` | `admin` | Grafana admin password |
| `ingress.enabled` | `true` | Enable Ingress |
| `ingress.host` | `fraud-guard.example.com` | Ingress hostname |
| `ingress.tls.enabled` | `true` | Enable TLS |
| `ingress.certManager.clusterIssuer` | `letsencrypt-prod` | cert-manager issuer |

## Cleanup

```bash
# Delete the Helm release
helm uninstall fraud-guard -n fraud-guard

# Delete PVCs (data will be lost)
kubectl delete pvc --all -n fraud-guard

# Delete the namespace
kubectl delete namespace fraud-guard
```
