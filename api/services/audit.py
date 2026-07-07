from datetime import datetime, timezone
from typing import Any

try:
    from api.database import get_db_connection
except ImportError:  # pragma: no cover
    from database import get_db_connection


def log_event(user_id: int, action: str, target_type: str, target_id: int | None = None, details: dict[str, Any] | None = None) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs (user_id, action, target_type, target_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                action,
                target_type,
                target_id,
                (details or {}).get("summary") if isinstance(details, dict) else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def list_logs_for_user(user_id: int) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, action, target_type, target_id, details, created_at FROM audit_logs WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
