#!/bin/bash

# =====================================================
# Database Initialization Script
# =====================================================

echo "Initializing fraud detection database..."

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until docker exec postgres-fraud-db pg_isready -U frauduser -d fraud_detection > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done

echo ""
echo "PostgreSQL is ready!"

# Check if schema is already initialized
TABLES_EXIST=$(docker exec postgres-fraud-db psql -U frauduser -d fraud_detection -tAc \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='transactions';")

if [ "$TABLES_EXIST" = "1" ]; then
    echo "Database already initialized."
else
    echo "Initializing schema..."
    docker exec -i postgres-fraud-db psql -U frauduser -d fraud_detection < feature_store/schema.sql
    echo "Schema initialized successfully!"
fi

# Generate some initial seed data
echo ""
echo "Generating seed data..."
python3 - <<EOF
import psycopg2
import uuid
from datetime import datetime, timedelta
import random

conn = psycopg2.connect(
    host="localhost",
    port=5433,
    database="fraud_detection",
    user="frauduser",
    password="fraudpass123"
)

cur = conn.cursor()

# Create some user behavioral profiles
users = []
for i in range(100):
    user_id = str(uuid.uuid4())
    users.append(user_id)
    
    cur.execute("""
        INSERT INTO user_behavioral_features (
            user_id, avg_transaction_amount_30d, total_transactions_30d,
            unique_merchants_30d, unique_countries_30d, unique_devices_30d,
            home_country, account_age_days, is_verified, user_risk_score
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (
        user_id,
        random.uniform(20, 200),
        random.randint(10, 100),
        random.randint(5, 20),
        random.randint(1, 3),
        random.randint(1, 3),
        random.choice(['US', 'UK', 'CA', 'DE']),
        random.randint(30, 1000),
        random.choice([True, False]),
        random.uniform(0.1, 0.5)
    ))

conn.commit()
cur.close()
conn.close()

print(f"Created {len(users)} user profiles")
EOF

echo ""
echo "Database initialization complete!"
