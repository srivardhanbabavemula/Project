# Load test

Reproduces the throughput and latency figures quoted in the project README.

## Running it

```bash
# 1. Postgres
docker compose up -d postgres
docker exec -i postgres-fraud-db psql -U frauduser -d fraud_detection < feature_store/schema.sql

# 2. A model (synthetic data; registers as production)
export DB_HOST=localhost DB_PORT=5433 DB_NAME=fraud_detection \
       DB_USER=frauduser DB_PASSWORD=fraudpass123
python -m ml.train_model --samples 50000 --stage production

# 3. The API, 4 workers
python -m uvicorn api.main:app --host 127.0.0.1 --port 8100 --workers 4

# 4. The load test
locust -f load_test/locustfile.py --host http://127.0.0.1:8100 \
       --users 80 --spawn-rate 20 --run-time 10m --headless \
       --csv load_test/results
```

`results_stats.csv` is committed so the numbers can be checked without re-running.

## What the test sends

Realistic varied transactions rather than one repeated payload: 500 users, 120
merchants and 400 devices drawn at random, with log-normal amounts and a small
rate of CVV and billing-zip mismatches. The user pool is fixed rather than
random per request, so the feature store sees repeat users the way production
would instead of a cache miss every time.

20 scoring calls per health check, matching the real traffic mix.

## Caveats, stated plainly

These are single-machine numbers: the API, Postgres in Docker and Locust all on
one laptop. They measure whether the service holds up under sustained
concurrency, not what it would do on production hardware with a tuned connection
pool. Throughput is bounded by Postgres feature-store reads well before the
XGBoost call, which is why worker count matters more than model latency.
