#!/bin/bash

# =====================================================
# Fraud Detection System - Startup Script
# =====================================================

set -e

echo "=========================================="
echo "Starting Fraud Detection System"
echo "=========================================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Start infrastructure with Docker Compose
echo ""
echo "1. Starting infrastructure (Kafka, PostgreSQL, Spark, Monitoring)..."
docker-compose up -d

echo ""
echo "Waiting for services to be healthy..."
sleep 15

# Initialize database
echo ""
echo "2. Initializing database..."
python3 scripts/init_db.py

# Train model if not exists
if [ ! -f "ml/models/fraud_model_v*.pkl" ]; then
    echo ""
    echo "3. Training fraud detection model..."
    python3 ml/train_model.py
else
    echo ""
    echo "3. Model already trained, skipping..."
fi

# Start transaction producer in background
echo ""
echo "4. Starting transaction producer..."
nohup python3 streaming/kafka_producer.py --rate 5 > logs/producer.log 2>&1 &
PRODUCER_PID=$!
echo "Transaction producer started (PID: $PRODUCER_PID)"

# Start Spark streaming job in background
echo ""
echo "5. Starting Spark streaming job..."
nohup python3 streaming/transaction_processor.py > logs/spark.log 2>&1 &
SPARK_PID=$!
echo "Spark streaming started (PID: $SPARK_PID)"

# Wait a bit for streaming to initialize
sleep 5

# Start FastAPI server
echo ""
echo "6. Starting FastAPI server..."
echo ""
echo "=========================================="
echo "System Ready!"
echo "=========================================="
echo ""
echo "Access points:"
echo "  - API Documentation:  http://localhost:8000/docs"
echo "  - Grafana Dashboard:  http://localhost:3000 (admin/admin)"
echo "  - Kafka UI:           http://localhost:8080"
echo "  - Prometheus:         http://localhost:9090"
echo ""
echo "Background processes:"
echo "  - Transaction Producer PID: $PRODUCER_PID"
echo "  - Spark Streaming PID:      $SPARK_PID"
echo ""
echo "To stop all services, run: ./scripts/stop_services.sh"
echo "=========================================="
echo ""

# Start API server (foreground)
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
