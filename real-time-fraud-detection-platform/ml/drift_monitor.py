"""
Evidently Drift Monitor

Runs data drift detection on recent transactions compared to the champion model's
reference dataset. If significant drift is detected, triggers an auto-rollback
via the ModelRegistry and records the drift report in PostgreSQL.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import psycopg2
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset

sys.path.append(str(Path(__file__).parent.parent))
from ml.registry import ModelRegistry, STAGE_PRODUCTION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_drift_check(simulate_drift: bool = False):
    registry = ModelRegistry()
    
    # 1. Get the current champion model
    champion_version = registry.get_version_for_stage(STAGE_PRODUCTION)
    if not champion_version:
        logger.warning("No production model found. Skipping drift check.")
        return

    metadata = registry.get_metadata(champion_version)
    reference_path = metadata.get("reference_data_path")
    if not reference_path or not os.path.exists(reference_path):
        logger.warning(f"No reference data found at {reference_path}. Skipping.")
        return

    # 2. Load Reference Data
    logger.info(f"Loading reference data from {reference_path}")
    ref_df = pd.read_csv(reference_path)

    # 3. Load Current Data
    # In a real system, we'd query Postgres for the last N hours of features.
    # For this platform, we simulate recent data (with optional drift) for demonstration.
    curr_df = ref_df.copy()
    if simulate_drift:
        logger.info("Simulating data drift on current dataset...")
        # Introduce drift on important features
        curr_df["merchant_txn_count_24h"] = curr_df["merchant_txn_count_24h"] * 3
        curr_df["merchant_fraud_rate_24h"] = curr_df["merchant_fraud_rate_24h"] + 0.1
        curr_df["txn_amount"] = curr_df["txn_amount"] * 2

    # 4. Run Evidently Report
    logger.info("Running Evidently DataDriftPreset...")
    drift_report = Report(metrics=[DataDriftPreset()])
    drift_report.run(reference_data=ref_df, current_data=curr_df)
    
    report_dict = drift_report.as_dict()
    
    # 5. Extract Drift Metrics
    drift_metrics = report_dict["metrics"][0]["result"]
    n_features = drift_metrics["number_of_columns"]
    n_drifted = drift_metrics["number_of_drifted_columns"]
    drift_share = drift_metrics["share_of_drifted_columns"]
    drift_detected = drift_metrics["dataset_drift"]
    
    drifted_features = [
        feature for feature, details in drift_metrics["drift_by_columns"].items() 
        if details["drift_detected"]
    ]

    logger.info(f"Drift Share: {drift_share:.2%} ({n_drifted}/{n_features} features drifted)")
    
    action_taken = "none"
    rolled_back_to = None
    
    # 6. Auto-Rollback if drift > threshold (e.g. > 20%)
    if drift_share > 0.2:
        logger.warning("Significant data drift detected! Triggering auto-rollback.")
        rolled_back_to = registry.rollback()
        if rolled_back_to:
            action_taken = "rolled_back"
            logger.info(f"Successfully rolled back to version {rolled_back_to}")
        else:
            logger.warning("Rollback failed (no previous version available).")
    
    # 7. Save Report to DB
    try:
        conn = psycopg2.connect(**registry.connection_params)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drift_reports (
                    model_name, model_version, drift_share, n_drifted, n_features,
                    drifted_features, drift_detected, action_taken, rolled_back_to,
                    n_reference_rows, n_current_rows
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    registry.model_name, champion_version, float(drift_share), n_drifted, n_features,
                    json.dumps(drifted_features), drift_detected, action_taken, rolled_back_to,
                    len(ref_df), len(curr_df)
                )
            )
        conn.commit()
        conn.close()
        logger.info("Drift report saved to Postgres `drift_reports` table.")
    except Exception as e:
        logger.error(f"Failed to save drift report to DB: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate-drift", action="store_true", help="Simulate data drift")
    args = parser.parse_args()
    
    run_drift_check(simulate_drift=args.simulate_drift)
