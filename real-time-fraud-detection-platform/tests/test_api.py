"""
Unit Tests for Fraud Detection API
"""

import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from api.main import app

client = TestClient(app)


def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "service" in response.json()


def test_health_check():
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "model_loaded" in data


def test_score_transaction():
    """Test fraud scoring endpoint"""
    transaction = {
        "user_id": "test-user-123",
        "amount": 125.50,
        "currency": "USD",
        "merchant_id": "TestMerchant",
        "merchant_category": "online_retail",
        "country": "US",
        "device_id": "device-123",
        "ip_address": "192.168.1.1",
        "card_last_4": "4242",
        "cvv_match": True,
        "billing_zip_match": True
    }
    
    response = client.post("/score", json=transaction)
    assert response.status_code == 200
    
    data = response.json()
    assert "fraud_score" in data
    assert "decision" in data
    assert "risk_level" in data
    assert 0 <= data["fraud_score"] <= 1
    assert data["decision"] in ["approve", "review", "decline"]


def test_batch_scoring():
    """Test batch scoring endpoint"""
    batch = {
        "transactions": [
            {
                "user_id": "user-1",
                "amount": 50.0,
                "currency": "USD",
                "merchant_id": "Merchant1",
                "country": "US",
                "device_id": "device-1",
                "cvv_match": True,
                "billing_zip_match": True
            },
            {
                "user_id": "user-2",
                "amount": 1500.0,
                "currency": "USD",
                "merchant_id": "HighRiskMerchant",
                "country": "CN",
                "device_id": "device-999",
                "cvv_match": False,
                "billing_zip_match": False
            }
        ]
    }
    
    response = client.post("/score/batch", json=batch)
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2
    assert all("fraud_score" in item for item in data)


def test_invalid_transaction():
    """Test with invalid transaction data"""
    transaction = {
        "user_id": "test-user",
        "amount": -10.0,  # Invalid negative amount
        "merchant_id": "Test"
    }
    
    response = client.post("/score", json=transaction)
    assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
