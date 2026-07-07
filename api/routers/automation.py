import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import AutomationRuleCreate, AutomationRuleOut
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import AutomationRuleCreate, AutomationRuleOut
    from services.audit import log_event

router = APIRouter(prefix="/automation", tags=["Automation"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/rules", response_model=list[AutomationRuleOut])
def list_rules(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, name, event_type, action, config, created_at FROM automation_rules WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [AutomationRuleOut(id=row["id"], name=row["name"], event_type=row["event_type"], action=row["action"], config=json.loads(row["config"]), created_at=row["created_at"]) for row in rows]


@router.post("/rules", response_model=AutomationRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(payload: AutomationRuleCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO automation_rules (user_id, name, event_type, action, config, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], payload.name, payload.event_type, payload.action, json.dumps(payload.config), now),
        )
        conn.commit()
    log_event(user["id"], "create_automation_rule", "automation_rule", cursor.lastrowid, {"summary": payload.name})
    return AutomationRuleOut(id=cursor.lastrowid, name=payload.name, event_type=payload.event_type, action=payload.action, config=payload.config, created_at=now)
