#!/usr/bin/env python3
"""
Database Initialization Script for Fraud Detection System
Generates seed data for user behavioral profiles
"""
import psycopg2
import uuid
from datetime import datetime, timedelta
import random
import time
import sys

def wait_for_postgres(max_retries=30):
    """Wait for PostgreSQL to be ready"""
    print("Waiting for PostgreSQL to be ready...")
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(
                host="localhost",
                port=5433,
                database="fraud_detection",
                user="frauduser",
                password="fraudpass123",
                connect_timeout=3
            )
            conn.close()
            print("✓ PostgreSQL is ready!")
            return True
        except psycopg2.OperationalError:
            print(".", end="", flush=True)
            time.sleep(1)
    
    print("\n✗ PostgreSQL is not ready after {} seconds".format(max_retries))
    return False

def initialize_seed_data():
    """Generate initial seed data for user behavioral profiles"""
    print("\nGenerating seed data...")
    
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        database="fraud_detection",
        user="frauduser",
        password="fraudpass123"
    )
    
    cur = conn.cursor()
    
    # Create user behavioral profiles (100 users)
    print("Creating user behavioral profiles...")
    user_ids = [str(uuid.uuid4()) for _ in range(100)]
    
    for user_id in user_ids:
        avg_amount_30d = random.uniform(50, 500)
        total_txns_30d = random.randint(10, 200)
        unique_merchants = random.randint(5, 30)
        unique_countries = random.randint(1, 5)
        unique_devices = random.randint(1, 3)
        home_country = random.choice(['US', 'UK', 'CA', 'DE', 'FR', 'JP', 'AU'])
        account_age = random.randint(30, 1000)
        is_verified = random.choice([True, True, True, False])
        
        cur.execute("""
            INSERT INTO user_behavioral_features 
            (user_id, avg_transaction_amount_30d, total_transactions_30d, 
             unique_merchants_30d, unique_countries_30d, unique_devices_30d,
             home_country, account_age_days, is_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
        """, (
            user_id,
            avg_amount_30d,
            total_txns_30d,
            unique_merchants,
            unique_countries,
            unique_devices,
            home_country,
            account_age,
            is_verified
        ))
    
    conn.commit()
    print(f"✓ Created {len(user_ids)} user profiles")
    
    # Create merchant features
    print("Creating merchant features...")
    merchant_ids = [f"merchant_{i:04d}" for i in range(50)]
    
    for merchant_id in merchant_ids:
        window_end = datetime.now()
        txn_count = random.randint(10, 500)
        avg_amount = random.uniform(20, 1000)
        fraud_count = random.randint(0, int(txn_count * 0.05))
        fraud_rate = fraud_count / txn_count if txn_count > 0 else 0
        risk_category = 'high' if fraud_rate > 0.03 else ('medium' if fraud_rate > 0.01 else 'low')
        
        cur.execute("""
            INSERT INTO merchant_features
            (merchant_id, window_end, merchant_txn_count_24h, merchant_avg_amount_24h,
             merchant_fraud_count_24h, merchant_fraud_rate_24h, risk_category)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (merchant_id, window_end) DO NOTHING
        """, (
            merchant_id,
            window_end,
            txn_count,
            avg_amount,
            fraud_count,
            fraud_rate,
            risk_category
        ))
    
    conn.commit()
    print(f"✓ Created {len(merchant_ids)} merchant profiles")
    
    # Create device features
    print("Creating device features...")
    device_ids = [str(uuid.uuid4()) for _ in range(200)]
    
    for device_id in device_ids:
        device_type = random.choice(['mobile', 'desktop', 'tablet'])
        first_seen = datetime.now() - timedelta(days=random.randint(1, 365))
        last_seen = datetime.now() - timedelta(days=random.randint(0, 7))
        total_txns = random.randint(1, 100)
        total_users_count = random.randint(1, 3)
        fraud_count_val = random.randint(0, int(total_txns * 0.1))
        fraud_rate_val = fraud_count_val / total_txns if total_txns > 0 else 0
        is_high_risk = fraud_rate_val > 0.05
        
        cur.execute("""
            INSERT INTO device_features
            (device_id, device_type, first_seen, last_seen, total_transactions,
             total_users, fraud_count, fraud_rate, is_high_risk)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (device_id) DO NOTHING
        """, (
            device_id,
            device_type,
            first_seen,
            last_seen,
            total_txns,
            total_users_count,
            fraud_count_val,
            fraud_rate_val,
            is_high_risk
        ))
    
    conn.commit()
    print(f"✓ Created {len(device_ids)} device profiles")
    
    cur.close()
    conn.close()
    print("\n✓ Database initialization complete!")
    print(f"  - {len(user_ids)} users")
    print(f"  - {len(merchant_ids)} merchants")
    print(f"  - {len(device_ids)} devices")

def main():
    """Main initialization function"""
    print("=" * 60)
    print("Fraud Detection Database Initialization")
    print("=" * 60)
    
    if not wait_for_postgres():
        sys.exit(1)
    
    try:
        initialize_seed_data()
        print("\n" + "=" * 60)
        print("SUCCESS: Database is ready for fraud detection!")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ Error during initialization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
