from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import RiskLimitCreate, RiskLimitOut, RiskScanResponse
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import RiskLimitCreate, RiskLimitOut, RiskScanResponse
    from services.audit import log_event

router = APIRouter(prefix="/risk", tags=["Risk"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/limits", response_model=RiskLimitOut, status_code=status.HTTP_201_CREATED)
def create_limit(payload: RiskLimitCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO risk_limits (user_id, max_drawdown, max_position_size, max_daily_loss, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], payload.max_drawdown, payload.max_position_size, payload.max_daily_loss, now),
        )
        conn.commit()
    log_event(user["id"], "create_risk_limit", "risk_limit", cursor.lastrowid, {"summary": "risk limit configured"})
    return RiskLimitOut(id=cursor.lastrowid, max_drawdown=payload.max_drawdown, max_position_size=payload.max_position_size, max_daily_loss=payload.max_daily_loss, created_at=now)


@router.get("/limits", response_model=list[RiskLimitOut])
def list_limits(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, max_drawdown, max_position_size, max_daily_loss, created_at FROM risk_limits WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [RiskLimitOut(id=row["id"], max_drawdown=row["max_drawdown"], max_position_size=row["max_position_size"], max_daily_loss=row["max_daily_loss"], created_at=row["created_at"]) for row in rows]


@router.post("/scan", response_model=RiskScanResponse)
def scan_risk(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        open_positions = conn.execute("SELECT COUNT(*) AS count FROM positions WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        active_orders = conn.execute("SELECT COUNT(*) AS count FROM orders WHERE user_id = ? AND status = 'pending'", (user["id"],)).fetchone()["count"]
        limits = conn.execute("SELECT max_drawdown, max_position_size, max_daily_loss FROM risk_limits WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user["id"],)).fetchone()
    max_drawdown = limits["max_drawdown"] if limits else 0.2
    max_position_size = limits["max_position_size"] if limits else 0.25
    max_daily_loss = limits["max_daily_loss"] if limits else 0.05
    status = "ok"
    if open_positions > 0 and max_position_size <= 0.1:
        status = "warning"
    return RiskScanResponse(status=status, open_positions=open_positions, active_orders=active_orders, max_drawdown=max_drawdown, max_position_size=max_position_size, max_daily_loss=max_daily_loss)
