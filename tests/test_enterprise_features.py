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
            "full_name": "Enterprise User",
        },
    )
    assert signup.status_code == 201, signup.text
    return signup.json()["access_token"]


def test_team_subscription_and_strategy_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    team_response = client.post("/teams", headers=headers, json={"name": "Alpha Desk", "description": "Quant team"})
    assert team_response.status_code == 201, team_response.text
    team_id = team_response.json()["id"]

    subscription_response = client.post("/subscriptions", headers=headers, json={"plan": "pro", "billing_period": "monthly"})
    assert subscription_response.status_code == 201, subscription_response.text

    strategy_response = client.post(
        "/strategies",
        headers=headers,
        json={"name": "Momentum Breakout", "description": "Trend following", "market": "crypto", "is_public": False},
    )
    assert strategy_response.status_code == 201, strategy_response.text
    strategy_id = strategy_response.json()["id"]

    publish_response = client.post(f"/strategies/{strategy_id}/publish", headers=headers)
    assert publish_response.status_code == 200, publish_response.text

    clone_response = client.post(f"/strategies/{strategy_id}/clone", headers=headers, json={"name": "Momentum Breakout Clone"})
    assert clone_response.status_code == 201, clone_response.text

    teams_response = client.get("/teams", headers=headers)
    assert teams_response.status_code == 200
    assert any(item["id"] == team_id for item in teams_response.json())


def test_automation_audit_and_analytics_flow():
    client = TestClient(app)
    token = _create_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/orders", headers=headers, json={"symbol": "BTC/USDT", "market": "crypto", "side": "buy", "quantity": 0.5, "price": 60000.0})
    client.post("/journal", headers=headers, json={"title": "Journal", "entry_type": "note", "content": "Market update", "tags": "qa"})
    client.post("/alerts", headers=headers, json={"symbol": "ETH/USDT", "market": "crypto", "alert_type": "price_above", "value": 3000.0})

    automation_response = client.post(
        "/automation/rules",
        headers=headers,
        json={"name": "Signal Rule", "event_type": "market_update", "action": "notify", "config": {"symbol": "BTC/USDT"}},
    )
    assert automation_response.status_code == 201, automation_response.text

    analytics_response = client.get("/analytics/portfolio", headers=headers)
    assert analytics_response.status_code == 200, analytics_response.text

    assistant_response = client.post(
        "/assistant/query",
        headers=headers,
        json={"prompt": "Summarize my trading activity and suggest next steps"},
    )
    assert assistant_response.status_code == 200, assistant_response.text

    audit_response = client.get("/audit/logs", headers=headers)
    assert audit_response.status_code == 200, audit_response.text
