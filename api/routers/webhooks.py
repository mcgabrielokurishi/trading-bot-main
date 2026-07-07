from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import WebhookCreate, WebhookOut
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import WebhookCreate, WebhookOut

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("", response_model=list[WebhookOut])
def list_webhooks(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, url, event_type, active, created_at FROM webhooks WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
        return [
            WebhookOut(
                id=row["id"],
                name=row["name"],
                url=row["url"],
                event_type=row["event_type"],
                active=bool(row["active"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
def create_webhook(payload: WebhookCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO webhooks (user_id, name, url, event_type, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (user["id"], payload.name, payload.url, payload.event_type, now),
        )
        conn.commit()
        return WebhookOut(
            id=cursor.lastrowid,
            name=payload.name,
            url=payload.url,
            event_type=payload.event_type,
            active=True,
            created_at=now,
        )
