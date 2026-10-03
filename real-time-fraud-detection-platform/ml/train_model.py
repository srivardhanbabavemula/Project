"""
XGBoost Fraud Detection Model Training

Trains a gradient boosting model to detect fraudulent transactions.
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score, 
    precision_recall_curve, average_precision_score
)
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
from imblearn.pipeline import Pipeline as ImbPipeline
import xgboost as xgb
import joblib
import json
from datetime import datetime
import logging
import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

# Allow `python ml/train_model.py` and `from ml.train_model import ...` alike
sys.path.append(str(Path(__file__).parent.parent))
from ml.registry import ModelRegistry, STAGE_STAGING, STAGE_PRODUCTION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FraudDetectionModel:
    """XGBoost model for fraud detection"""
    
    # Feature names expected by the model
    FEATURE_COLUMNS = [
        # Velocity features
        "velocity_txn_count_1h",
        "velocity_total_amount_1h",
        "velocity_avg_amount_1h",
        "velocity_stddev_amount_1h",
        "velocity_max_amount_1h",
        
        # Behavioral features
        "behavioral_avg_amount_30d",
        "behavioral_total_txns_30d",
        "behavioral_unique_merchants_30d",
        "behavioral_unique_countries_30d",
        "behavioral_unique_devices_30d",
        "behavioral_account_age_days",
        "behavioral_is_verified",
        "behavioral_fraud_count",
        "behavioral_user_risk_score",
        
        # Merchant features
        "merchant_txn_count_24h",
        "merchant_avg_amount_24h",
        "merchant_fraud_rate_24h",
        
        # Device features
        "device_total_txns",
        "device_fraud_rate",
        "device_is_high_risk",
        
        # Transaction features
        "txn_amount",
        "amount_deviation_from_avg",
        "is_new_country",
        "is_new_device",
        "is_new_merchant",
        "cvv_match",
        "billing_zip_match",
        "hour_of_day",
        "day_of_week",
        "is_weekend",
        "is_night_txn"
    ]
    
    def __init__(self, model_dir: str = "ml/models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self.model = None
        self.model_version = None
        self.feature_importance = None
        self.metrics = {}
        self.artifact_path = None
        self.reference_data_path = None
    
    def load_data_from_db(self, 
                         connection_params: dict,
                         limit: int = None) -> pd.DataFrame:
        """Load training data from PostgreSQL"""
        
        conn = psycopg2.connect(**connection_params)
        
        query = """
        SELECT 
            t.*,
            v.txn_count_1h as velocity_txn_count_1h,
            v.total_amount_1h as velocity_total_amount_1h,
            v.avg_amount_1h as velocity_avg_amount_1h,
            v.stddev_amount_1h as velocity_stddev_amount_1h,
            v.max_amount_1h as velocity_max_amount_1h
        FROM transactions t
        LEFT JOIN user_velocity_features v ON t.user_id = v.user_id
        WHERE t.is_fraud IS NOT NULL
        ORDER BY t.timestamp DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        df = pd.read_sql(query, conn)
        conn.close()
        
        logger.info(f"Loaded {len(df)} transactions from database")
        return df
    
    def generate_synthetic_data(self, n_samples: int = 10000, fraud_rate: float = 0.02) -> pd.DataFrame:
        """Generate synthetic training data for demo purposes"""
        
        np.random.seed(42)
        
        n_fraud = int(n_samples * fraud_rate)
        n_legitimate = n_samples - n_fraud
        
        # Generate legitimate transactions
        legitimate_data = {
            "velocity_txn_count_1h": np.random.poisson(2, n_legitimate),
            "velocity_total_amount_1h": np.random.gamma(2, 50, n_legitimate),
            "velocity_avg_amount_1h": np.random.gamma(2, 25, n_legitimate),
            "velocity_stddev_amount_1h": np.random.gamma(1, 10, n_legitimate),
            "velocity_max_amount_1h": np.random.gamma(3, 30, n_legitimate),
            
            "behavioral_avg_amount_30d": np.random.gamma(2, 30, n_legitimate),
            "behavioral_total_txns_30d": np.random.poisson(50, n_legitimate),
            "behavioral_unique_merchants_30d": np.random.poisson(10, n_legitimate),
            "behavioral_unique_countries_30d": np.random.binomial(3, 0.3, n_legitimate) + 1,
            "behavioral_unique_devices_30d": np.random.binomial(3, 0.5, n_legitimate) + 1,
            "behavioral_account_age_days": np.random.exponential(365, n_legitimate).astype(int),
            "behavioral_is_verified": np.random.binomial(1, 0.8, n_legitimate),
            "behavioral_fraud_count": np.random.binomial(1, 0.01, n_legitimate),
            "behavioral_user_risk_score": np.random.beta(2, 10, n_legitimate),
            
            "merchant_txn_count_24h": np.random.poisson(100, n_legitimate),
            "merchant_avg_amount_24h": np.random.gamma(2, 40, n_legitimate),
            "merchant_fraud_rate_24h": np.random.beta(1, 50, n_legitimate),
            
            "device_total_txns": np.random.poisson(30, n_legitimate),
            "device_fraud_rate": np.random.beta(1, 50, n_legitimate),
            "device_is_high_risk": np.random.binomial(1, 0.05, n_legitimate),
            
            "txn_amount": np.random.gamma(2, 30, n_legitimate),
            "amount_deviation_from_avg": np.random.normal(0, 20, n_legitimate),
            "is_new_country": np.random.binomial(1, 0.1, n_legitimate),
            "is_new_device": np.random.binomial(1, 0.15, n_legitimate),
            "is_new_merchant": np.random.binomial(1, 0.3, n_legitimate),
            "cvv_match": np.random.binomial(1, 0.98, n_legitimate),
            "billing_zip_match": np.random.binomial(1, 0.95, n_legitimate),
            "hour_of_day": np.random.randint(6, 23, n_legitimate),
            "day_of_week": np.random.randint(0, 7, n_legitimate),
            "is_weekend": np.random.binomial(1, 2/7, n_legitimate),
            "is_night_txn": np.random.binomial(1, 0.1, n_legitimate),
            
            "is_fraud": np.zeros(n_legitimate, dtype=int)
        }
        
        # Generate fraudulent transactions (different distributions)
        fraud_data = {
            "velocity_txn_count_1h": np.random.poisson(5, n_fraud),  # Higher velocity
            "velocity_total_amount_1h": np.random.gamma(4, 100, n_fraud),  # Higher amounts
            "velocity_avg_amount_1h": np.random.gamma(4, 50, n_fraud),
            "velocity_stddev_amount_1h": np.random.gamma(2, 20, n_fraud),
            "velocity_max_amount_1h": np.random.gamma(5, 60, n_fraud),
            
            "behavioral_avg_amount_30d": np.random.gamma(2, 25, n_fraud),
            "behavioral_total_txns_30d": np.random.poisson(40, n_fraud),
            "behavioral_unique_merchants_30d": np.random.poisson(8, n_fraud),
            "behavioral_unique_countries_30d": np.random.binomial(5, 0.5, n_fraud) + 1,
            "behavioral_unique_devices_30d": np.random.binomial(4, 0.6, n_fraud) + 1,
            "behavioral_account_age_days": np.random.exponential(180, n_fraud).astype(int),  # Younger accounts
            "behavioral_is_verified": np.random.binomial(1, 0.3, n_fraud),  # Less verified
            "behavioral_fraud_count": np.random.binomial(2, 0.3, n_fraud),
            "behavioral_user_risk_score": np.random.beta(5, 5, n_fraud),  # Higher risk
            
            "merchant_txn_count_24h": np.random.poisson(50, n_fraud),
            "merchant_avg_amount_24h": np.random.gamma(3, 50, n_fraud),
            "merchant_fraud_rate_24h": np.random.beta(3, 10, n_fraud),  # Higher fraud rate
            
            "device_total_txns": np.random.poisson(10, n_fraud),  # Newer devices
            "device_fraud_rate": np.random.beta(3, 10, n_fraud),  # Higher device fraud
            "device_is_high_risk": np.random.binomial(1, 0.4, n_fraud),
            
            "txn_amount": np.random.gamma(4, 80, n_fraud),  # Larger amounts
            "amount_deviation_from_avg": np.random.normal(50, 40, n_fraud),  # Unusual amounts
            "is_new_country": np.random.binomial(1, 0.6, n_fraud),  # More new countries
            "is_new_device": np.random.binomial(1, 0.7, n_fraud),  # More new devices
            "is_new_merchant": np.random.binomial(1, 0.8, n_fraud),  # More new merchants
            "cvv_match": np.random.binomial(1, 0.4, n_fraud),  # Lower CVV match
            "billing_zip_match": np.random.binomial(1, 0.3, n_fraud),  # Lower zip match
            "hour_of_day": np.random.randint(0, 24, n_fraud),  # Any time
            "day_of_week": np.random.randint(0, 7, n_fraud),
            "is_weekend": np.random.binomial(1, 0.4, n_fraud),
            "is_night_txn": np.random.binomial(1, 0.4, n_fraud),  # More night transactions
            
            "is_fraud": np.ones(n_fraud, dtype=int)
        }
        
        # Combine and shuffle
        df_legitimate = pd.DataFrame(legitimate_data)
        df_fraud = pd.DataFrame(fraud_data)
        df = pd.concat([df_legitimate, df_fraud], ignore_index=True)
        df = df.sample(frac=1, random_state=42).reset_index(drop=True)
        
        logger.info(f"Generated {len(df)} synthetic transactions ({fraud_rate*100:.1f}% fraud)")
        return df
    
    def train(self,
             df: pd.DataFrame,
             test_size: float = 0.2,
             balance_data: bool = True,
             cv_folds: int = 5,
             register: bool = True,
             register_stage: str = STAGE_STAGING):
        """Train XGBoost model with cross-validation.

        When ``register`` is true the trained version is recorded in the
        model registry (default stage ``staging``) along with its eval
        metrics and a reference feature sample used for drift detection.
        """

        # Prepare features and target
        X = df[self.FEATURE_COLUMNS]
        y = df["is_fraud"]
        
        logger.info(f"Training on {len(X)} samples, {y.sum()} fraudulent ({y.mean()*100:.2f}%)")
        
        # Train-test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
        
        # Handle class imbalance with SMOTE + undersampling
        if balance_data:
            logger.info("Balancing dataset with SMOTE + UnderSampling...")
            
            # Create pipeline: oversample minority, undersample majority
            over = SMOTE(sampling_strategy=0.5, random_state=42)  # Bring fraud to 50% of majority
            under = RandomUnderSampler(sampling_strategy=0.8, random_state=42)  # Majority to 80% after SMOTE
            
            X_train_resampled, y_train_resampled = over.fit_resample(X_train, y_train)
            X_train_resampled, y_train_resampled = under.fit_resample(X_train_resampled, y_train_resampled)
            
            logger.info(
                f"Resampled: {len(X_train_resampled)} samples, "
                f"{y_train_resampled.sum()} fraudulent ({y_train_resampled.mean()*100:.2f}%)"
            )
        else:
            X_train_resampled = X_train
            y_train_resampled = y_train
        
        # XGBoost parameters optimized for fraud detection
        params = {
            "objective": "binary:logistic",
            "eval_metric": ["auc", "aucpr"],
            "max_depth": 6,
            "learning_rate": 0.1,
            "n_estimators": 200,
            "min_child_weight": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "gamma": 1,
            "reg_alpha": 0.1,
            "reg_lambda": 1,
            "scale_pos_weight": 1,  # Already balanced
            "random_state": 42,
            "n_jobs": -1,
            "tree_method": "hist"
        }
        
        # Train model
        logger.info("Training XGBoost model...")
        self.model = xgb.XGBClassifier(**params)
        
        eval_set = [(X_train_resampled, y_train_resampled), (X_test, y_test)]
        self.model.fit(
            X_train_resampled, 
            y_train_resampled,
            eval_set=eval_set,
            verbose=False
        )
        
        # Cross-validation
        logger.info(f"Performing {cv_folds}-fold cross-validation...")
        cv_scores = cross_val_score(
            self.model, X_train, y_train,
            cv=StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42),
            scoring="roc_auc",
            n_jobs=-1
        )
        logger.info(f"CV ROC-AUC: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
        
        # Evaluate on test set
        self.metrics = self._evaluate(X_test, y_test)
        self.metrics["cv_roc_auc"] = float(cv_scores.mean())

        # Feature importance
        self.feature_importance = pd.DataFrame({
            "feature": self.FEATURE_COLUMNS,
            "importance": self.model.feature_importances_
        }).sort_values("importance", ascending=False)

        logger.info("\nTop 10 Most Important Features:")
        logger.info(self.feature_importance.head(10).to_string(index=False))

        # Save model
        self.model_version = datetime.now().strftime("v%Y%m%d_%H%M%S")
        self._save_model()

        # Persist a reference feature sample for drift detection
        self._save_reference_data(X_test)

        # Register the version in the model registry
        if register:
            self._register(
                stage=register_stage,
                training_rows=int(len(X)),
                fraud_rate=float(y.mean()),
            )

        return self.metrics

    def _register(self, stage: str, training_rows: int, fraud_rate: float):
        """Record this trained version in the model registry."""
        try:
            registry = ModelRegistry()
            registry.register_model(
                version=self.model_version,
                artifact_path=self.artifact_path,
                reference_data_path=self.reference_data_path,
                metrics=self.metrics,
                params=self.model.get_params(),
                feature_list=self.FEATURE_COLUMNS,
                training_rows=training_rows,
                fraud_rate=fraud_rate,
                stage=stage,
            )
            logger.info(f"Registered model {self.model_version} as '{stage}'")
        except Exception as e:
            logger.error(f"Failed to register model in registry: {e}")

    def _save_reference_data(self, X_reference: pd.DataFrame):
        """Save the reference feature distribution used by drift detection."""
        ref_path = self.model_dir / f"reference_{self.model_version}.csv"
        X_reference.to_csv(ref_path, index=False)
        self.reference_data_path = str(ref_path)
        logger.info(f"Reference data saved to {ref_path}")

    def _evaluate(self, X_test, y_test) -> dict:
        """Evaluate model performance and return a metrics dict"""
        
        # Predictions
        y_pred = self.model.predict(X_test)
        y_pred_proba = self.model.predict_proba(X_test)[:, 1]
        
        # Metrics
        logger.info("\n" + "="*60)
        logger.info("MODEL EVALUATION")
        logger.info("="*60)
        
        logger.info("\nClassification Report:")
        logger.info("\n" + classification_report(y_test, y_pred, target_names=["Legitimate", "Fraud"]))
        
        logger.info("\nConfusion Matrix:")
        cm = confusion_matrix(y_test, y_pred)
        logger.info(f"\n{cm}")
        logger.info(f"True Negatives:  {cm[0][0]}")
        logger.info(f"False Positives: {cm[0][1]}")
        logger.info(f"False Negatives: {cm[1][0]}")
        logger.info(f"True Positives:  {cm[1][1]}")
        
        # ROC-AUC
        roc_auc = roc_auc_score(y_test, y_pred_proba)
        logger.info(f"\nROC-AUC Score: {roc_auc:.4f}")
        
        # Precision-Recall AUC
        pr_auc = average_precision_score(y_test, y_pred_proba)
        logger.info(f"PR-AUC Score: {pr_auc:.4f}")
        
        # Find optimal threshold
        precisions, recalls, thresholds = precision_recall_curve(y_test, y_pred_proba)
        f1_scores = 2 * (precisions * recalls) / (precisions + recalls + 1e-10)
        optimal_idx = np.argmax(f1_scores)
        optimal_threshold = thresholds[optimal_idx] if optimal_idx < len(thresholds) else 0.5
        
        logger.info(f"\nOptimal Threshold: {optimal_threshold:.4f}")
        logger.info(f"Precision at optimal: {precisions[optimal_idx]:.4f}")
        logger.info(f"Recall at optimal: {recalls[optimal_idx]:.4f}")
        logger.info(f"F1-Score at optimal: {f1_scores[optimal_idx]:.4f}")
        logger.info("="*60 + "\n")

        return {
            "roc_auc": float(roc_auc),
            "pr_auc": float(pr_auc),
            "precision": float(precisions[optimal_idx]),
            "recall": float(recalls[optimal_idx]),
            "f1": float(f1_scores[optimal_idx]),
            "optimal_threshold": float(optimal_threshold),
            "true_positives": int(cm[1][1]),
            "false_positives": int(cm[0][1]),
            "false_negatives": int(cm[1][0]),
            "true_negatives": int(cm[0][0]),
        }
    
    def _save_model(self):
        """Save trained model and metadata"""
        
        model_path = self.model_dir / f"fraud_model_{self.model_version}.pkl"
        metadata_path = self.model_dir / f"fraud_model_{self.model_version}_metadata.json"
        
        # Save model
        joblib.dump(self.model, model_path)
        self.artifact_path = str(model_path)
        logger.info(f"Model saved to {model_path}")
        
        # Save metadata
        metadata = {
            "model_version": self.model_version,
            "model_type": "XGBoostClassifier",
            "features": self.FEATURE_COLUMNS,
            "feature_importance": self.feature_importance.to_dict(orient="records"),
            "metrics": self.metrics,
            "training_date": datetime.now().isoformat(),
            "params": self.model.get_params()
        }
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Metadata saved to {metadata_path}")
    
    def load_model(self, version: str = None):
        """Load a trained model"""
        
        if version:
            model_path = self.model_dir / f"fraud_model_{version}.pkl"
        else:
            # Load latest
            model_files = list(self.model_dir.glob("fraud_model_v*.pkl"))
            if not model_files:
                raise FileNotFoundError("No trained models found")
            model_path = max(model_files, key=lambda p: p.stat().st_mtime)
        
        self.model = joblib.load(model_path)
        self.model_version = model_path.stem.replace("fraud_model_", "")
        logger.info(f"Loaded model {self.model_version} from {model_path}")
    
    def predict(self, features: dict) -> dict:
        """Make fraud prediction"""
        
        if self.model is None:
            raise ValueError("Model not trained or loaded")
        
        # Convert to DataFrame
        X = pd.DataFrame([features])[self.FEATURE_COLUMNS]
        
        # Predict
        fraud_probability = self.model.predict_proba(X)[0, 1]
        predicted_fraud = bool(fraud_probability > 0.5)
        
        return {
            "fraud_probability": float(fraud_probability),
            "predicted_fraud": predicted_fraud,
            "model_version": self.model_version
        }


def main():
    """Train the fraud detection model and register it."""
    import argparse

    parser = argparse.ArgumentParser(description="Train + register a fraud detection model")
    parser.add_argument("--samples", type=int, default=50000, help="Synthetic samples to generate")
    parser.add_argument("--fraud-rate", type=float, default=0.02, help="Synthetic fraud rate")
    parser.add_argument(
        "--stage",
        default=STAGE_STAGING,
        choices=[STAGE_STAGING, STAGE_PRODUCTION],
        help="Registry stage to register the trained model under",
    )
    parser.add_argument("--no-register", action="store_true", help="Skip registry registration")
    args = parser.parse_args()

    model = FraudDetectionModel()

    # Generate synthetic data (replace with real data loading in production)
    logger.info("Generating synthetic training data...")
    df = model.generate_synthetic_data(n_samples=args.samples, fraud_rate=args.fraud_rate)

    # Train model
    model.train(
        df,
        balance_data=True,
        register=not args.no_register,
        register_stage=args.stage,
    )

    logger.info("\nModel training complete!")
    logger.info(f"Model version: {model.model_version}")
    logger.info(f"Registered stage: {'(skipped)' if args.no_register else args.stage}")


if __name__ == "__main__":
    main()
