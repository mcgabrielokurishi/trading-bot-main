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
            "full_name": "Extended User",
        },
    )
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    return token


def test_watchlist_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)

    headers = {"Authorization": f"Bearer {token}"}
    add_response = client.post(
        "/watchlist/items",
        headers=headers,
        json={"symbol": "BTC/USDT", "market": "crypto", "notes": "Primary watch"},
    )
    assert add_response.status_code == 201, add_response.text

    list_response = client.get("/watchlist", headers=headers)
    assert list_response.status_code == 200
    assert any(item["symbol"] == "BTC/USDT" for item in list_response.json())


def test_alerts_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/alerts",
        headers=headers,
        json={"symbol": "ETH/USDT", "market": "crypto", "alert_type": "price_above", "value": 3000.0},
    )
    assert create_response.status_code == 201, create_response.text
    alert_id = create_response.json()["id"]

    list_response = client.get("/alerts", headers=headers)
    assert list_response.status_code == 200
    assert any(item["id"] == alert_id for item in list_response.json())

    delete_response = client.delete(f"/alerts/{alert_id}", headers=headers)
    assert delete_response.status_code == 200
