import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, "api")

from main import app


def _create_user_and_token(client: TestClient):
    username = f"user_{uuid4().hex[:8]}"
    email = f"{username}@example.com"
    signup = client.post(
        "/auth/signup",
        json={
            "username": username,
            "email": email,
            "password": "Password123!",
            "full_name": "Real Money User",
        },
    )
    assert signup.status_code == 201, signup.text
    return signup.json()["access_token"]


def test_broker_and_reconciliation_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    broker_response = client.post(
        "/brokers/alpaca/connect",
        headers=headers,
        json={"api_key": "key", "secret_key": "secret", "paper": True},
    )
    assert broker_response.status_code == 201, broker_response.text

    sync_response = client.post("/positions/sync", headers=headers)
    assert sync_response.status_code == 200, sync_response.text

    execution_response = client.post(
        "/executions",
        headers=headers,
        json={"symbol": "AAPL", "side": "buy", "quantity": 1, "price": 100.0},
    )
    assert execution_response.status_code == 201, execution_response.text

    reconciliation_response = client.get("/positions/reconcile", headers=headers)
    assert reconciliation_response.status_code == 200, reconciliation_response.text


def test_billing_and_webhook_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    billing_response = client.post(
        "/billing/checkout",
        headers=headers,
        json={"plan": "pro", "currency": "USD"},
    )
    assert billing_response.status_code == 201, billing_response.text

    webhook_response = client.post(
        "/billing/webhooks",
        headers=headers,
        json={"provider": "stripe", "event": "checkout.session.completed", "payload": {"id": "evt_123"}},
    )
    assert webhook_response.status_code == 201, webhook_response.text
