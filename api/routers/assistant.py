from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import AssistantQueryRequest, AssistantResponse
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import AssistantQueryRequest, AssistantResponse

router = APIRouter(prefix="/assistant", tags=["Assistant"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/query", response_model=AssistantResponse)
def assistant_query(payload: AssistantQueryRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        order_count = conn.execute("SELECT COUNT(*) AS count FROM orders WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        journal_count = conn.execute("SELECT COUNT(*) AS count FROM journal_entries WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        alert_count = conn.execute("SELECT COUNT(*) AS count FROM alerts WHERE user_id = ?", (user["id"],)).fetchone()["count"]
    summary = (
        f"You have {order_count} orders, {journal_count} journal entries, and {alert_count} active alerts. "
        f"Based on your prompt, I recommend reviewing recent orders and keeping risk limits aligned with your current exposure."
    )
    return AssistantResponse(summary=summary, suggested_actions=["Review current positions", "Check journal notes", "Refresh alerts"])
