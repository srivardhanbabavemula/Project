# Requirements Document

## Introduction

This feature evolves the existing Fraud Guard real-time payment fraud detection system into a
portfolio-grade Production ML Platform (MLOps). Fraud Guard already provides a Postgres-backed
model registry (`ml/registry.py`), a deterministic champion/challenger A/B router (`ml/ab_router.py`),
an XGBoost training and registration pipeline (`ml/train_model.py`), a feature store
(`feature_store/store.py`), and a FastAPI serving layer (`api/main.py`) exposing scoring, registry,
A/B experiment, drift status, and feature-freshness endpoints.

The scope of this feature is the net-new MLOps work that completes the platform and closes gaps that
the serving layer already references but that are not yet implemented. Specifically:

1. A drift detection job using Evidently that compares live feature distributions against the stored
   reference data, records results to the `drift_reports` table, and triggers an automated rollback of
   the production model when drift exceeds a configured threshold.
2. Feature store read-API enhancements, including the `get_feature_freshness()` method that
   `GET /feature-store/freshness` already calls but which does not yet exist.
3. A model performance dashboard visualizing model metrics, champion-vs-challenger A/B comparison,
   drift status, and feature freshness.
4. A CI/CD pipeline that retrains on a schedule, evaluates the candidate model, and gates promotion
   from staging to production on evaluation results.
5. Wiring drift detection to auto-rollback with alert emission.

This feature extends the existing components. It does not re-implement the registry, router, trainer,
or scoring path, all of which are already present.

## Glossary

- **Platform**: The complete Production ML Platform comprising all components below.
- **Model_Registry**: The existing Postgres-backed component (`ml/registry.py`) that stores versioned
  models with lifecycle stages (`staging`, `production`, `challenger`, `archived`) and exposes
  `register_model`, `promote`, `rollback`, and A/B experiment operations.
- **AB_Router**: The existing component (`ml/ab_router.py`) that loads champion/challenger models from
  the Model_Registry and routes traffic; exposes `refresh()` to reload registry state.
- **Trainer**: The existing component (`ml/train_model.py`, class `FraudDetectionModel`) that trains an
  XGBoost model, evaluates it, writes a reference feature CSV, and registers the version.
- **Feature_Store**: The existing component (`feature_store/store.py`, class `FeatureStore`) that serves
  online features for scoring.
- **Serving_API**: The existing FastAPI application (`api/main.py`).
- **Drift_Detector**: The net-new job that compares current feature distributions against reference data
  using Evidently and persists results.
- **Reference_Data**: The feature sample saved at training time (`reference_data_path` in the
  Model_Registry, a CSV produced by the Trainer) representing the distribution the production model was
  trained on.
- **Current_Data**: A sample of recent feature vectors served in production, read from the
  `model_predictions.features` column.
- **Drift_Share**: The fraction of monitored feature columns flagged as drifted by Evidently, a value in
  the range 0.0 to 1.0.
- **Drift_Threshold**: The configured Drift_Share value at or above which the production model is rolled
  back. Default value is 0.5.
- **Drift_Report**: A row in the `drift_reports` table summarizing one Drift_Detector run.
- **Auto_Rollback**: The action of demoting the current production model and promoting the previous
  known-good version, performed by `Model_Registry.rollback()` followed by `AB_Router.refresh()`.
- **Alert_Notifier**: The net-new component that emits notifications when drift is detected, a rollback
  occurs, or a promotion gate decision is made.
- **Dashboard**: The net-new model performance dashboard (Grafana panels or a Streamlit application).
- **Retraining_Pipeline**: The net-new CI/CD workflow that retrains, evaluates, and conditionally
  promotes models on a schedule.
- **Promotion_Gate**: The decision logic in the Retraining_Pipeline that compares a staging candidate
  model against the current production model and decides whether promotion is permitted.
- **Feature_Freshness**: The staleness status of each feature, derived from the `feature_metadata`
  table's `last_updated` and `staleness_threshold_seconds` columns.
- **ROC_AUC**: Area under the receiver operating characteristic curve, a model evaluation metric stored
  in the Model_Registry `metrics` field.
- **PR_AUC**: Area under the precision-recall curve, a model evaluation metric stored in the
  Model_Registry `metrics` field.

## Requirements

### Requirement 1: Drift Detection Job

**User Story:** As an ML platform operator, I want a scheduled job that measures feature drift against
the production model's reference data, so that I can detect when live traffic has diverged from training
conditions.

#### Acceptance Criteria

1. WHEN the Drift_Detector runs, THE Drift_Detector SHALL load the Reference_Data identified by the
   `reference_data_path` of the current production model in the Model_Registry.
2. WHEN the Drift_Detector runs, THE Drift_Detector SHALL load Current_Data from the most recent
   `model_predictions.features` rows served by the current production model version.
3. WHEN both Reference_Data and Current_Data are available, THE Drift_Detector SHALL compute a
   Drift_Share over the feature columns shared between the two datasets using Evidently.
4. WHEN a drift computation completes, THE Drift_Detector SHALL insert one Drift_Report into the
   `drift_reports` table recording `model_version`, `drift_share`, `n_drifted`, `n_features`,
   `drifted_features`, `drift_detected`, `action_taken`, `n_reference_rows`, and `n_current_rows`.
5. IF the production model has no `reference_data_path` recorded, THEN THE Drift_Detector SHALL record a
   Drift_Report with `drift_detected` set to false and `action_taken` set to `none`, and SHALL emit a
   warning.
6. IF the number of Current_Data rows is below the configured minimum sample size, THEN THE
   Drift_Detector SHALL skip drift computation, record a Drift_Report with `drift_detected` set to false
   and `action_taken` set to `none`, and SHALL emit a warning.
7. IF the Model_Registry contains no production model, THEN THE Drift_Detector SHALL terminate without
   writing a Drift_Report and SHALL emit a warning.

### Requirement 2: Drift-Triggered Auto-Rollback

**User Story:** As an ML platform operator, I want the production model to be rolled back automatically
when drift is severe, so that the system reverts to a known-good model without manual intervention.

#### Acceptance Criteria

1. WHEN a Drift_Detector run produces a Drift_Share greater than or equal to the Drift_Threshold, THE
   Drift_Detector SHALL set `drift_detected` to true on the Drift_Report.
2. WHEN `drift_detected` is true and a previous archived version exists to roll back to, THE
   Drift_Detector SHALL invoke `Model_Registry.rollback()`.
3. WHEN `Model_Registry.rollback()` returns a target version, THE Drift_Detector SHALL set the
   Drift_Report `action_taken` to `rolled_back` and `rolled_back_to` to the returned version.
4. WHEN an Auto_Rollback completes, THE Drift_Detector SHALL invoke `AB_Router.refresh()` so the serving
   layer loads the restored production model.
5. WHEN a Drift_Share is below the Drift_Threshold, THE Drift_Detector SHALL set the Drift_Report
   `action_taken` to `none` and SHALL leave the production model unchanged.
6. IF `drift_detected` is true but `Model_Registry.rollback()` returns no target version, THEN THE
   Drift_Detector SHALL set the Drift_Report `action_taken` to `none` and SHALL emit a warning that no
   rollback target was available.

### Requirement 3: Drift and Rollback Alerting

**User Story:** As an on-call engineer, I want to be alerted when drift is detected or a rollback occurs,
so that I can investigate model degradation promptly.

#### Acceptance Criteria

1. WHEN a Drift_Report records `drift_detected` as true, THE Alert_Notifier SHALL emit an alert
   containing the model version, the Drift_Share, and the list of drifted features.
2. WHEN a Drift_Report records `action_taken` as `rolled_back`, THE Alert_Notifier SHALL emit an alert
   containing the rolled-back-from version and the rolled-back-to version.
3. WHERE alert delivery is configured with a notification target, THE Alert_Notifier SHALL send the
   alert to the configured target and SHALL NOT duplicate the alert to the application log.
4. WHERE no notification target is configured, THE Alert_Notifier SHALL write the alert to the
   application log at warning level.
5. IF alert delivery to a configured target fails, THEN THE Alert_Notifier SHALL write the alert to the
   application log at error level and SHALL allow the Drift_Detector run to complete.

### Requirement 4: Feature Freshness Reporting

**User Story:** As an ML platform operator, I want the feature store to report how stale each feature is,
so that I can detect broken or delayed feature pipelines through the existing
`GET /feature-store/freshness` endpoint.

#### Acceptance Criteria

1. THE Feature_Store SHALL provide a `get_feature_freshness()` method returning exactly one entry for
   every active feature defined in the `feature_metadata` table, with no active feature omitted.
2. WHEN `get_feature_freshness()` is called, THE Feature_Store SHALL return for each active feature its
   `feature_name`, its staleness in seconds computed as the elapsed time since `last_updated`, and a
   boolean indicating whether staleness exceeds `staleness_threshold_seconds`.
3. IF a feature's `last_updated` value is null, THEN THE Feature_Store SHALL report that feature with a
   stale status of true.
4. WHEN `GET /feature-store/freshness` is requested, THE Serving_API SHALL return the result of
   `get_feature_freshness()` with HTTP status 200.
5. IF the Feature_Store cannot query the `feature_metadata` table, THEN THE Serving_API SHALL return
   HTTP status 500 with a descriptive error message.

### Requirement 5: Model Performance Dashboard

**User Story:** As a data scientist, I want a dashboard showing model metrics, A/B comparison, drift
status, and feature freshness, so that I can monitor the health of the deployed models in one place.

#### Acceptance Criteria

1. THE Dashboard SHALL display the current production model version and its registered evaluation
   metrics, including ROC_AUC and PR_AUC, read from the Model_Registry.
2. WHERE an A/B experiment is active, THE Dashboard SHALL display the champion and challenger versions
   alongside their observed fraud rate, average score, and average latency computed per `model_role`
   from the `model_predictions` table.
3. THE Dashboard SHALL display the most recent Drift_Reports, including each report's Drift_Share,
   `drift_detected` status, and `action_taken`.
4. THE Dashboard SHALL display Feature_Freshness for each active feature, indicating which features are
   stale.
5. WHEN underlying data for a panel is unavailable, THE Dashboard SHALL display an empty-state indicator
   for that panel rather than failing to render the remaining panels.

### Requirement 6: Scheduled Retraining Pipeline

**User Story:** As an ML platform operator, I want models retrained automatically on a schedule, so that
the production model stays current without manual training runs.

#### Acceptance Criteria

1. WHEN the configured schedule triggers, THE Retraining_Pipeline SHALL execute the Trainer to produce a
   new model version registered in the `staging` stage.
2. WHEN the Trainer completes within the Retraining_Pipeline, THE Retraining_Pipeline SHALL record the
   candidate version identifier and its evaluation metrics for use by the Promotion_Gate.
3. IF the Trainer fails during a scheduled run, THEN THE Retraining_Pipeline SHALL record the partial
   run outcome, mark the run as failed, terminate with a non-zero exit status, and SHALL leave the
   existing production model unchanged.
4. WHEN a scheduled run completes, THE Retraining_Pipeline SHALL emit a run summary recording the
   candidate version, the gate decision, and whether a promotion occurred.

### Requirement 7: Promotion Gating on Evaluation

**User Story:** As an ML platform operator, I want promotion from staging to production gated on
evaluation results, so that a new model is promoted only when it is at least as good as the current
production model.

#### Acceptance Criteria

1. WHEN the Promotion_Gate evaluates a staging candidate, THE Promotion_Gate SHALL compare the
   candidate's ROC_AUC and PR_AUC against the current production model's registered ROC_AUC and PR_AUC.
2. WHEN the candidate's ROC_AUC and PR_AUC are each greater than or equal to the current production
   model's corresponding metric minus the configured tolerance, THE Promotion_Gate SHALL mark the
   candidate as meeting the performance criteria.
3. THE Promotion_Gate SHALL determine eligibility as a decision distinct from the performance criteria,
   such that a configured override MAY mark a candidate eligible or ineligible regardless of whether the
   performance criteria are met.
4. WHERE auto-promotion is enabled and the candidate is eligible, THE Retraining_Pipeline SHALL invoke
   `Model_Registry.promote()` to move the candidate to the `production` stage.
5. WHERE manual approval is required and the candidate is eligible, THE Retraining_Pipeline SHALL leave
   the candidate in the `staging` stage and SHALL record that the candidate is awaiting approval.
6. IF the candidate is not eligible for promotion, THEN THE Promotion_Gate SHALL reject the candidate,
   leave it in the `staging` stage, and record the rejection reason.
7. IF the Model_Registry contains no production model when the Promotion_Gate runs, THEN THE
   Promotion_Gate SHALL mark the candidate as eligible and the Retraining_Pipeline SHALL promote the
   candidate to the `production` stage.
8. WHEN a promotion occurs through the Retraining_Pipeline, THE Alert_Notifier SHALL emit an alert
   recording the promoted version and the metrics that satisfied the Promotion_Gate.

### Requirement 8: Drift and Promotion Configuration

**User Story:** As an ML platform operator, I want the drift and promotion behavior to be configurable,
so that I can tune thresholds without changing code.

#### Acceptance Criteria

1. THE Platform SHALL read the Drift_Threshold from configuration, defaulting to 0.5 when unset.
2. THE Platform SHALL read the minimum Current_Data sample size from configuration, defaulting to a
   documented value when unset.
3. THE Platform SHALL read the Promotion_Gate metric tolerance from configuration, defaulting to a
   documented value when unset.
4. THE Platform SHALL read the promotion mode (auto-promotion or manual approval) from configuration,
   defaulting to manual approval when unset.
5. IF a configuration value is present but cannot be parsed into its expected type, THEN THE Platform
   SHALL fall back to the documented default for that value and SHALL emit a warning naming the affected
   configuration key.
