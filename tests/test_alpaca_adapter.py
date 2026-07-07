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
            "full_name": "Alpaca User",
        },
    )
    assert signup.status_code == 201, signup.text
    return signup.json()["access_token"]


def test_alpaca_paper_connection_and_order():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    connect_response = client.post(
        "/brokers/alpaca/connect",
        headers=headers,
        json={"api_key": "paper-key", "secret_key": "paper-secret", "paper": True},
    )
    assert connect_response.status_code == 201, connect_response.text

    order_response = client.post(
        "/brokers/alpaca/orders",
        headers=headers,
        json={"symbol": "AAPL", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert order_response.status_code == 200, order_response.text
    assert order_response.json()["status"] in {"submitted", "paper_ready"}
