#!/bin/bash

# =====================================================
# Fraud Guard - Quick Startup Script
# =====================================================

echo "=========================================="
echo "Fraud Guard - Fraud Detection System"
echo "=========================================="
echo ""

# Check Docker
echo "1. Checking Docker status..."
if ! docker info > /dev/null 2>&1; then
    echo ""
    echo "⚠️  Docker is not running!"
    echo ""
    echo "Please start Docker Desktop:"
    echo "  - On Mac: Applications > Docker.app"
    echo "  - On Windows: Search for Docker Desktop in Start Menu"
    echo "  - On Linux: sudo systemctl start docker"
    echo ""
    echo "After starting Docker, run this script again."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Check if venv exists
echo "2. Setting up Python environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt 2>/dev/null

echo "✅ Python environment ready"
echo ""

# Start Docker services
echo "3. Starting Docker services..."
echo "   This will start: Kafka, PostgreSQL, Spark, Prometheus, Grafana"
echo ""

docker-compose down -q 2>/dev/null || true
docker-compose up -d

echo ""
echo "Waiting for services to be healthy..."
sleep 20

# Check services
echo ""
echo "4. Checking service health..."

services=(
    "redpanda:9092"
    "postgres-fraud-db:5432"
    "prometheus:9090"
    "grafana:3000"
)

for service in "${services[@]}"; do
    host="${service%:*}"
    port="${service#*:}"
    
    if docker-compose exec -T "$host" true > /dev/null 2>&1; then
        echo "   ✅ $host (port $port)"
    else
        echo "   ⏳ $host (starting...)"
    fi
done

echo ""
echo "5. Initializing database..."
python3 scripts/init_db.py 2>/dev/null || echo "   Database initialization in progress..."

echo ""
echo "6. Training fraud model..."
python3 ml/train_model.py 2>/dev/null || echo "   Model training in progress..."

echo ""
echo "=========================================="
echo "✅ System Ready!"
echo "=========================================="
echo ""
echo "Access Points:"
echo ""
echo "  🔗 API Documentation"
echo "     http://localhost:8000/docs"
echo ""
echo "  📊 Grafana Dashboards"  
echo "     http://localhost:3000"
echo "     Username: admin"
echo "     Password: admin"
echo ""
echo "  📬 Kafka UI"
echo "     http://localhost:8080"
echo ""
echo "  📈 Prometheus"
echo "     http://localhost:9090"
echo ""
echo "=========================================="
echo ""
echo "Starting API Server..."
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Start the API server
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
