import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, "api")

from main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_and_login_flow():
    client = TestClient(app)
    username = f"user_{uuid4().hex[:8]}"
    email = f"{username}@example.com"

    signup_response = client.post(
        "/auth/signup",
        json={
            "username": username,
            "email": email,
            "password": "Password123!",
            "full_name": "Test User",
        },
    )

    assert signup_response.status_code == 201, signup_response.text
    signup_payload = signup_response.json()
    assert signup_payload["user"]["username"] == username

    login_response = client.post(
        "/auth/login",
        json={"email_or_username": username, "password": "Password123!"},
    )

    assert login_response.status_code == 200, login_response.text
    assert "access_token" in login_response.json()
