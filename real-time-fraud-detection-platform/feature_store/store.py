"""
Feature Store Implementation

Handles online/offline feature retrieval with low latency for fraud detection.
"""

import os
import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor, execute_values
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime, timedelta
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeatureStore:
    """PostgreSQL-backed feature store for fraud detection"""
    
    def __init__(self, 
                 host: str = None,
                 port: int = None,
                 database: str = None,
                 user: str = None,
                 password: str = None):
        
        host = host or os.environ.get("DB_HOST", "localhost")
        port = port or int(os.environ.get("DB_PORT", "5433"))
        database = database or os.environ.get("DB_NAME", "fraud_detection")
        user = user or os.environ.get("DB_USER", "frauduser")
        password = password or os.environ.get("DB_PASSWORD", "fraudpass123")
        
        self.connection_params = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password
        }
        
        self._conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self._conn = psycopg2.connect(**self.connection_params)
            logger.info("Connected to feature store database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _ensure_connection(self):
        """Ensure connection is alive"""
        if self._conn is None or self._conn.closed:
            self._connect()
    
    def get_online_features(self, user_id: str, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve online features for real-time fraud scoring
        
        Args:
            user_id: User identifier
            transaction_data: Current transaction details
        
        Returns:
            Dictionary of features for model inference
        """
        
        self._ensure_connection()

        # A failed statement leaves psycopg2 in an aborted transaction, and every
        # later query on the same pooled connection then dies with "current
        # transaction is aborted". One malformed request would take the scorer
        # down until restart. Clear any aborted state before reading.
        try:
            if self._conn.get_transaction_status() not in (
                psycopg2.extensions.TRANSACTION_STATUS_IDLE,
                psycopg2.extensions.TRANSACTION_STATUS_UNKNOWN,
            ):
                self._conn.rollback()
        except Exception:  # a dead connection is re-made by _ensure_connection
            self._conn.rollback()

        features = {}
        
        # Get velocity features
        velocity_features = self._get_velocity_features(user_id)
        features.update(velocity_features)
        
        # Get behavioral features
        behavioral_features = self._get_behavioral_features(user_id)
        features.update(behavioral_features)
        
        # Get merchant features
        merchant_features = self._get_merchant_features(transaction_data.get("merchant_id"))
        features.update(merchant_features)
        
        # Get device features
        device_features = self._get_device_features(transaction_data.get("device_id"))
        features.update(device_features)
        
        # Add transaction-level features
        features.update(self._compute_transaction_features(user_id, transaction_data))
        
        logger.debug(f"Retrieved {len(features)} features for user {user_id}")
        return features
    
    def _get_velocity_features(self, user_id: str) -> Dict[str, Any]:
        """Get user velocity features from most recent window"""
        
        query = """
        SELECT 
            txn_count_1h,
            total_amount_1h,
            avg_amount_1h,
            stddev_amount_1h,
            max_amount_1h
        FROM user_velocity_features
        WHERE user_id = %s
        ORDER BY window_end DESC
        LIMIT 1
        """
        
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (user_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    "velocity_txn_count_1h": result.get("txn_count_1h", 0),
                    "velocity_total_amount_1h": float(result.get("total_amount_1h", 0.0)),
                    "velocity_avg_amount_1h": float(result.get("avg_amount_1h", 0.0)),
                    "velocity_stddev_amount_1h": float(result.get("stddev_amount_1h", 0.0)),
                    "velocity_max_amount_1h": float(result.get("max_amount_1h", 0.0))
                }
            else:
                # No history - return defaults (new user)
                return {
                    "velocity_txn_count_1h": 0,
                    "velocity_total_amount_1h": 0.0,
                    "velocity_avg_amount_1h": 0.0,
                    "velocity_stddev_amount_1h": 0.0,
                    "velocity_max_amount_1h": 0.0
                }
    
    def _get_behavioral_features(self, user_id: str) -> Dict[str, Any]:
        """Get user behavioral features"""
        
        query = """
        SELECT 
            avg_transaction_amount_30d,
            total_transactions_30d,
            unique_merchants_30d,
            unique_countries_30d,
            unique_devices_30d,
            account_age_days,
            is_verified,
            fraud_count_historical,
            user_risk_score
        FROM user_behavioral_features
        WHERE user_id = %s
        """
        
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (user_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    "behavioral_avg_amount_30d": float(result.get("avg_transaction_amount_30d", 0.0)),
                    "behavioral_total_txns_30d": result.get("total_transactions_30d", 0),
                    "behavioral_unique_merchants_30d": result.get("unique_merchants_30d", 0),
                    "behavioral_unique_countries_30d": result.get("unique_countries_30d", 1),
                    "behavioral_unique_devices_30d": result.get("unique_devices_30d", 1),
                    "behavioral_account_age_days": result.get("account_age_days", 0),
                    "behavioral_is_verified": int(result.get("is_verified", False)),
                    "behavioral_fraud_count": result.get("fraud_count_historical", 0),
                    "behavioral_user_risk_score": float(result.get("user_risk_score", 0.5))
                }
            else:
                # New user defaults
                return {
                    "behavioral_avg_amount_30d": 0.0,
                    "behavioral_total_txns_30d": 0,
                    "behavioral_unique_merchants_30d": 0,
                    "behavioral_unique_countries_30d": 1,
                    "behavioral_unique_devices_30d": 1,
                    "behavioral_account_age_days": 0,
                    "behavioral_is_verified": 0,
                    "behavioral_fraud_count": 0,
                    "behavioral_user_risk_score": 0.5
                }
    
    def _get_merchant_features(self, merchant_id: str) -> Dict[str, Any]:
        """Get merchant features"""
        
        if not merchant_id:
            return {
                "merchant_txn_count_24h": 0,
                "merchant_avg_amount_24h": 0.0,
                "merchant_fraud_rate_24h": 0.0
            }
        
        query = """
        SELECT 
            merchant_txn_count_24h,
            merchant_avg_amount_24h,
            merchant_fraud_rate_24h
        FROM merchant_features
        WHERE merchant_id = %s
        ORDER BY window_end DESC
        LIMIT 1
        """
        
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (merchant_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    "merchant_txn_count_24h": result.get("merchant_txn_count_24h", 0),
                    "merchant_avg_amount_24h": float(result.get("merchant_avg_amount_24h", 0.0)),
                    "merchant_fraud_rate_24h": float(result.get("merchant_fraud_rate_24h", 0.0))
                }
            else:
                return {
                    "merchant_txn_count_24h": 0,
                    "merchant_avg_amount_24h": 0.0,
                    "merchant_fraud_rate_24h": 0.0
                }
    
    def _get_device_features(self, device_id: str) -> Dict[str, Any]:
        """Get device features"""
        
        if not device_id:
            return {
                "device_total_txns": 0,
                "device_fraud_rate": 0.0,
                "device_is_high_risk": 0
            }
        
        query = """
        SELECT 
            total_transactions,
            fraud_rate,
            is_high_risk
        FROM device_features
        WHERE device_id = %s
        """
        
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (device_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    "device_total_txns": result.get("total_transactions", 0),
                    "device_fraud_rate": float(result.get("fraud_rate", 0.0)),
                    "device_is_high_risk": int(result.get("is_high_risk", False))
                }
            else:
                return {
                    "device_total_txns": 0,
                    "device_fraud_rate": 0.0,
                    "device_is_high_risk": 0
                }
    
    def _compute_transaction_features(self, user_id: str, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute features from transaction data itself"""
        
        # Get user's recent transaction history
        query = """
        SELECT 
            amount,
            country,
            device_id,
            merchant_id,
            timestamp
        FROM transactions
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT 10
        """
        
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (user_id,))
            recent_txns = cur.fetchall()
        
        features = {}
        
        # Current transaction amount
        current_amount = transaction_data.get("amount", 0)
        features["txn_amount"] = float(current_amount)
        
        # Amount deviation from user average
        if recent_txns:
            avg_recent_amount = sum(float(t["amount"]) for t in recent_txns) / len(recent_txns)
            features["amount_deviation_from_avg"] = float(current_amount - avg_recent_amount)
            
            # New country flag
            recent_countries = set(t["country"] for t in recent_txns if t["country"])
            features["is_new_country"] = int(
                transaction_data.get("country") not in recent_countries
            )
            
            # New device flag
            recent_devices = set(t["device_id"] for t in recent_txns if t["device_id"])
            features["is_new_device"] = int(
                transaction_data.get("device_id") not in recent_devices
            )
            
            # New merchant flag
            recent_merchants = set(t["merchant_id"] for t in recent_txns if t["merchant_id"])
            features["is_new_merchant"] = int(
                transaction_data.get("merchant_id") not in recent_merchants
            )
        else:
            features["amount_deviation_from_avg"] = 0.0
            features["is_new_country"] = 1
            features["is_new_device"] = 1
            features["is_new_merchant"] = 1
        
        # Binary features
        features["cvv_match"] = int(transaction_data.get("cvv_match", False))
        features["billing_zip_match"] = int(transaction_data.get("billing_zip_match", False))
        
        # Time features
        if "timestamp" in transaction_data:
            ts = transaction_data["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            features["hour_of_day"] = ts.hour
            features["day_of_week"] = ts.weekday()
            features["is_weekend"] = int(ts.weekday() >= 5)
            features["is_night_txn"] = int(0 <= ts.hour <= 6)
        
        return features
    
    def write_features(self, feature_data: Dict[str, Any], table_name: str):
        """Write features to the feature store"""
        
        self._ensure_connection()
        
        if not feature_data:
            return
        
        columns = list(feature_data.keys())
        values = list(feature_data.values())
        
        placeholders = ", ".join(["%s"] * len(columns))
        column_names = ", ".join(columns)
        
        query = f"""
        INSERT INTO {table_name} ({column_names})
        VALUES ({placeholders})
        ON CONFLICT DO NOTHING
        """
        
        with self._conn.cursor() as cur:
            cur.execute(query, values)
            self._conn.commit()
    
    def get_feature_freshness(self) -> Dict[str, Any]:
        """Check how fresh the data is in the feature store tables."""
        self._ensure_connection()
        freshness = {}
        
        queries = {
            "user_velocity": "SELECT MAX(window_end) FROM user_velocity_features",
            "merchant_features": "SELECT MAX(window_end) FROM merchant_features",
            "transactions": "SELECT MAX(timestamp) FROM transactions"
        }
        
        with self._conn.cursor() as cur:
            for key, query in queries.items():
                try:
                    cur.execute(query)
                    result = cur.fetchone()
                    freshness[key] = result[0].isoformat() if result and result[0] else None
                except Exception as e:
                    logger.warning(f"Could not get freshness for {key}: {e}")
                    self._conn.rollback()
                    freshness[key] = None
        
        return freshness
    
    def close(self):
        """Close database connection"""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("Feature store connection closed")


# Singleton instance
_feature_store_instance = None

def get_feature_store() -> FeatureStore:
    """Get or create feature store singleton"""
    global _feature_store_instance
    if _feature_store_instance is None:
        _feature_store_instance = FeatureStore()
    return _feature_store_instance
