"""
Fraud Scorer - Core Fraud Detection Logic

Orchestrates feature retrieval, A/B model selection, model inference, and
decision making. Models are sourced from the Postgres-backed model registry:
the production "champion" serves most traffic, and an optional "challenger"
serves a configurable share for online A/B evaluation.
"""

import os
import time
import uuid
from typing import Dict, Any, Optional
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from ml.train_model import FraudDetectionModel
from ml.registry import ModelRegistry, STAGE_PRODUCTION
from ml.ab_router import ABRouter
from feature_store.store import get_feature_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FraudScorer:
    """Real-time fraud scoring engine with registry-backed A/B serving."""

    # Decision thresholds
    THRESHOLD_HIGH_RISK = 0.8      # Auto-decline
    THRESHOLD_MEDIUM_RISK = 0.5    # Manual review
    THRESHOLD_LOW_RISK = 0.2       # Monitor

    def __init__(self, model_version: str = None):
        """Initialize fraud scorer with the registry-backed A/B router."""

        self.registry = ModelRegistry()
        self._cold_start_if_empty()
        self.router = ABRouter(registry=self.registry)

        self.feature_store = get_feature_store()

        # In-memory metrics (fast path; authoritative numbers come from DB)
        self.predictions_count = 0
        self.total_fraud_score = 0.0
        self.decisions = {"approve": 0, "review": 0, "decline": 0}

    def _cold_start_if_empty(self):
        """Train and register a production model if the registry is empty."""
        try:
            if not self.registry.is_empty():
                return
        except Exception as e:
            logger.error(f"Registry unavailable ({e}); cannot cold-start")
            raise

        logger.warning("Model registry is empty. Training initial production model...")
        model = FraudDetectionModel()
        df = model.generate_synthetic_data(n_samples=10000)
        model.train(df, register=True, register_stage=STAGE_PRODUCTION)
        logger.info(f"Cold-start model {model.model_version} registered as production")

    # ------------------------------------------------------------------
    # Champion accessors (kept for API/health backward compatibility)
    # ------------------------------------------------------------------
    @property
    def model(self):
        return self.router.champion_model.model if self.router.champion_model else None

    @property
    def model_version(self):
        return self.router.champion_version

    def load_model(self, version: str = None):
        """Refresh the router from the registry (used by /model/reload and
        after drift rollbacks / promotions)."""
        self.router.refresh()
        logger.info(f"Router refreshed. Champion: {self.router.champion_version}")

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def score_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Score a transaction for fraud, routing through the A/B router."""

        transaction_id = str(uuid.uuid4())
        user_id = transaction_data["user_id"]

        # Select champion or challenger for this user
        model, role, version, experiment_id = self.router.select(user_id)

        # Feature retrieval
        feature_start = time.time()
        features = self.feature_store.get_online_features(user_id, transaction_data)
        feature_retrieval_time_ms = int((time.time() - feature_start) * 1000)

        # Model inference
        inference_start = time.time()
        prediction = model.predict(features)
        inference_time_ms = int((time.time() - inference_start) * 1000)

        fraud_score = prediction["fraud_probability"]

        # Make decision
        decision, risk_level = self._make_decision(fraud_score)

        # Identify risk factors
        reasons = self._identify_risk_factors(features, fraud_score)

        # Update in-memory metrics
        self.predictions_count += 1
        self.total_fraud_score += fraud_score
        self.decisions[decision] += 1

        result = {
            "transaction_id": transaction_id,
            "fraud_score": fraud_score,
            "decision": decision,
            "risk_level": risk_level,
            "model_version": version,
            "model_role": role,
            "experiment_id": experiment_id,
            "reasons": reasons,
            "feature_retrieval_time_ms": feature_retrieval_time_ms,
            "model_inference_time_ms": inference_time_ms,
            "features": features,  # For logging
        }

        logger.info(
            f"Scored {transaction_id}: score={fraud_score:.4f}, decision={decision}, "
            f"model={version}({role}), latency={feature_retrieval_time_ms + inference_time_ms}ms"
        )

        return result

    def _make_decision(self, fraud_score: float) -> tuple:
        """Make approval/decline decision based on fraud score."""

        if fraud_score >= self.THRESHOLD_HIGH_RISK:
            return "decline", "critical"
        elif fraud_score >= self.THRESHOLD_MEDIUM_RISK:
            return "review", "high"
        elif fraud_score >= self.THRESHOLD_LOW_RISK:
            return "approve", "medium"
        else:
            return "approve", "low"

    def _identify_risk_factors(self, features: Dict[str, Any], fraud_score: float) -> list:
        """Identify key risk factors contributing to fraud score."""

        reasons = []

        # High velocity
        if features.get("velocity_txn_count_1h", 0) > 5:
            reasons.append("High transaction velocity (>5 txns/hour)")

        # Large amount deviation
        if features.get("amount_deviation_from_avg", 0) > 100:
            reasons.append("Transaction amount significantly above user average")

        # New country
        if features.get("is_new_country", 0) == 1:
            reasons.append("Transaction from new country")

        # New device
        if features.get("is_new_device", 0) == 1:
            reasons.append("Transaction from new device")

        # CVV mismatch
        if features.get("cvv_match", 1) == 0:
            reasons.append("CVV verification failed")

        # Billing zip mismatch
        if features.get("billing_zip_match", 1) == 0:
            reasons.append("Billing ZIP code mismatch")

        # High-risk merchant
        if features.get("merchant_fraud_rate_24h", 0) > 0.1:
            reasons.append("High-risk merchant (>10% fraud rate)")

        # High-risk device
        if features.get("device_is_high_risk", 0) == 1:
            reasons.append("High-risk device detected")

        # Night transaction
        if features.get("is_night_txn", 0) == 1 and fraud_score > 0.3:
            reasons.append("Unusual transaction time (late night)")

        # New user
        if features.get("behavioral_account_age_days", 0) < 7:
            reasons.append("New account (<7 days old)")

        # Unverified account
        if features.get("behavioral_is_verified", 1) == 0 and fraud_score > 0.4:
            reasons.append("Unverified account")

        # Historical fraud
        if features.get("behavioral_fraud_count", 0) > 0:
            reasons.append("Previous fraudulent transactions on account")

        # If high score but no specific reasons identified
        if not reasons and fraud_score > 0.5:
            reasons.append("Multiple minor risk factors detected")

        return reasons[:5]  # Return top 5 reasons

    def log_prediction(self, transaction_data: Dict[str, Any], result: Dict[str, Any]):
        """Log prediction to database for monitoring, A/B analysis, and drift."""

        try:
            import psycopg2
            import json

            conn = psycopg2.connect(
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5433")),
                database=os.environ.get("DB_NAME", "fraud_detection"),
                user=os.environ.get("DB_USER", "frauduser"),
                password=os.environ.get("DB_PASSWORD", "fraudpass123"),
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_predictions (
                        transaction_id, model_version, model_role, experiment_id,
                        fraud_probability, predicted_fraud, decision, features,
                        prediction_latency_ms, feature_retrieval_latency_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        result["transaction_id"],
                        result["model_version"],
                        result.get("model_role"),
                        result.get("experiment_id"),
                        result["fraud_score"],
                        result["fraud_score"] > 0.5,
                        result["decision"],
                        json.dumps(result["features"]),
                        result["model_inference_time_ms"],
                        result["feature_retrieval_time_ms"],
                    ),
                )
                conn.commit()

            conn.close()

        except Exception as e:
            logger.error(f"Failed to log prediction: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Get current model performance metrics (authoritative, from DB)."""

        champion = self.router.champion_version
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5433")),
                database=os.environ.get("DB_NAME", "fraud_detection"),
                user=os.environ.get("DB_USER", "frauduser"),
                password=os.environ.get("DB_PASSWORD", "fraudpass123"),
            )
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                        AS total,
                        AVG(fraud_probability)                          AS avg_score,
                        AVG(CASE WHEN predicted_fraud THEN 1 ELSE 0 END) AS fraud_rate,
                        AVG(prediction_latency_ms + feature_retrieval_latency_ms) AS avg_latency,
                        COUNT(*) FILTER (WHERE decision = 'approve')     AS approve,
                        COUNT(*) FILTER (WHERE decision = 'review')      AS review,
                        COUNT(*) FILTER (WHERE decision = 'decline')     AS decline
                    FROM model_predictions
                    WHERE model_version = %s
                    """,
                    (champion,),
                )
                row = cur.fetchone()
            conn.close()

            if row and row["total"]:
                return {
                    "model_version": champion,
                    "total_predictions": int(row["total"]),
                    "fraud_rate": float(row["fraud_rate"] or 0.0),
                    "avg_score": float(row["avg_score"] or 0.0),
                    "avg_latency_ms": float(row["avg_latency"] or 0.0),
                    "decisions": {
                        "approve": int(row["approve"]),
                        "review": int(row["review"]),
                        "decline": int(row["decline"]),
                    },
                }
        except Exception as e:
            logger.error(f"Failed to read metrics from DB, using in-memory: {e}")

        # Fallback to in-memory counters
        avg_score = self.total_fraud_score / max(self.predictions_count, 1)
        return {
            "model_version": champion,
            "total_predictions": self.predictions_count,
            "fraud_rate": avg_score,
            "avg_score": avg_score,
            "avg_latency_ms": 0.0,
            "decisions": self.decisions,
        }
