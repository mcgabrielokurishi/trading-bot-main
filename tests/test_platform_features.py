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
            "full_name": "Platform User",
        },
    )
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    return username, email, token


def test_orders_journal_and_webhook_flows():
    client = TestClient(app)
    _, _, token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    order_response = client.post(
        "/orders",
        headers=headers,
        json={"symbol": "BTC/USDT", "market": "crypto", "side": "buy", "quantity": 0.25, "price": 65000.0},
    )
    assert order_response.status_code == 201, order_response.text

    journal_response = client.post(
        "/journal",
        headers=headers,
        json={"title": "Trade note", "entry_type": "note", "content": "Scalping plan", "tags": "trading"},
    )
    assert journal_response.status_code == 201, journal_response.text

    webhook_response = client.post(
        "/webhooks",
        headers=headers,
        json={"name": "Signal Hook", "url": "https://example.com/hook", "event_type": "signal"},
    )
    assert webhook_response.status_code == 201, webhook_response.text

    orders_response = client.get("/orders", headers=headers)
    assert orders_response.status_code == 200
    assert any(item["symbol"] == "BTC/USDT" for item in orders_response.json())

    journal_entries = client.get("/journal", headers=headers)
    assert journal_entries.status_code == 200
    assert any(item["title"] == "Trade note" for item in journal_entries.json())

    webhooks = client.get("/webhooks", headers=headers)
    assert webhooks.status_code == 200
    assert any(item["name"] == "Signal Hook" for item in webhooks.json())


def test_password_reset_flow():
    client = TestClient(app)
    username, email, _ = _create_user_and_token(client)

    reset_request = client.post(
        "/auth/password-reset/request",
        json={"email": email},
    )
    assert reset_request.status_code == 200, reset_request.text
    token = reset_request.json()["token"]

    reset_confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": "NewPassword123!"},
    )
    assert reset_confirm.status_code == 200, reset_confirm.text

    login_response = client.post(
        "/auth/login",
        json={"email_or_username": username, "password": "NewPassword123!"},
    )
    assert login_response.status_code == 200, login_response.text
