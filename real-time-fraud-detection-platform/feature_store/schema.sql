-- =====================================================
-- Fraud Detection Database Schema
-- PostgreSQL 15+
-- =====================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TRANSACTIONS TABLE
-- Stores all payment transactions with raw data
-- =====================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    merchant_id VARCHAR(255) NOT NULL,
    merchant_category VARCHAR(100),
    country VARCHAR(2),
    device_id VARCHAR(255),
    ip_address VARCHAR(45),
    card_last_4 VARCHAR(4),
    cvv_match BOOLEAN,
    billing_zip_match BOOLEAN,
    
    -- Time features
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    hour_of_day INTEGER,
    day_of_week INTEGER,
    is_weekend BOOLEAN,
    is_night_txn BOOLEAN,
    
    -- Fraud label
    is_fraud BOOLEAN DEFAULT FALSE,
    fraud_type VARCHAR(50),
    
    -- Processing metadata
    processing_status VARCHAR(20) DEFAULT 'pending',
    fraud_score DECIMAL(5, 4),
    fraud_decision VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_timestamp ON transactions(timestamp DESC);
CREATE INDEX idx_transactions_merchant_id ON transactions(merchant_id);
CREATE INDEX idx_transactions_is_fraud ON transactions(is_fraud);
CREATE INDEX idx_transactions_created_at ON transactions(created_at DESC);

-- =====================================================
-- USER VELOCITY FEATURES
-- Real-time aggregated features per user
-- =====================================================
CREATE TABLE IF NOT EXISTS user_velocity_features (
    user_id UUID NOT NULL,
    window_end TIMESTAMP NOT NULL,
    
    -- 1 hour window features
    txn_count_1h INTEGER DEFAULT 0,
    total_amount_1h DECIMAL(12, 2) DEFAULT 0,
    avg_amount_1h DECIMAL(10, 2),
    stddev_amount_1h DECIMAL(10, 2),
    max_amount_1h DECIMAL(10, 2),
    
    -- Computed timestamp
    computed_at TIMESTAMP DEFAULT NOW(),
    
    PRIMARY KEY (user_id, window_end)
);

CREATE INDEX idx_velocity_user_id ON user_velocity_features(user_id);
CREATE INDEX idx_velocity_window_end ON user_velocity_features(window_end DESC);

-- =====================================================
-- MERCHANT FEATURES
-- Merchant-level statistics and risk scores
-- =====================================================
CREATE TABLE IF NOT EXISTS merchant_features (
    merchant_id VARCHAR(255) NOT NULL,
    window_end TIMESTAMP NOT NULL,
    
    -- 24 hour aggregations
    merchant_txn_count_24h INTEGER DEFAULT 0,
    merchant_avg_amount_24h DECIMAL(10, 2),
    merchant_fraud_count_24h INTEGER DEFAULT 0,
    merchant_fraud_rate_24h DECIMAL(5, 4),
    
    -- Risk profile
    risk_category VARCHAR(20) DEFAULT 'low',
    
    computed_at TIMESTAMP DEFAULT NOW(),
    
    PRIMARY KEY (merchant_id, window_end)
);

CREATE INDEX idx_merchant_id ON merchant_features(merchant_id);
CREATE INDEX idx_merchant_window_end ON merchant_features(window_end DESC);

-- =====================================================
-- USER BEHAVIORAL FEATURES
-- Long-term user behavior patterns (updated periodically)
-- =====================================================
CREATE TABLE IF NOT EXISTS user_behavioral_features (
    user_id UUID PRIMARY KEY,
    
    -- Historical patterns (30 day)
    avg_transaction_amount_30d DECIMAL(10, 2),
    total_transactions_30d INTEGER DEFAULT 0,
    unique_merchants_30d INTEGER DEFAULT 0,
    unique_countries_30d INTEGER DEFAULT 0,
    unique_devices_30d INTEGER DEFAULT 0,
    
    -- User profile
    home_country VARCHAR(2),
    account_age_days INTEGER,
    is_verified BOOLEAN DEFAULT FALSE,
    
    -- Risk indicators
    fraud_count_historical INTEGER DEFAULT 0,
    chargeback_count INTEGER DEFAULT 0,
    user_risk_score DECIMAL(5, 4),
    
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_behavioral_user_id ON user_behavioral_features(user_id);

-- =====================================================
-- DEVICE FEATURES
-- Device-level risk tracking
-- =====================================================
CREATE TABLE IF NOT EXISTS device_features (
    device_id VARCHAR(255) PRIMARY KEY,
    
    device_type VARCHAR(50),
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    
    -- Device statistics
    total_transactions INTEGER DEFAULT 0,
    total_users INTEGER DEFAULT 0,
    fraud_count INTEGER DEFAULT 0,
    fraud_rate DECIMAL(5, 4),
    
    -- Risk flags
    is_high_risk BOOLEAN DEFAULT FALSE,
    risk_reason TEXT,
    
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_device_id ON device_features(device_id);
CREATE INDEX idx_device_is_high_risk ON device_features(is_high_risk);

-- =====================================================
-- MODEL PREDICTIONS
-- Stores fraud scores and model predictions
-- =====================================================
CREATE TABLE IF NOT EXISTS model_predictions (
    prediction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID NOT NULL REFERENCES transactions(transaction_id),
    
    -- Model metadata
    model_version VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) DEFAULT 'xgboost_v1',
    
    -- Prediction results
    fraud_probability DECIMAL(5, 4) NOT NULL,
    predicted_fraud BOOLEAN NOT NULL,
    decision VARCHAR(20) NOT NULL, -- 'approve', 'decline', 'review'
    
    -- Feature values at prediction time (JSONB for flexibility)
    features JSONB,
    
    -- Performance tracking
    prediction_latency_ms INTEGER,
    feature_retrieval_latency_ms INTEGER,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- A/B testing metadata: which model role served this prediction and under
-- which experiment. Nullable so single-model deployments keep working.
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS model_role VARCHAR(20);
ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS experiment_id UUID;

-- Decouple prediction logging from transaction ingestion. The real-time
-- scoring path generates a transaction_id and scores on the fly without
-- persisting a full transactions row (request user_ids are not always UUIDs),
-- so predictions must be loggable on their own.
ALTER TABLE model_predictions DROP CONSTRAINT IF EXISTS model_predictions_transaction_id_fkey;

CREATE INDEX IF NOT EXISTS idx_predictions_transaction_id ON model_predictions(transaction_id);
CREATE INDEX IF NOT EXISTS idx_predictions_model_version ON model_predictions(model_version);
CREATE INDEX IF NOT EXISTS idx_predictions_created_at ON model_predictions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_model_role ON model_predictions(model_role);

-- =====================================================
-- MODEL PERFORMANCE METRICS
-- Track model accuracy over time
-- =====================================================
CREATE TABLE IF NOT EXISTS model_performance (
    metric_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_version VARCHAR(50) NOT NULL,
    
    -- Time window
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    
    -- Performance metrics
    total_predictions INTEGER,
    true_positives INTEGER,
    false_positives INTEGER,
    true_negatives INTEGER,
    false_negatives INTEGER,
    precision DECIMAL(5, 4),
    recall DECIMAL(5, 4),
    f1_score DECIMAL(5, 4),
    auc_roc DECIMAL(5, 4),
    
    -- Latency metrics
    avg_latency_ms DECIMAL(8, 2),
    p50_latency_ms INTEGER,
    p95_latency_ms INTEGER,
    p99_latency_ms INTEGER,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_performance_model_version ON model_performance(model_version);
CREATE INDEX idx_performance_window_end ON model_performance(window_end DESC);

-- =====================================================
-- FEATURE STORE METADATA
-- Tracks feature definitions and freshness
-- =====================================================
CREATE TABLE IF NOT EXISTS feature_metadata (
    feature_name VARCHAR(255) PRIMARY KEY,
    feature_type VARCHAR(50) NOT NULL, -- 'velocity', 'behavioral', 'merchant', 'device'
    description TEXT,
    data_type VARCHAR(50),
    
    -- Freshness tracking
    expected_update_frequency_seconds INTEGER,
    last_updated TIMESTAMP,
    staleness_threshold_seconds INTEGER,
    
    -- Feature importance (from model)
    importance_score DECIMAL(5, 4),
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- ALERT RULES
-- Define rules for fraud alerts
-- =====================================================
CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(50) NOT NULL, -- 'velocity', 'amount', 'location', 'merchant'
    
    -- Rule conditions (JSONB for flexibility)
    conditions JSONB NOT NULL,
    
    -- Actions
    severity VARCHAR(20) DEFAULT 'medium', -- 'low', 'medium', 'high', 'critical'
    auto_decline BOOLEAN DEFAULT FALSE,
    requires_review BOOLEAN DEFAULT TRUE,
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- FRAUD ALERTS
-- Generated alerts for suspicious activity
-- =====================================================
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID REFERENCES transactions(transaction_id),
    rule_id UUID REFERENCES alert_rules(rule_id),
    
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT,
    
    -- Alert details
    triggered_conditions JSONB,
    
    -- Resolution
    status VARCHAR(20) DEFAULT 'open', -- 'open', 'investigating', 'resolved', 'false_positive'
    assigned_to VARCHAR(255),
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_alerts_transaction_id ON fraud_alerts(transaction_id);
CREATE INDEX idx_alerts_status ON fraud_alerts(status);
CREATE INDEX idx_alerts_severity ON fraud_alerts(severity);
CREATE INDEX idx_alerts_created_at ON fraud_alerts(created_at DESC);

-- =====================================================
-- MODEL REGISTRY  (MLOps)
-- Versioned models with lifecycle stages and eval metrics.
-- At most one 'production' and one 'challenger' per model_name
-- (enforced by partial unique indexes below).
-- =====================================================
CREATE TABLE IF NOT EXISTS model_registry (
    model_name          VARCHAR(100) NOT NULL DEFAULT 'fraud_xgboost',
    version             VARCHAR(50)  NOT NULL,

    -- Lifecycle: 'staging' | 'production' | 'challenger' | 'archived'
    stage               VARCHAR(20)  NOT NULL DEFAULT 'staging',

    -- Artifacts (paths on shared/mounted storage)
    artifact_path       TEXT,
    reference_data_path TEXT,

    -- Evaluation snapshot at registration time
    metrics             JSONB,        -- {roc_auc, pr_auc, precision, recall, f1, optimal_threshold}
    params              JSONB,
    feature_list        JSONB,
    training_rows       INTEGER,
    fraud_rate          DECIMAL(6, 5),

    created_at          TIMESTAMP DEFAULT NOW(),
    promoted_at         TIMESTAMP,
    is_active           BOOLEAN DEFAULT TRUE,

    PRIMARY KEY (model_name, version)
);

CREATE INDEX IF NOT EXISTS idx_registry_stage ON model_registry(model_name, stage);
CREATE INDEX IF NOT EXISTS idx_registry_created_at ON model_registry(created_at DESC);

-- Only one production / one challenger per model_name.
CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_production
    ON model_registry(model_name) WHERE stage = 'production';
CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_challenger
    ON model_registry(model_name) WHERE stage = 'challenger';

-- =====================================================
-- MODEL EXPERIMENTS  (A/B harness state)
-- One 'active' row per model_name drives champion/challenger routing.
-- Persisted so serving survives restarts and is settable via the API.
-- =====================================================
CREATE TABLE IF NOT EXISTS model_experiments (
    experiment_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name          VARCHAR(100) NOT NULL DEFAULT 'fraud_xgboost',

    champion_version    VARCHAR(50) NOT NULL,
    challenger_version  VARCHAR(50) NOT NULL,
    traffic_pct         DECIMAL(4, 3) NOT NULL DEFAULT 0.100,  -- share routed to challenger

    status              VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active' | 'stopped'
    description         TEXT,

    started_at          TIMESTAMP DEFAULT NOW(),
    stopped_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_experiments_status ON model_experiments(model_name, status);

-- At most one active experiment per model_name.
CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_active
    ON model_experiments(model_name) WHERE status = 'active';

-- =====================================================
-- DRIFT REPORTS  (Evidently runs + auto-rollback audit)
-- =====================================================
CREATE TABLE IF NOT EXISTS drift_reports (
    report_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name          VARCHAR(100) NOT NULL DEFAULT 'fraud_xgboost',
    model_version       VARCHAR(50)  NOT NULL,

    run_at              TIMESTAMP DEFAULT NOW(),

    -- Drift summary
    drift_share         DECIMAL(5, 4),         -- fraction of columns drifted
    n_drifted           INTEGER,
    n_features          INTEGER,
    drifted_features    JSONB,
    drift_detected      BOOLEAN DEFAULT FALSE,

    -- Action taken: 'none' | 'rolled_back'
    action_taken        VARCHAR(20) DEFAULT 'none',
    rolled_back_to      VARCHAR(50),

    report_html_path    TEXT,
    n_reference_rows    INTEGER,
    n_current_rows      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_drift_run_at ON drift_reports(run_at DESC);
CREATE INDEX IF NOT EXISTS idx_drift_model_version ON drift_reports(model_version);

-- =====================================================
-- HELPER VIEWS
-- =====================================================

-- Recent transactions with fraud scores
CREATE OR REPLACE VIEW v_recent_transactions_with_scores AS
SELECT 
    t.transaction_id,
    t.user_id,
    t.amount,
    t.merchant_id,
    t.country,
    t.timestamp,
    t.is_fraud,
    mp.fraud_probability,
    mp.decision,
    mp.model_version
FROM transactions t
LEFT JOIN model_predictions mp ON t.transaction_id = mp.transaction_id
WHERE t.timestamp > NOW() - INTERVAL '24 hours'
ORDER BY t.timestamp DESC;

-- User fraud summary
CREATE OR REPLACE VIEW v_user_fraud_summary AS
SELECT 
    user_id,
    COUNT(*) as total_transactions,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END) as fraud_count,
    ROUND(SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)::DECIMAL / COUNT(*), 4) as fraud_rate,
    SUM(amount) as total_amount,
    MAX(timestamp) as last_transaction
FROM transactions
GROUP BY user_id;

-- Merchant fraud summary
CREATE OR REPLACE VIEW v_merchant_fraud_summary AS
SELECT 
    merchant_id,
    merchant_category,
    COUNT(*) as total_transactions,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END) as fraud_count,
    ROUND(SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)::DECIMAL / COUNT(*), 4) as fraud_rate,
    AVG(amount) as avg_transaction_amount
FROM transactions
GROUP BY merchant_id, merchant_category;

-- =====================================================
-- FUNCTIONS
-- =====================================================

-- Function to calculate feature freshness
CREATE OR REPLACE FUNCTION check_feature_freshness()
RETURNS TABLE(feature_name VARCHAR, is_stale BOOLEAN, staleness_seconds INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        fm.feature_name,
        (EXTRACT(EPOCH FROM (NOW() - fm.last_updated))::INTEGER > fm.staleness_threshold_seconds) as is_stale,
        EXTRACT(EPOCH FROM (NOW() - fm.last_updated))::INTEGER as staleness_seconds
    FROM feature_metadata fm
    WHERE fm.is_active = TRUE;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- INITIAL DATA
-- =====================================================

-- Insert sample feature metadata
INSERT INTO feature_metadata (feature_name, feature_type, description, data_type, expected_update_frequency_seconds, staleness_threshold_seconds) VALUES
('txn_count_1h', 'velocity', 'Number of transactions in last 1 hour', 'integer', 60, 300),
('total_amount_1h', 'velocity', 'Total transaction amount in last 1 hour', 'decimal', 60, 300),
('avg_amount_1h', 'velocity', 'Average transaction amount in last 1 hour', 'decimal', 60, 300),
('merchant_fraud_rate_24h', 'merchant', 'Merchant fraud rate in last 24 hours', 'decimal', 3600, 7200),
('avg_transaction_amount_30d', 'behavioral', 'User average transaction amount in last 30 days', 'decimal', 86400, 172800)
ON CONFLICT (feature_name) DO NOTHING;

-- Insert sample alert rules
INSERT INTO alert_rules (rule_name, rule_type, conditions, severity, auto_decline) VALUES
('High Velocity - Multiple Transactions', 'velocity', '{"txn_count_1h": {"operator": ">", "value": 10}}', 'high', false),
('Unusual Amount - High Value', 'amount', '{"amount": {"operator": ">", "value": 1000}, "avg_amount_30d": {"operator": "<", "value": 100}}', 'critical', true),
('New Country Transaction', 'location', '{"is_new_country": true, "amount": {"operator": ">", "value": 500}}', 'medium', false),
('High Risk Merchant', 'merchant', '{"merchant_fraud_rate_24h": {"operator": ">", "value": 0.1}}', 'high', false)
ON CONFLICT DO NOTHING;

COMMIT;
