"""
Kafka Producer for Generating Mock Payment Transactions

This module generates realistic payment transaction events and publishes them
to a Kafka topic for real-time processing.
"""

import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any
from kafka import KafkaProducer
from faker import Faker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

fake = Faker()


class TransactionGenerator:
    """Generates realistic payment transaction data"""
    
    MERCHANT_CATEGORIES = [
        "grocery", "restaurant", "gas_station", "online_retail", 
        "entertainment", "travel", "utilities", "healthcare"
    ]
    
    COUNTRIES = ["US", "UK", "CA", "DE", "FR", "JP", "AU", "SG"]
    
    DEVICE_TYPES = ["mobile_ios", "mobile_android", "web", "pos_terminal"]
    
    # High-risk merchants for fraud simulation
    HIGH_RISK_MERCHANTS = [
        "CryptoExchange", "GiftCardMall", "InternationalWire", 
        "OnlineGambling", "AdultContent"
    ]
    
    def __init__(self):
        self.user_profiles = self._generate_user_profiles(1000)
        
    def _generate_user_profiles(self, count: int) -> Dict[str, Dict]:
        """Generate user profiles with typical behavior patterns"""
        profiles = {}
        for _ in range(count):
            user_id = fake.uuid4()
            profiles[user_id] = {
                "home_country": random.choice(self.COUNTRIES),
                "avg_transaction_amount": random.uniform(20, 500),
                "preferred_merchants": random.sample(
                    [fake.company() for _ in range(10)], k=3
                ),
                "typical_hours": list(range(
                    random.randint(6, 10), random.randint(20, 23)
                )),
                "devices": random.sample(self.DEVICE_TYPES, k=random.randint(1, 3))
            }
        return profiles
    
    def generate_transaction(self, is_fraud: bool = False) -> Dict[str, Any]:
        """Generate a single transaction, optionally marked as fraudulent"""
        
        user_id = random.choice(list(self.user_profiles.keys()))
        profile = self.user_profiles[user_id]
        
        if is_fraud:
            # Fraudulent transaction patterns
            transaction = self._generate_fraudulent_transaction(user_id, profile)
        else:
            # Normal transaction
            transaction = self._generate_normal_transaction(user_id, profile)
        
        # Add common fields
        transaction.update({
            "transaction_id": fake.uuid4(),
            "timestamp": datetime.utcnow().isoformat(),
            "is_fraud": is_fraud,
            "processing_status": "pending"
        })
        
        return transaction
    
    def _generate_normal_transaction(self, user_id: str, profile: Dict) -> Dict:
        """Generate a normal (non-fraudulent) transaction"""
        
        # Amount follows user's typical pattern with some variance
        amount = abs(random.gauss(profile["avg_transaction_amount"], 50))
        amount = round(min(amount, 2000), 2)  # Cap at $2000
        
        merchant = random.choice(profile["preferred_merchants"])
        if random.random() < 0.3:  # 30% chance of new merchant
            merchant = fake.company()
        
        return {
            "user_id": user_id,
            "amount": amount,
            "currency": "USD",
            "merchant_id": merchant,
            "merchant_category": random.choice(self.MERCHANT_CATEGORIES),
            "country": profile["home_country"],
            "device_id": random.choice(profile["devices"]),
            "ip_address": fake.ipv4(),
            "card_last_4": fake.credit_card_number()[-4:],
            "cvv_match": True,
            "billing_zip_match": random.random() < 0.95  # 95% match
        }
    
    def _generate_fraudulent_transaction(self, user_id: str, profile: Dict) -> Dict:
        """Generate a fraudulent transaction with suspicious patterns"""
        
        fraud_type = random.choice([
            "stolen_card", "account_takeover", "friendly_fraud", "merchant_fraud"
        ])
        
        # Fraudulent patterns
        if fraud_type == "stolen_card":
            # Multiple high-value transactions in quick succession
            amount = round(random.uniform(500, 2500), 2)
            country = random.choice([c for c in self.COUNTRIES if c != profile["home_country"]])
            device_id = fake.uuid4()  # New device
            cvv_match = random.random() < 0.3  # Often CVV fails
            billing_zip_match = False
            merchant = random.choice(self.HIGH_RISK_MERCHANTS)
            
        elif fraud_type == "account_takeover":
            # Account accessed from unusual location/device
            amount = round(random.uniform(100, 1000), 2)
            country = random.choice([c for c in self.COUNTRIES if c != profile["home_country"]])
            device_id = fake.uuid4()
            cvv_match = True
            billing_zip_match = random.random() < 0.5
            merchant = fake.company()
            
        elif fraud_type == "friendly_fraud":
            # Legitimate purchase, but user will claim fraud
            amount = round(random.uniform(200, 1500), 2)
            country = profile["home_country"]
            device_id = random.choice(profile["devices"])
            cvv_match = True
            billing_zip_match = True
            merchant = random.choice(["Electronics Store", "Jewelry Shop", "Designer Outlet"])
            
        else:  # merchant_fraud
            # Merchant charging suspicious amounts
            amount = round(random.uniform(0.01, 1.00), 2)  # Micro-transaction
            country = profile["home_country"]
            device_id = random.choice(profile["devices"])
            cvv_match = True
            billing_zip_match = True
            merchant = random.choice(self.HIGH_RISK_MERCHANTS)
        
        return {
            "user_id": user_id,
            "amount": amount,
            "currency": "USD",
            "merchant_id": merchant,
            "merchant_category": random.choice(self.MERCHANT_CATEGORIES),
            "country": country,
            "device_id": device_id,
            "ip_address": fake.ipv4(),
            "card_last_4": fake.credit_card_number()[-4:],
            "cvv_match": cvv_match,
            "billing_zip_match": billing_zip_match,
            "fraud_type": fraud_type
        }


class KafkaTransactionProducer:
    """Produces transaction events to Kafka"""
    
    def __init__(self, bootstrap_servers: str = None, 
                 topic: str = None):
        bootstrap_servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
        topic = topic or os.environ.get("KAFKA_TOPIC", "payment-transactions")
        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',  # Wait for all replicas
            retries=3
        )
        self.generator = TransactionGenerator()
        logger.info(f"Kafka producer connected to {bootstrap_servers}")
    
    def produce_transactions(self, 
                           transactions_per_second: int = 10,
                           fraud_rate: float = 0.02,
                           duration_seconds: int = None):
        """
        Produce transactions at specified rate
        
        Args:
            transactions_per_second: Number of transactions to generate per second
            fraud_rate: Percentage of transactions that are fraudulent (0.02 = 2%)
            duration_seconds: How long to run (None = infinite)
        """
        
        start_time = time.time()
        count = 0
        fraud_count = 0
        
        try:
            while True:
                # Check duration
                if duration_seconds and (time.time() - start_time) > duration_seconds:
                    break
                
                # Generate batch
                batch_start = time.time()
                
                for _ in range(transactions_per_second):
                    is_fraud = random.random() < fraud_rate
                    transaction = self.generator.generate_transaction(is_fraud=is_fraud)
                    
                    # Use user_id as key for partitioning
                    key = transaction["user_id"]
                    
                    # Send to Kafka
                    self.producer.send(
                        self.topic,
                        key=key,
                        value=transaction
                    )
                    
                    count += 1
                    if is_fraud:
                        fraud_count += 1
                    
                    if count % 100 == 0:
                        logger.info(
                            f"Produced {count} transactions "
                            f"({fraud_count} fraudulent, {fraud_count/count*100:.2f}%)"
                        )
                
                # Wait to maintain rate
                elapsed = time.time() - batch_start
                sleep_time = max(0, 1 - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("Stopping transaction producer...")
        finally:
            self.producer.flush()
            self.producer.close()
            logger.info(
                f"Produced {count} total transactions "
                f"({fraud_count} fraudulent, {fraud_count/count*100:.2f}%)"
            )


def main():
    """Run the transaction producer"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate mock payment transactions")
    parser.add_argument(
        "--rate", 
        type=int, 
        default=10, 
        help="Transactions per second"
    )
    parser.add_argument(
        "--fraud-rate", 
        type=float, 
        default=0.02, 
        help="Fraud rate (0.02 = 2%%)"
    )
    parser.add_argument(
        "--duration", 
        type=int, 
        default=None, 
        help="Duration in seconds (None = infinite)"
    )
    parser.add_argument(
        "--kafka-servers", 
        type=str, 
        default="localhost:19092",
        help="Kafka bootstrap servers"
    )
    
    args = parser.parse_args()
    
    producer = KafkaTransactionProducer(bootstrap_servers=args.kafka_servers)
    producer.produce_transactions(
        transactions_per_second=args.rate,
        fraud_rate=args.fraud_rate,
        duration_seconds=args.duration
    )


if __name__ == "__main__":
    main()
