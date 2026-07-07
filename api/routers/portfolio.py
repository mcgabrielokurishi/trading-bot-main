from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])
security = HTTPBearer(auto_error=False)


@router.get("/summary")
def get_portfolio_summary(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)

    with get_db_connection() as conn:
        watch_count = conn.execute("SELECT COUNT(*) FROM watchlist_items WHERE user_id = ?", (user["id"],)).fetchone()[0]
        alert_count = conn.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user["id"],)).fetchone()[0]

    return {
        "user_id": user["id"],
        "username": user["username"],
        "portfolio_value": 100000.0,
        "cash": 100000.0,
        "open_positions": 0,
        "watchlist_count": watch_count,
        "alerts_count": alert_count,
        "status": "paper-trading-ready",
    }
