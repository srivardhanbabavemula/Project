"""
A/B Testing Router - champion vs challenger model selection.

Reads the production (champion) and, when an experiment is active, the
challenger model from the model registry and deterministically routes a
configurable share of traffic to the challenger. Bucketing is hashed on
``user_id`` so a given user is consistently served by the same model for the
life of the experiment (clean A/B exposure).
"""

import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

sys.path.append(str(Path(__file__).parent.parent))
from ml.train_model import FraudDetectionModel
from ml.registry import ModelRegistry, STAGE_PRODUCTION

logger = logging.getLogger(__name__)

ROLE_CHAMPION = "champion"
ROLE_CHALLENGER = "challenger"


def _bucket(user_id: str) -> float:
    """Map a user id to a stable float in [0, 1) for traffic splitting."""
    digest = hashlib.md5(str(user_id).encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 10_000) / 10_000.0


class ABRouter:
    """Loads champion/challenger models and routes scoring traffic."""

    def __init__(self, registry: Optional[ModelRegistry] = None, model_dir: str = "ml/models"):
        self.registry = registry or ModelRegistry()
        self.model_dir = model_dir

        self.champion_model: Optional[FraudDetectionModel] = None
        self.champion_version: Optional[str] = None

        self.challenger_model: Optional[FraudDetectionModel] = None
        self.challenger_version: Optional[str] = None

        self.experiment_id: Optional[str] = None
        self.traffic_pct: float = 0.0

        self.refresh()

    def _load_version(self, version: str) -> FraudDetectionModel:
        model = FraudDetectionModel(model_dir=self.model_dir)
        model.load_model(version)
        return model

    def refresh(self):
        """Reload champion/challenger from the registry + active experiment.

        Called at startup and after rollbacks / promotions so the live router
        always reflects the registry's current state.
        """
        champion_version = self.registry.get_version_for_stage(STAGE_PRODUCTION)

        if champion_version and champion_version != self.champion_version:
            self.champion_model = self._load_version(champion_version)
            self.champion_version = champion_version
            logger.info(f"Champion model: {champion_version}")
        elif champion_version is None:
            self.champion_model = None
            self.champion_version = None

        # Active A/B experiment (optional)
        experiment = self.registry.get_active_experiment()
        if experiment:
            self.experiment_id = str(experiment["experiment_id"])
            self.traffic_pct = float(experiment["traffic_pct"])
            ch_version = experiment["challenger_version"]
            if ch_version != self.challenger_version:
                self.challenger_model = self._load_version(ch_version)
                self.challenger_version = ch_version
                logger.info(
                    f"Challenger model: {ch_version} @ {self.traffic_pct:.0%} traffic"
                )
        else:
            self.experiment_id = None
            self.traffic_pct = 0.0
            self.challenger_model = None
            self.challenger_version = None

    def has_champion(self) -> bool:
        return self.champion_model is not None

    def set_champion(self, model: FraudDetectionModel):
        """Inject a freshly trained champion (cold-start path)."""
        self.champion_model = model
        self.champion_version = model.model_version

    def select(self, user_id: str) -> Tuple[FraudDetectionModel, str, str, Optional[str]]:
        """Choose which model serves this request.

        Returns ``(model, role, version, experiment_id)``. Falls back to the
        champion whenever no challenger is configured or the user is outside
        the challenger traffic bucket.
        """
        if self.champion_model is None:
            raise RuntimeError("No champion model loaded")

        if self.challenger_model is not None and _bucket(user_id) < self.traffic_pct:
            return (self.challenger_model, ROLE_CHALLENGER, self.challenger_version, self.experiment_id)

        return (self.champion_model, ROLE_CHAMPION, self.champion_version, self.experiment_id)
