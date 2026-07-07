from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.schemas import AuditLogOut
    from api.services.audit import list_logs_for_user
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from schemas import AuditLogOut
    from services.audit import list_logs_for_user

router = APIRouter(prefix="/audit", tags=["Audit"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/logs", response_model=list[AuditLogOut])
def list_audit_logs(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    rows = list_logs_for_user(user["id"])
    return [AuditLogOut(id=row["id"], action=row["action"], target_type=row["target_type"], target_id=row.get("target_id"), details=row.get("details"), created_at=row["created_at"]) for row in rows]
