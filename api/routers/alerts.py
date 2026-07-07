from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import AlertCreate, AlertOut
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import AlertCreate, AlertOut

router = APIRouter(prefix="/alerts", tags=["Alerts"])
security = HTTPBearer(auto_error=False)


def _row_to_alert(row: Any) -> AlertOut:
    return AlertOut(
        id=row["id"],
        symbol=row["symbol"],
        market=row["market"],
        alert_type=row["alert_type"],
        value=float(row["value"]),
        description=row["description"] if "description" in row.keys() else None,
        created_at=row["created_at"],
        active=bool(row["active"]),
    )


@router.get("", response_model=list[AlertOut])
def list_alerts(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> list[AlertOut]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, symbol, market, alert_type, value, description, created_at, active FROM alerts WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_row_to_alert(row) for row in rows]


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(payload: AlertCreate, credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> AlertOut:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO alerts (user_id, symbol, market, alert_type, value, description, created_at, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (user["id"], payload.symbol, payload.market, payload.alert_type, payload.value, payload.description, now),
        )
        alert_id = cursor.lastrowid
    return AlertOut(id=alert_id, symbol=payload.symbol, market=payload.market, alert_type=payload.alert_type, value=payload.value, description=payload.description, created_at=now, active=True)


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    with get_db_connection() as conn:
        deleted = conn.execute("DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user["id"]))
        conn.commit()
    if deleted.rowcount == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert deleted", "id": alert_id}
