# Fraud Guard - System Architecture

## Overview

Fraud Guard is a production-grade real-time fraud detection system built with modern streaming architecture. This document explains the system design, components, and data flow.

---

## High-Level Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    FRAUD GUARD SYSTEM                          │
│           Real-Time Payment Fraud Detection                    │
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

---

## Component Details

### 1. Kafka (Event Streaming)

**Purpose:** Ingests payment transactions from multiple sources

**Key Features:**
- Topic partitioning by user_id for scalability
- At-least-once delivery semantics
- Consumer group for multiple consumers
- Schema registry for data validation

**Topics:**
- `transactions` - Raw incoming transactions
- `features_computed` - Processed features (output from Spark)
- `fraud_alerts` - High-risk transactions

---

### 2. Spark Structured Streaming (Feature Engineering)

**Purpose:** Computes real-time features from transaction streams

**Key Operations:**
- **Windowed Aggregations** - Tumbling windows (1h, 24h, 7d) for velocity features
- **Stateful Operations** - Maintains running counters per user/merchant
- **Watermarking** - Handles late-arriving data (10 min allowed lateness)
- **Write-Ahead Logs** - Ensures fault tolerance

**Feature Categories Computed:**
1. **Velocity Features** (transactions/hour, daily spend)
2. **Behavioral Features** (avg amount, transaction frequency)
3. **Device Features** (new devices, device changes)
4. **Merchant Features** (merchant risk, first-time merchant)
5. **Geographic Features** (distance from home, new country)

**Architecture:**
```
Kafka Source → Windowed Agg → Feature Computation → PostgreSQL Sink
     ↓              ↓                   ↓                   ↓
  Batch Read    Tumble Windows    Engineering            Write
  Every 10s    (1h, 24h, 7d)     31 Features          Features
```

---

### 3. PostgreSQL Feature Store

**Purpose:** Centralized storage for online and offline features

**Tables:**
- `transactions` - Raw transaction records
- `user_velocity_features` - User transaction velocity (1h, 24h, 7d)
- `user_behavioral_features` - Long-term user patterns (30d)
- `merchant_features` - Merchant-level statistics
- `device_features` - Device fingerprint and history
- `model_predictions` - All fraud scoring predictions
- `fraud_alerts` - High-risk transactions requiring review

**Query Performance:**
- Indexed on user_id, merchant_id, device_id
- Partitioned by date for historical data
- Connection pooling for concurrent requests

---

### 4. FastAPI Fraud Scoring API

**Purpose:** Serves real-time fraud risk scores

**Endpoints:**
```
POST /score                 - Score a single transaction
  Request:  user_id, amount, merchant_id, country, etc.
  Response: fraud_probability, decision, risk_level, reasons

POST /score/batch          - Score multiple transactions
  Request:  List of transactions
  Response: List of fraud scores

GET /health                - Health check
GET /metrics               - Prometheus metrics
GET /features/{user_id}    - Get user features
```

**Scoring Pipeline:**
```
1. Receive Transaction (JSON)
       ↓
2. Validate Input
       ↓
3. Fetch Features from PostgreSQL
       ├─ User velocity (cache from Redis if available)
       ├─ User behavioral pattern
       ├─ Merchant risk score
       ├─ Device history
       └─ Geographic flags
       ↓
4. Run XGBoost Model Inference
       ├─ Input: 31 features
       ├─ Output: fraud probability (0-1)
       └─ Decision: approve/review/decline
       ↓
5. Apply Business Rules
       ├─ Risk thresholds
       ├─ Velocity limits
       └─ Geographic rules
       ↓
6. Return Response + Log to PostgreSQL
```

---

### 5. XGBoost Model

**Purpose:** Gradient boosting classifier for fraud detection

**Model Configuration:**
- **Type:** Binary classification (fraud/legitimate)
- **Features:** 31 engineered features
- **Training Data:** 10,000 synthetic transactions (2% fraud)
- **Class Balancing:** SMOTE + RandomUnderSampler
- **Performance:** 100% accuracy on test set

**Feature Importance (Top 5):**
1. Merchant transaction count (24h) - 53.3%
2. Device total transactions - 38.9%
3. Merchant fraud rate (24h) - 3.7%
4. Device fraud rate - 2.4%
5. Velocity avg amount (1h) - 0.7%

**Decision Thresholds:**
- Probability > 0.7 → "decline" (high risk)
- Probability 0.5-0.7 → "review" (medium risk)
- Probability < 0.5 → "approve" (low risk)

---

### 6. Prometheus & Grafana

**Purpose:** Observability and monitoring

**Key Metrics:**
- `transactions_processed_total` - Total transactions
- `fraud_transactions_total` - Detected fraud
- `api_request_duration_seconds` - API latency
- `model_inference_seconds` - Model scoring time
- `feature_retrieval_seconds` - Database query time

**Grafana Dashboards:**
- Real-time transaction metrics
- Fraud rate trends
- Model performance metrics
- System resource utilization
- Alert rules and notifications

---

## Data Flow

### Normal Transaction Flow

```
1. User initiates payment (amount: $150, merchant: Amazon, country: US)
              ↓
2. Payment gateway sends transaction to Kafka
   {
     "transaction_id": "txn-123",
     "user_id": "user-456",
     "amount": 150.00,
     "merchant_id": "amz-789",
     "timestamp": "2025-12-21T10:30:00Z",
     "country": "US"
   }
              ↓
3. Spark Streaming processes in real-time
   • Increments user velocity counters
   • Checks for anomalies
   • Updates feature store
              ↓
4. FastAPI receives score request
   POST /score {transaction}
              ↓
5. API fetches features from PostgreSQL
   • User velocity (last 1h: 3 txns, avg: $120)
   • User behavior (typical: $100-200)
   • Device: trusted (2 months old)
   • Merchant: low risk (fraud_rate: 0.01%)
   • Country: home country (US)
              ↓
6. XGBoost model inference
   Input: [velocity=3, avg_amount=150, device_age=60, merchant_fraud_rate=0.01, ...]
   Output: fraud_probability = 0.02 (2% fraud probability)
              ↓
7. Decision logic
   • 0.02 < 0.5 → APPROVE
   • No anomalies detected
   • Add to whitelist for faster future approvals
              ↓
8. Response returned in <500ms
   {
     "fraud_probability": 0.02,
     "decision": "approve",
     "risk_level": "low",
     "reasons": []
   }
              ↓
9. Transaction proceeds, customer receives product
```

### Fraud Transaction Flow

```
1. Attacker attempts to use stolen card
   Amount: $5,000 (unusual, user's typical: $100-200)
              ↓
2. Transaction reaches Fraud Guard
              ↓
3. Feature retrieval
   • User velocity (1h: 5 txns in last 5 min - anomaly!)
   • User behavior (typical: $100-200, current: $5,000 - anomaly!)
   • Device: new device (1 min old - anomaly!)
   • Country: different from home (Singapore vs US - anomaly!)
   • Merchant: high-risk category
              ↓
4. XGBoost inference
   Input: [velocity=5, avg_amount=5000, device_age=1, country_change=1, ...]
   Output: fraud_probability = 0.95 (95% fraud probability)
              ↓
5. Decision logic
   • 0.95 > 0.7 → DECLINE
   • Multiple anomalies detected
   • Alert triggered for fraud team
              ↓
6. Response returned
   {
     "fraud_probability": 0.95,
     "decision": "decline",
     "risk_level": "critical",
     "reasons": [
       "Unusual transaction amount ($5,000 vs typical $150)",
       "New device detected",
       "Transaction from different country",
       "High velocity (5 transactions in 5 minutes)"
     ]
   }
              ↓
7. Transaction blocked, user notified, fraud team investigates
```

---

## Scalability Considerations

### Horizontal Scaling

**Kafka:**
- Partition transactions by user_id
- Multiple consumer groups (feature engine, real-time model, analytics)
- Parallel processing across multiple brokers

**Spark:**
- Distributed cluster mode with multiple workers
- Shuffle partitions tuned for throughput
- Memory configuration for large aggregations

**PostgreSQL:**
- Read replicas for feature retrieval
- Write optimization with batch inserts
- Connection pooling (HikariCP equivalent)

**FastAPI:**
- Multiple Uvicorn workers
- Load balancing across instances
- Async request handling

### Performance Targets

- **Throughput:** 10,000+ TPS (local), 100k+ TPS (AWS)
- **Latency (P99):** <500ms end-to-end
- **Feature retrieval:** <100ms
- **Model inference:** <50ms
- **Availability:** 99.9% uptime

---

## Deployment Architecture

### Local Development

```
Docker Compose
├── Kafka Container
├── PostgreSQL Container
├── Spark Master + Worker
├── Prometheus Container
├── Grafana Container
└── Redis Container (optional)
```

### Production (AWS)

```
AWS Infrastructure
├── EC2 (API + Application)
├── RDS (PostgreSQL)
├── MSK (Kafka)
├── ElastiCache (Redis)
├── S3 (Model artifacts)
├── CloudWatch (Monitoring)
└── ALB (Load balancer)
```

---

## Security Considerations

1. **API Security**
   - Rate limiting per user/IP
   - API key authentication
   - Request validation

2. **Data Security**
   - Encrypted connections (TLS)
   - Database encryption at rest
   - Masked PII in logs

3. **Model Security**
   - Model versioning and approval
   - A/B testing before production
   - Explainability for decisions

---

## Future Enhancements

- [ ] Multi-armed bandits for adaptive thresholds
- [ ] Graph neural networks for fraud ring detection
- [ ] SHAP values for model explainability
- [ ] Real-time model retraining
- [ ] Kubernetes deployment
- [ ] Multi-class classification (fraud types)

---

## References

- **Apache Kafka:** https://kafka.apache.org/
- **Apache Spark:** https://spark.apache.org/
- **PostgreSQL:** https://www.postgresql.org/
- **FastAPI:** https://fastapi.tiangolo.com/
- **XGBoost:** https://xgboost.readthedocs.io/
