# 💳 Fraud Guard - Real-Time Payment Fraud Detection System

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Kafka](https://img.shields.io/badge/Kafka-Stream-black.svg)](https://kafka.apache.org/)
[![Spark](https://img.shields.io/badge/Spark-3.5-orange.svg)](https://spark.apache.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-ML-red.svg)](https://xgboost.readthedocs.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> An end-to-end real-time fraud detection system that processes payment transactions and provides fraud risk scores. This project demonstrates enterprise-grade architecture patterns used by FinTech companies like Stripe, PayPal, and Visa.

---

## 🎯 Overview

Fraud Guard is a production-ready fraud detection platform that:

- **Processes streaming transactions** in real-time via Kafka
- **Computes features dynamically** using Spark Structured Streaming
- **Scores fraud risk** with a trained XGBoost classifier
- **Serves predictions** through a high-performance REST API
- **Manages Models & A/B Tests** via a custom Postgres Model Registry
- **Monitors Data Drift** with Evidently to auto-rollback on threshold breaches
- **Visualizes MLOps Metrics** with a dedicated Streamlit Dashboard

### Key Highlights

✅ **Real-time Processing** - Kafka streaming with Spark feature engineering  
✅ **End-to-End MLOps** - Data pipeline, model registry, A/B testing, drift-triggered auto-rollback, and CI/CD  
✅ **Production-Ready** - API, monitoring, database, and error handling  
✅ **100% Free** - Uses only open-source tools and AWS free tier  
✅ **Scalable** - Docker-based deployment ready for cloud migration  

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    FRAUD GUARD SYSTEM                          │
└────────────────────────────────────────────────────────────────┘

                    Transaction Input Stream
                            │
                            ▼
                    ┌──────────────────┐
                    │     Kafka        │  Real-time event ingestion
                    │   (Topics)       │  • transaction.created
                    └────────┬─────────┘  • transaction.enriched
                             │
                             ▼
        ┌────────────────────────────────────────────┐
        │  REAL-TIME FEATURE ENGINEERING            │
        │  (Spark Structured Streaming)             │
        ├────────────────────────────────────────────┤
        │ • Velocity features (1h, 24h, 7d windows) │
        │ • User behavioral patterns                │
        │ • Merchant risk scores                    │
        │ • Device fingerprints                     │
        │ • Geographic anomalies                    │
        └────────────────────┬───────────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   PostgreSQL     │  Feature Store
                    │   (Feature       │  • User velocity
                    │    Store)        │  • Merchant profiles
                    └────────┬─────────┘  • Device history
                             │
                             ▼
        ┌────────────────────────────────────────────┐
        │         FRAUD SCORING API                 │
        │         (FastAPI Endpoint)                │
        ├────────────────────────────────────────────┤
        │ • Fetch features (online retrieval)       │
        │ • XGBoost model inference                 │
        │ • Risk decision (approve/review/decline)  │
        │ • Return fraud probability & reasons      │
        └────────────────────┬───────────────────────┘
                             │
                    ┌────────┴─────────┐
                    │                  │
                    ▼                  ▼
            ┌──────────────┐   ┌──────────────┐
            │  Prometheus  │   │  PostgreSQL  │
            │  (Metrics)   │   │  (Logs)      │
            └──────┬───────┘   └──────────────┘
                   │
                   ▼
            ┌──────────────┐
            │   Grafana    │  Dashboards & Alerts
            │ (Dashboard)  │
            └──────────────┘
```

### Components Explained

1. **Kafka** - Ingests payment transactions from multiple sources
2. **Spark** - Computes real-time features using windowed aggregations
3. **PostgreSQL** - Stores features, transaction history, and the **Model Registry**
4. **FastAPI** - Serves fraud scoring predictions and A/B testing router
5. **XGBoost** - Trained model for fraud classification
6. **Streamlit** - MLOps Dashboard for model registry, experiments, and data drift
7. **Evidently** - Drift detection & auto-rollback
8. **Prometheus / Grafana** - Collects system and application metrics

---

## 📊 System Features

### Real-Time Features (Computed in Streaming)

| Category | Examples | Window |
|----------|----------|--------|
| **Velocity** | Transactions/hour, daily spend, frequency anomalies | 1h, 24h, 7d |
| **Behavioral** | Average transaction amount, time patterns | 30d |
| **Geographic** | Home country, travel distance, new location flag | Real-time |
| **Device** | Device age, number of users per device | 90d |
| **Merchant** | First-time merchant, merchant risk category | Real-time |

### Model Performance

- **Accuracy**: 100% (test set)
- **Precision**: 100%
- **Recall**: 100%
- **ROC-AUC**: 1.0
- **Training Data**: 10,000 synthetic transactions (2% fraud rate)
- **Feature Count**: 31 engineered features
- **Model Type**: XGBoost with SMOTE balancing for imbalanced data

---

## 🚀 Quick Start

### Prerequisites

- Docker Desktop (free)
- Python 3.9+ 
- 4GB RAM, 10GB disk space

### Installation

```bash
# 1. Clone repository
git clone https://github.com/yourusername/fraud-guard.git
cd fraud-guard

# 2. Setup Python environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Docker services
docker-compose up -d

# 5. Initialize database
python scripts/init_db_proper.py

# 6. Start API server
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 7. Access dashboards
# API Docs: http://localhost:8000/docs
# MLOps Dashboard (Streamlit): http://localhost:8502
# Grafana: http://localhost:3000 (admin/admin)
# Kafka UI: http://localhost:8080
```

### Test the API

```bash
# Score a single transaction
curl -X POST "http://localhost:8000/score" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "transaction_id": "txn-456",
    "amount": 150.00,
    "merchant_id": "merchant-789",
    "timestamp": "2025-12-21T10:30:00Z",
    "country": "US"
  }'

# Response:
# {
#   "fraud_probability": 0.02,
#   "decision": "approve",
#   "risk_level": "low",
#   "reasons": []
# }
```

---

## 📁 Project Structure

```
fraud-guard/
├── api/                          # FastAPI server
│   ├── main.py                   # REST endpoints & Pydantic models
│   └── fraud_scorer.py           # Fraud detection logic
│
├── ml/                           # Machine learning & MLOps
│   ├── train_model.py            # XGBoost training pipeline
│   ├── registry.py               # Custom Postgres Model Registry
│   ├── ab_router.py              # A/B testing traffic router
│   ├── drift_monitor.py          # Evidently data drift & auto-rollback
│   └── models/                   # Trained model artifacts (gitignored)
│
├── feature_store/                # Feature engineering
│   ├── store.py                  # Feature retrieval & freshness
│   └── schema.sql                # Database schema
│
├── dashboard/                    # MLOps Dashboard
│   └── app.py                    # Streamlit interface
│
├── streaming/                    # Real-time processing
│   ├── kafka_producer.py         # Transaction generator
│   └── transaction_processor.py  # Spark streaming job
│
├── monitoring/                   # Observability
│   ├── prometheus/               # Metrics config
│   └── grafana/                  # Dashboard configs
│
├── helm/                         # Kubernetes deployment
│   ├── fraud-guard/              # Helm chart (all K8s manifests)
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── templates/            # K8s resource templates
│   │   └── files/                # Static files (schema, dashboards)
│   └── README.md                 # Deployment guide
│
├── scripts/                      # Utilities
│   └── init_db_proper.py         # Database initialization
│
├── Dockerfile                    # Multi-stage FastAPI container image
├── docker-compose.yml            # Local infrastructure
├── requirements.txt              # Full Python dependencies
├── requirements-api.txt          # Runtime-only dependencies (for Docker)
└── README.md                     # This file
```

---

## 🛠️ Technology Stack (All Open-Source & Free)

### Streaming & Processing
- **Apache Kafka** - Message broker for transaction streams
- **Apache Spark** 3.5 - Distributed stream processing
- **Python** 3.9+ - Application logic

### Storage & Database
- **PostgreSQL** 15 - Feature store & transaction history
- **Redis** - Optional hot feature caching

### Machine Learning & MLOps
- **XGBoost** - Gradient boosting for classification
- **Evidently** - Data drift detection and monitoring
- **scikit-learn** - Data preprocessing & metrics
- **Streamlit** - MLOps Control Plane Dashboard

### API & Serving
- **FastAPI** - High-performance REST API
- **Uvicorn** - ASGI application server

### Monitoring & Observability
- **Prometheus** - Metrics collection
- **Grafana** - Visualization dashboards

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Local orchestration
- **Kubernetes / Helm** - Production deployment (GKE / EKS)

---

## 🎓 Learning Outcomes

By studying this project, you'll learn:

1. **Real-time Streaming** - Kafka architecture, topic partitioning, consumer groups
2. **Feature Engineering** - Windowed aggregations, time-series features, feature stores
3. **Machine Learning Ops** - Model training, evaluation, deployment pipelines
4. **System Design** - Scalable architectures, monitoring, error handling
5. **FinTech Domain** - Fraud patterns, risk scoring, compliance considerations
6. **API Design** - RESTful services, async/await, request validation
7. **DevOps** - Docker, orchestration, cloud deployment

---

## 🤖 Model Training

The system includes a complete training pipeline:

```python
# Generate synthetic data (2% fraud rate)
# Balance dataset with SMOTE + undersampling
# Train XGBoost classifier
# Perform 5-fold cross-validation
# Evaluate metrics and feature importance
# Save model artifacts with metadata

python ml/train_model.py
```

**Top Features by Importance:**
1. Merchant transaction count (24h) - 53.3%
2. Device total transactions - 38.9%
3. Merchant fraud rate (24h) - 3.7%
4. Device fraud rate - 2.4%
5. Other velocity/behavioral features - 2.2%

---

## 🔧 Configuration

### Environment Variables

All services read configuration from environment variables with backward-compatible defaults. Create a `.env` file for local development, or use ConfigMaps/Secrets in Kubernetes:

```bash
# Database
DB_HOST=localhost              # K8s: set via ConfigMap
DB_PORT=5433                   # K8s: 5432 (in-cluster)
DB_USER=frauduser
DB_PASSWORD=fraudpass123       # K8s: set via Secret
DB_NAME=fraud_detection

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
KAFKA_TOPIC=payment-transactions

# Spark
SPARK_CHECKPOINT_DIR=/tmp/spark-checkpoints

# Model thresholds
MODEL_THRESHOLD_DECLINE=0.8
MODEL_THRESHOLD_REVIEW=0.5
MODEL_THRESHOLD_LOW_RISK=0.2
```

---

## 📊 Dashboards & MLOps Control Plane

### Streamlit MLOps Dashboard (http://localhost:8502)
A unified control plane for your ML infrastructure:
- **Model Registry**: View production/challenger models and their historical training ROC-AUC.
- **A/B Testing**: Visualize live traffic splits routing to active experiments.
- **Data Drift**: Audit Evidently drift reports and track automated rollbacks.

### Grafana (http://localhost:3000)

Dashboards track:
- Transaction throughput
- Fraud detection rate
- Model performance metrics
- API latency percentiles
- System resource usage

**Default Credentials:** admin / admin

### Prometheus (http://localhost:9090)

Available metrics:
- `fraud_detection:transaction_count` - Total transactions processed
- `fraud_detection:fraud_count` - Detected fraudulent transactions
- `fraud_detection:api_latency_seconds` - Request latency
- `fraud_detection:model_inference_time_seconds` - Model scoring time

---

## 🌐 Deployment

### Local Development

```bash
docker-compose up -d
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Kubernetes (GKE / EKS)

The project includes a full Helm chart for production deployment. See [`helm/README.md`](helm/README.md) for the complete guide.

```bash
# Build and push the Docker image
docker build -t your-registry/fraud-guard-api:latest .
docker push your-registry/fraud-guard-api:latest

# Deploy to your cluster
helm install fraud-guard ./helm/fraud-guard \
  --namespace fraud-guard --create-namespace \
  --set fastapi.image.repository=your-registry/fraud-guard-api \
  --set postgres.auth.password=YOUR_SECURE_PASSWORD
```

**What the Helm chart deploys:**

| Component | Kind | Details |
|-----------|------|---------|
| FastAPI API | Deployment + HPA | 2-5 replicas, autoscales at 70% CPU |
| PostgreSQL | StatefulSet | 10Gi PVC, schema auto-initialized |
| Kafka | StatefulSet | KRaft mode (no ZooKeeper), 5Gi PVC |
| Spark | Deployment | Master + worker |
| Prometheus | Deployment | Scrapes FastAPI `/metrics` |
| Grafana | Deployment | Pre-provisioned datasources & dashboards |
| Ingress | Ingress | TLS via cert-manager, nginx |

**Features:** Liveness/readiness probes on all services, ConfigMaps for environment, Secrets for credentials, TLS termination via cert-manager.

### AWS Deployment (Free Tier)

- EC2 t2.micro for API server
- RDS PostgreSQL (Free Tier)
- Self-hosted Kafka on EC2
- S3 for model artifacts
- CloudWatch for monitoring

---

## 🤝 Contributing

Contributions are welcome! Areas for improvement:

- [ ] Additional fraud detection rules
- [ ] Multi-class classification (fraud types)
- [ ] Real-time model retraining
- [ ] Advanced feature engineering
- [x] Production Kubernetes deployment
- [ ] Integration tests
- [ ] Load testing & benchmarking

---

## 📚 References & Learning Resources

### System Design
- **Designing Data-Intensive Applications** by Martin Kleppmann
- **The Art of Scalability** by Martin Abbott & Michael Fisher

### Fraud Detection
- [PayPal Fraud Detection Research](https://www.paypal.com/)
- [Stripe Engineering Blog](https://stripe.com/blog)
- [Uber Engineering - Real-time ML Systems](https://eng.uber.com/)

### Technology Specific
- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [Apache Spark Structured Streaming](https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html)
- [XGBoost Documentation](https://xgboost.readthedocs.io/)
- [FastAPI Guide](https://fastapi.tiangolo.com/)

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

---

**⭐ If this project helped you learn, please consider starring it!**
