from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import NotificationOut
    from api.services.notifications import notification_service
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import NotificationOut
    from services.notifications import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("", response_model=list[NotificationOut])
def list_notifications(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    rows = notification_service.list_for_user(user["id"])
    return [
        NotificationOut(
            id=row["id"],
            title=row["title"],
            message=row["message"],
            kind=row["kind"],
            created_at=row["created_at"],
            read_flag=bool(row["read_flag"]),
        )
        for row in rows
    ]


@router.post("/mark-read")
def mark_all_read(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        conn.execute("UPDATE notifications SET read_flag = 1 WHERE user_id = ?", (user["id"],))
        conn.commit()
    return {"message": "Notifications marked as read"}
