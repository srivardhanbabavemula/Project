"""Load test for the Fraud Guard scoring API.

Run the API and Postgres first, then:

    locust -f load_test/locustfile.py --host http://127.0.0.1:8100 \
           --users 100 --spawn-rate 20 --run-time 10m --headless \
           --csv load_test/results

The point of this file is that the numbers in the README are reproducible. It
sends realistic, varied transactions rather than one cached payload, so the
feature-store reads and the model call are both genuinely exercised.
"""

import random
import uuid

from locust import HttpUser, between, task

COUNTRIES = ["US", "GB", "CA", "DE", "IN", "BR", "NG", "SG"]
CATEGORIES = ["grocery", "electronics", "travel", "gaming", "fuel", "pharmacy"]

# A fixed pool, so the feature store sees repeat users the way production would
# rather than a fresh cache miss on every single request.
USERS = [str(uuid.uuid4()) for _ in range(500)]
MERCHANTS = [str(uuid.uuid4()) for _ in range(120)]
DEVICES = [str(uuid.uuid4()) for _ in range(400)]


def transaction() -> dict:
    return {
        "user_id": random.choice(USERS),
        "amount": round(random.lognormvariate(3.6, 1.1), 2),
        "currency": "USD",
        "merchant_id": random.choice(MERCHANTS),
        "merchant_category": random.choice(CATEGORIES),
        "country": random.choice(COUNTRIES),
        "device_id": random.choice(DEVICES),
        "cvv_match": random.random() > 0.05,
        "billing_zip_match": random.random() > 0.08,
    }


class Scorer(HttpUser):
    wait_time = between(0.05, 0.25)

    @task(20)
    def score(self):
        with self.client.post("/score", json=transaction(), catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
            elif not (0.0 <= r.json().get("fraud_score", -1) <= 1.0):
                r.failure("fraud_score outside [0,1]")

    @task(1)
    def health(self):
        self.client.get("/health")
