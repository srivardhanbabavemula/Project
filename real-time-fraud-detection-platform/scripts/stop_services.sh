#!/bin/bash

# =====================================================
# Stop All Services
# =====================================================

echo "Stopping Fraud Detection System..."

# Stop background processes
echo "Stopping background processes..."
pkill -f "kafka_producer.py" || true
pkill -f "transaction_processor.py" || true
pkill -f "uvicorn" || true

# Stop Docker containers
echo "Stopping Docker containers..."
docker-compose down

echo ""
echo "All services stopped."
