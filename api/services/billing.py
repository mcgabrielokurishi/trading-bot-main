from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from api.database import get_db_connection
except ImportError:  # pragma: no cover
    from database import get_db_connection


@dataclass
class CheckoutSession:
    id: int
    plan: str
    currency: str
    status: str
    created_at: str


class BillingService:
    def create_checkout(self, user_id: int, plan: str, currency: str = "USD") -> CheckoutSession:
        now = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO billing_sessions (user_id, plan, currency, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (user_id, plan, currency, now),
            )
            conn.commit()
            return CheckoutSession(id=cursor.lastrowid, plan=plan, currency=currency, status="pending", created_at=now)

    def record_webhook(self, user_id: int, provider: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO billing_webhooks (user_id, provider, event_name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, provider, event, str(payload), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return {"status": "recorded", "provider": provider, "event": event}


billing_service = BillingService()
