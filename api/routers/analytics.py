from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import AnalyticsSummaryResponse
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import AnalyticsSummaryResponse

router = APIRouter(prefix="/analytics", tags=["Analytics"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/portfolio", response_model=AnalyticsSummaryResponse)
def portfolio_summary(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        orders = conn.execute("SELECT COUNT(*) AS count FROM orders WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        alerts = conn.execute("SELECT COUNT(*) AS count FROM alerts WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        journal_entries = conn.execute("SELECT COUNT(*) AS count FROM journal_entries WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        positions = conn.execute("SELECT SUM(quantity) AS qty FROM orders WHERE user_id = ? AND status = 'pending'", (user["id"],)).fetchone()["qty"] or 0
        return AnalyticsSummaryResponse(
            user_id=user["id"],
            total_orders=orders,
            active_alerts=alerts,
            journal_entries=journal_entries,
            open_positions=float(positions),
            estimated_exposure=float(positions) * 1000.0,
            summary=f"You have {orders} orders, {alerts} active alerts, and {journal_entries} journal entries.",
        )
