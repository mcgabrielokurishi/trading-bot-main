import json
from typing import Any

import requests

try:
    from api.database import get_db_connection
except ImportError:  # pragma: no cover
    from database import get_db_connection


class NotificationService:
    def create(self, user_id: int, title: str, message: str, kind: str = "info") -> int:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO notifications (user_id, title, message, kind, created_at, read_flag) VALUES (?, ?, ?, ?, datetime('now'), 0)",
                (user_id, title, message, kind),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, title, message, kind, created_at, read_flag FROM notifications WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def dispatch_webhook(self, webhook_url: str, payload: dict[str, Any]) -> bool:
        try:
            requests.post(webhook_url, json=payload, timeout=5)
            return True
        except Exception:
            return False


notification_service = NotificationService()
