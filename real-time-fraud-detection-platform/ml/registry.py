"""
Model Registry - Postgres-backed model lifecycle management.

Tracks versioned XGBoost models and their lifecycle stages
(staging -> production / challenger -> archived), the evaluation metrics
captured at registration time, and the A/B experiment that decides how
traffic is split between the production champion and a challenger.

This is the MLOps spine: training registers here, serving reads the
production/challenger versions from here, drift detection rolls back here,
and CI/CD gates promotion here.
"""

import os
import json
import math
import logging
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "fraud_xgboost"

STAGE_STAGING = "staging"
STAGE_PRODUCTION = "production"
STAGE_CHALLENGER = "challenger"
STAGE_ARCHIVED = "archived"


def _json_safe(value: Any) -> Any:
    """Make a value safe for ``psycopg2.extras.Json``.

    XGBoost reports ``missing`` as ``float('nan')`` and Python's json module
    happily writes that as the bare token ``NaN``, which is valid JavaScript and
    invalid JSON. Postgres rejects it, so registration failed for every model
    trained with default XGBoost params, silently leaving the A/B router pointing
    at whatever stale champion row was already in the table.

    NaN and the infinities become null; everything else passes through.
    """
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _connection_params() -> Dict[str, Any]:
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5433")),
        "database": os.environ.get("DB_NAME", "fraud_detection"),
        "user": os.environ.get("DB_USER", "frauduser"),
        "password": os.environ.get("DB_PASSWORD", "fraudpass123"),
    }


class ModelRegistry:
    """Postgres-backed registry for versioned models and A/B experiments."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, connection_params: Optional[dict] = None):
        self.model_name = model_name
        self.connection_params = connection_params or _connection_params()

    @contextmanager
    def _conn(self):
        conn = psycopg2.connect(**self.connection_params)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Registration & promotion
    # ------------------------------------------------------------------
    def register_model(
        self,
        version: str,
        artifact_path: str,
        metrics: Dict[str, Any],
        params: Dict[str, Any],
        feature_list: List[str],
        training_rows: int,
        fraud_rate: float,
        reference_data_path: Optional[str] = None,
        stage: str = STAGE_STAGING,
    ) -> Dict[str, Any]:
        """Register a newly trained model version.

        If ``stage`` is production/challenger, any existing holder of that
        stage is first demoted to ``archived`` so the partial unique indexes
        hold.
        """
        is_live = stage in (STAGE_PRODUCTION, STAGE_CHALLENGER)

        with self._conn() as conn:
            if is_live:
                self._demote_stage(conn, stage)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_registry (
                        model_name, version, stage, artifact_path, reference_data_path,
                        metrics, params, feature_list, training_rows, fraud_rate, promoted_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s THEN NOW() ELSE NULL END
                    )
                    ON CONFLICT (model_name, version) DO UPDATE SET
                        stage = EXCLUDED.stage,
                        artifact_path = EXCLUDED.artifact_path,
                        reference_data_path = EXCLUDED.reference_data_path,
                        metrics = EXCLUDED.metrics,
                        params = EXCLUDED.params,
                        feature_list = EXCLUDED.feature_list,
                        training_rows = EXCLUDED.training_rows,
                        fraud_rate = EXCLUDED.fraud_rate,
                        promoted_at = CASE WHEN %s THEN NOW() ELSE model_registry.promoted_at END
                    """,
                    (
                        self.model_name, version, stage, artifact_path, reference_data_path,
                        Json(_json_safe(metrics)), Json(_json_safe(params)), Json(_json_safe(feature_list)),
                        training_rows, fraud_rate, is_live, is_live,
                    ),
                )
        logger.info(f"Registered {self.model_name}:{version} as '{stage}'")
        return self.get_metadata(version)

    def promote(self, version: str, stage: str) -> Dict[str, Any]:
        """Move a version to a target stage, archiving the current holder."""
        if stage not in (STAGE_STAGING, STAGE_PRODUCTION, STAGE_CHALLENGER, STAGE_ARCHIVED):
            raise ValueError(f"Unknown stage: {stage}")

        with self._conn() as conn:
            if stage in (STAGE_PRODUCTION, STAGE_CHALLENGER):
                self._demote_stage(conn, stage, exclude_version=version)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_registry
                    SET stage = %s,
                        promoted_at = CASE WHEN %s IN ('production', 'challenger')
                                           THEN NOW() ELSE promoted_at END
                    WHERE model_name = %s AND version = %s
                    """,
                    (stage, stage, self.model_name, version),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"Version not found in registry: {version}")
        logger.info(f"Promoted {self.model_name}:{version} -> '{stage}'")
        return self.get_metadata(version)

    def _demote_stage(self, conn, stage: str, exclude_version: Optional[str] = None):
        """Archive whatever version currently holds ``stage``."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE model_registry
                SET stage = %s
                WHERE model_name = %s AND stage = %s
                  AND (%s IS NULL OR version <> %s)
                """,
                (STAGE_ARCHIVED, self.model_name, stage, exclude_version, exclude_version),
            )

    def rollback(self) -> Optional[str]:
        """Roll the production model back to the previous known-good version.

        Demotes the current production model to ``archived`` and promotes the
        most recently promoted archived version (i.e. the prior production) back
        to ``production``. Returns the version rolled back to, or ``None`` if
        there is nothing to roll back to.
        """
        current = self.get_version_for_stage(STAGE_PRODUCTION)

        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT version FROM model_registry
                    WHERE model_name = %s AND stage = %s
                      AND (%s IS NULL OR version <> %s)
                    ORDER BY promoted_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """,
                    (self.model_name, STAGE_ARCHIVED, current, current),
                )
                row = cur.fetchone()

            if not row:
                logger.warning("Rollback requested but no archived version to roll back to")
                return None

            target = row["version"]
            with conn.cursor() as cur:
                if current:
                    cur.execute(
                        "UPDATE model_registry SET stage = %s WHERE model_name = %s AND version = %s",
                        (STAGE_ARCHIVED, self.model_name, current),
                    )
                cur.execute(
                    """
                    UPDATE model_registry
                    SET stage = %s, promoted_at = NOW()
                    WHERE model_name = %s AND version = %s
                    """,
                    (STAGE_PRODUCTION, self.model_name, target),
                )
        logger.warning(f"Rolled back production {current} -> {target}")
        return target

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_version_for_stage(self, stage: str) -> Optional[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT version FROM model_registry WHERE model_name = %s AND stage = %s LIMIT 1",
                (self.model_name, stage),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_metadata(self, version: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM model_registry WHERE model_name = %s AND version = %s",
                (self.model_name, version),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_models(self) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM model_registry WHERE model_name = %s ORDER BY created_at DESC",
                (self.model_name,),
            )
            return [dict(r) for r in cur.fetchall()]

    def is_empty(self) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM model_registry WHERE model_name = %s LIMIT 1",
                (self.model_name,),
            )
            return cur.fetchone() is None

    # ------------------------------------------------------------------
    # A/B experiments
    # ------------------------------------------------------------------
    def get_active_experiment(self) -> Optional[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM model_experiments
                WHERE model_name = %s AND status = 'active'
                ORDER BY started_at DESC LIMIT 1
                """,
                (self.model_name,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def start_experiment(
        self,
        challenger_version: str,
        traffic_pct: float = 0.1,
        champion_version: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start an A/B experiment, stopping any currently active one.

        ``champion_version`` defaults to the current production version.
        """
        if not 0.0 <= traffic_pct <= 1.0:
            raise ValueError("traffic_pct must be between 0 and 1")

        champion = champion_version or self.get_version_for_stage(STAGE_PRODUCTION)
        if champion is None:
            raise ValueError("No production (champion) model to run an experiment against")

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_experiments SET status = 'stopped', stopped_at = NOW()
                    WHERE model_name = %s AND status = 'active'
                    """,
                    (self.model_name,),
                )
                cur.execute(
                    """
                    INSERT INTO model_experiments (
                        model_name, champion_version, challenger_version, traffic_pct, description
                    ) VALUES (%s, %s, %s, %s, %s)
                    RETURNING experiment_id
                    """,
                    (self.model_name, champion, challenger_version, traffic_pct, description),
                )
        logger.info(
            f"Started experiment: champion={champion} challenger={challenger_version} "
            f"traffic={traffic_pct:.0%}"
        )
        return self.get_active_experiment()

    def stop_experiment(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE model_experiments SET status = 'stopped', stopped_at = NOW()
                WHERE model_name = %s AND status = 'active'
                """,
                (self.model_name,),
            )
        logger.info("Stopped active experiment")
