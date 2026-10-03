"""
FastAPI Application for Real-Time Fraud Detection

Provides REST API endpoints for fraud scoring and monitoring.
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
import time
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from feature_store.store import get_feature_store
from api.fraud_scorer import FraudScorer
from ml.registry import ModelRegistry, STAGE_PRODUCTION, STAGE_CHALLENGER
from prometheus_fastapi_instrumentator import Instrumentator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Real-Time Fraud Detection API",
    description="Production-grade fraud detection system for real-time payment transactions",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Initialize fraud scorer (lazy loading)
fraud_scorer = None
model_registry = None

def get_fraud_scorer():
    """Dependency for fraud scorer"""
    global fraud_scorer
    if fraud_scorer is None:
        fraud_scorer = FraudScorer()
    return fraud_scorer


def get_registry() -> ModelRegistry:
    """Dependency for the model registry"""
    global model_registry
    if model_registry is None:
        model_registry = ModelRegistry()
    return model_registry


# =====================================================
# Request/Response Models
# =====================================================

class TransactionRequest(BaseModel):
    """Transaction data for fraud scoring"""
    
    user_id: str = Field(..., description="User identifier")
    amount: float = Field(..., gt=0, description="Transaction amount")
    currency: str = Field(default="USD", description="Currency code")
    merchant_id: str = Field(..., description="Merchant identifier")
    merchant_category: Optional[str] = Field(None, description="Merchant category")
    country: str = Field(..., description="Country code (ISO 2-letter)")
    device_id: str = Field(..., description="Device identifier")
    ip_address: Optional[str] = Field(None, description="IP address")
    card_last_4: Optional[str] = Field(None, description="Last 4 digits of card")
    cvv_match: bool = Field(..., description="Whether CVV matched")
    billing_zip_match: bool = Field(..., description="Whether billing zip matched")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow)
    
    class Config:
        schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "amount": 125.50,
                "currency": "USD",
                "merchant_id": "Amazon",
                "merchant_category": "online_retail",
                "country": "US",
                "device_id": "device_12345",
                "ip_address": "192.168.1.1",
                "card_last_4": "4242",
                "cvv_match": True,
                "billing_zip_match": True
            }
        }


class FraudScoreResponse(BaseModel):
    """Fraud scoring response"""
    
    transaction_id: str
    fraud_score: float = Field(..., ge=0, le=1, description="Fraud probability (0-1)")
    decision: str = Field(..., description="approve, decline, or review")
    risk_level: str = Field(..., description="low, medium, high, or critical")
    model_version: str
    model_role: Optional[str] = Field(None, description="champion or challenger (A/B)")
    reasons: List[str] = Field(default_factory=list, description="Risk factors identified")
    
    # Performance metrics
    processing_time_ms: int
    feature_retrieval_time_ms: int
    model_inference_time_ms: int
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BatchTransactionRequest(BaseModel):
    """Batch of transactions for scoring"""
    transactions: List[TransactionRequest]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    model_loaded: bool
    model_version: Optional[str]
    feature_store_connected: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ModelMetricsResponse(BaseModel):
    """Model performance metrics"""
    model_version: str
    total_predictions: int
    fraud_rate: float
    avg_score: float
    avg_latency_ms: float
    decisions: Dict[str, int]


class PromoteRequest(BaseModel):
    """Promote a registered model version to a lifecycle stage"""
    version: str = Field(..., description="Model version to promote")
    stage: str = Field(..., description="Target stage: staging, production, challenger, archived")


class ExperimentRequest(BaseModel):
    """Start an A/B experiment routing traffic to a challenger model"""
    challenger_version: str = Field(..., description="Challenger model version")
    traffic_pct: float = Field(0.1, ge=0.0, le=1.0, description="Share of traffic to challenger")
    champion_version: Optional[str] = Field(None, description="Champion version (defaults to production)")
    description: Optional[str] = Field(None, description="Experiment description")


# =====================================================
# API Endpoints
# =====================================================

@app.get("/", response_model=dict)
async def root():
    """Root endpoint"""
    return {
        "service": "Real-Time Fraud Detection API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check(scorer: FraudScorer = Depends(get_fraud_scorer)):
    """Health check endpoint"""
    
    feature_store = get_feature_store()
    
    return HealthResponse(
        status="healthy",
        model_loaded=scorer.model is not None,
        model_version=scorer.model_version,
        feature_store_connected=feature_store._conn is not None
    )


@app.post("/score", response_model=FraudScoreResponse)
async def score_transaction(
    transaction: TransactionRequest,
    background_tasks: BackgroundTasks,
    scorer: FraudScorer = Depends(get_fraud_scorer)
):
    """
    Score a single transaction for fraud
    
    Returns fraud probability, decision, and risk factors.
    """
    
    try:
        start_time = time.time()
        
        # Score transaction
        result = scorer.score_transaction(transaction.dict())
        
        total_time_ms = int((time.time() - start_time) * 1000)
        
        # Log to database in background
        background_tasks.add_task(
            scorer.log_prediction,
            transaction.dict(),
            result
        )
        
        return FraudScoreResponse(
            transaction_id=result["transaction_id"],
            fraud_score=result["fraud_score"],
            decision=result["decision"],
            risk_level=result["risk_level"],
            model_version=result["model_version"],
            model_role=result.get("model_role"),
            reasons=result["reasons"],
            processing_time_ms=total_time_ms,
            feature_retrieval_time_ms=result["feature_retrieval_time_ms"],
            model_inference_time_ms=result["model_inference_time_ms"]
        )

    except Exception as e:
        logger.error(f"Error scoring transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/score/batch", response_model=List[FraudScoreResponse])
async def score_batch(
    batch: BatchTransactionRequest,
    background_tasks: BackgroundTasks,
    scorer: FraudScorer = Depends(get_fraud_scorer)
):
    """
    Score multiple transactions in batch
    
    More efficient than individual scoring for bulk processing.
    """
    
    try:
        results = []
        
        for transaction in batch.transactions:
            result = scorer.score_transaction(transaction.dict())
            
            results.append(FraudScoreResponse(
                transaction_id=result["transaction_id"],
                fraud_score=result["fraud_score"],
                decision=result["decision"],
                risk_level=result["risk_level"],
                model_version=result["model_version"],
                model_role=result.get("model_role"),
                reasons=result["reasons"],
                processing_time_ms=result["feature_retrieval_time_ms"] + result["model_inference_time_ms"],
                feature_retrieval_time_ms=result["feature_retrieval_time_ms"],
                model_inference_time_ms=result["model_inference_time_ms"]
            ))
            
            # Log in background
            background_tasks.add_task(
                scorer.log_prediction,
                transaction.dict(),
                result
            )
        
        return results
    
    except Exception as e:
        logger.error(f"Error scoring batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics", response_model=ModelMetricsResponse)
async def get_metrics(scorer: FraudScorer = Depends(get_fraud_scorer)):
    """Get model performance metrics"""
    
    try:
        metrics = scorer.get_metrics()
        return ModelMetricsResponse(**metrics)
    
    except Exception as e:
        logger.error(f"Error retrieving metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features/{user_id}", response_model=dict)
async def get_user_features(user_id: str):
    """Get feature values for a user (debugging)"""
    
    try:
        feature_store = get_feature_store()
        features = feature_store.get_online_features(
            user_id=user_id,
            transaction_data={}
        )
        return {"user_id": user_id, "features": features}
    
    except Exception as e:
        logger.error(f"Error retrieving features: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/model/reload")
async def reload_model(scorer: FraudScorer = Depends(get_fraud_scorer)):
    """Reload the latest model version"""
    
    try:
        old_version = scorer.model_version
        scorer.load_model()
        new_version = scorer.model_version
        
        return {
            "status": "success",
            "old_version": old_version,
            "new_version": new_version,
            "timestamp": datetime.utcnow()
        }
    
    except Exception as e:
        logger.error(f"Error reloading model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Model Registry & A/B Experiment Endpoints (MLOps)
# =====================================================

@app.get("/registry/models", response_model=dict)
async def list_registered_models(registry: ModelRegistry = Depends(get_registry)):
    """List all registered model versions with their stages and metrics."""
    try:
        models = registry.list_models()
        # JSON-serialize timestamps
        for m in models:
            for k in ("created_at", "promoted_at"):
                if m.get(k) is not None:
                    m[k] = m[k].isoformat()
        return {
            "model_name": registry.model_name,
            "production": registry.get_version_for_stage(STAGE_PRODUCTION),
            "challenger": registry.get_version_for_stage(STAGE_CHALLENGER),
            "count": len(models),
            "models": models,
        }
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/registry/promote")
async def promote_model(
    req: PromoteRequest,
    registry: ModelRegistry = Depends(get_registry),
    scorer: FraudScorer = Depends(get_fraud_scorer),
):
    """Promote a model version to a lifecycle stage and refresh serving."""
    try:
        meta = registry.promote(req.version, req.stage)
        scorer.router.refresh()  # pick up the new champion/challenger
        return {"status": "success", "version": req.version, "stage": req.stage,
                "production": registry.get_version_for_stage(STAGE_PRODUCTION)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error promoting model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ab/experiment", response_model=dict)
async def get_experiment(registry: ModelRegistry = Depends(get_registry)):
    """Get the currently active A/B experiment, if any."""
    exp = registry.get_active_experiment()
    if exp:
        exp["experiment_id"] = str(exp["experiment_id"])
        for k in ("started_at", "stopped_at"):
            if exp.get(k) is not None:
                exp[k] = exp[k].isoformat()
        exp["traffic_pct"] = float(exp["traffic_pct"])
    return {"active": exp is not None, "experiment": exp}


@app.post("/ab/experiment")
async def start_experiment(
    req: ExperimentRequest,
    registry: ModelRegistry = Depends(get_registry),
    scorer: FraudScorer = Depends(get_fraud_scorer),
):
    """Start an A/B experiment routing traffic to a challenger model."""
    try:
        exp = registry.start_experiment(
            challenger_version=req.challenger_version,
            traffic_pct=req.traffic_pct,
            champion_version=req.champion_version,
            description=req.description,
        )
        scorer.router.refresh()
        exp["experiment_id"] = str(exp["experiment_id"])
        exp["traffic_pct"] = float(exp["traffic_pct"])
        return {"status": "started", "experiment_id": exp["experiment_id"],
                "champion": exp["champion_version"], "challenger": exp["challenger_version"],
                "traffic_pct": exp["traffic_pct"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting experiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/ab/experiment")
async def stop_experiment(
    registry: ModelRegistry = Depends(get_registry),
    scorer: FraudScorer = Depends(get_fraud_scorer),
):
    """Stop the active A/B experiment; all traffic returns to the champion."""
    try:
        registry.stop_experiment()
        scorer.router.refresh()
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Error stopping experiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/drift/status", response_model=dict)
async def drift_status():
    """Latest drift detection runs and any auto-rollback actions taken."""
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
                "SELECT * FROM drift_reports ORDER BY run_at DESC LIMIT 10"
            )
            rows = cur.fetchall()
        conn.close()
        for r in rows:
            r["report_id"] = str(r["report_id"])
            if r.get("run_at"):
                r["run_at"] = r["run_at"].isoformat()
            for k in ("drift_share",):
                if r.get(k) is not None:
                    r[k] = float(r[k])
        return {"count": len(rows), "reports": rows}
    except Exception as e:
        logger.error(f"Error retrieving drift status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/feature-store/freshness", response_model=dict)
async def feature_store_freshness():
    """Report feature freshness/staleness from the feature store."""
    try:
        feature_store = get_feature_store()
        return {"features": feature_store.get_feature_freshness()}
    except Exception as e:
        logger.error(f"Error retrieving feature freshness: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Startup/Shutdown Events
# =====================================================

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Fraud Detection API...")
    
    # Initialize fraud scorer
    global fraud_scorer
    fraud_scorer = FraudScorer()
    
    logger.info(f"Model loaded: {fraud_scorer.model_version}")
    logger.info("API ready to accept requests")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Fraud Detection API...")
    
    # Close feature store connection
    feature_store = get_feature_store()
    feature_store.close()
    
    logger.info("Shutdown complete")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
