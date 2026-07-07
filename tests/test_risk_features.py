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
            "full_name": "Risk User",
        },
    )
    assert signup.status_code == 201, signup.text
    return signup.json()["access_token"]


def test_risk_limits_and_scan_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_limit = client.post(
        "/risk/limits",
        headers=headers,
        json={"max_drawdown": 0.15, "max_position_size": 0.2, "max_daily_loss": 0.04},
    )
    assert create_limit.status_code == 201, create_limit.text

    scan_response = client.post("/risk/scan", headers=headers)
    assert scan_response.status_code == 200, scan_response.text
    assert scan_response.json()["status"] in {"ok", "warning"}
