from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import AdminStatsResponse
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import AdminStatsResponse

router = APIRouter(prefix="/admin", tags=["Admin"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        user = get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


@router.get("/stats", response_model=AdminStatsResponse)
def admin_stats(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        users = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        active_alerts = conn.execute("SELECT COUNT(*) AS count FROM alerts WHERE active = 1").fetchone()["count"]
        orders = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
        journal_entries = conn.execute("SELECT COUNT(*) AS count FROM journal_entries").fetchone()["count"]
        notifications = conn.execute("SELECT COUNT(*) AS count FROM notifications").fetchone()["count"]
        webhooks = conn.execute("SELECT COUNT(*) AS count FROM webhooks").fetchone()["count"]
    return AdminStatsResponse(
        users=users,
        active_alerts=active_alerts,
        orders=orders,
        journal_entries=journal_entries,
        notifications=notifications,
        webhooks=webhooks,
    )
