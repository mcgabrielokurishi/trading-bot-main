from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import StrategyCloneRequest, StrategyCreate, StrategyOut
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import StrategyCloneRequest, StrategyCreate, StrategyOut
    from services.audit import log_event

router = APIRouter(prefix="/strategies", tags=["Strategies"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("", response_model=list[StrategyOut])
def list_strategies(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, market, is_public, owner_id, created_at, updated_at FROM strategies WHERE owner_id = ? OR is_public = 1 ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [StrategyOut(id=row["id"], name=row["name"], description=row["description"], market=row["market"], is_public=bool(row["is_public"]), owner_id=row["owner_id"], created_at=row["created_at"], updated_at=row["updated_at"]) for row in rows]


@router.post("", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def create_strategy(payload: StrategyCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO strategies (name, description, market, is_public, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payload.name, payload.description, payload.market, 1 if payload.is_public else 0, user["id"], now, now),
        )
        conn.commit()
    log_event(user["id"], "create_strategy", "strategy", cursor.lastrowid, {"summary": payload.name})
    return StrategyOut(id=cursor.lastrowid, name=payload.name, description=payload.description, market=payload.market, is_public=payload.is_public, owner_id=user["id"], created_at=now, updated_at=now)


@router.post("/{strategy_id}/publish", response_model=StrategyOut)
def publish_strategy(strategy_id: int, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        strategy = conn.execute("SELECT id, name, description, market, is_public, owner_id, created_at, updated_at FROM strategies WHERE id = ? AND owner_id = ?", (strategy_id, user["id"])).fetchone()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        conn.execute("UPDATE strategies SET is_public = 1, updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), strategy_id))
        conn.commit()
    log_event(user["id"], "publish_strategy", "strategy", strategy_id, {"summary": strategy["name"]})
    return StrategyOut(id=strategy["id"], name=strategy["name"], description=strategy["description"], market=strategy["market"], is_public=True, owner_id=strategy["owner_id"], created_at=strategy["created_at"], updated_at=datetime.now(timezone.utc).isoformat())


@router.post("/{strategy_id}/clone", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def clone_strategy(strategy_id: int, payload: StrategyCloneRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        strategy = conn.execute("SELECT id, name, description, market, is_public FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO strategies (name, description, market, is_public, owner_id, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
            (payload.name or f"{strategy['name']} Clone", strategy['description'], strategy['market'], user['id'], now, now),
        )
        conn.commit()
    log_event(user["id"], "clone_strategy", "strategy", cursor.lastrowid, {"summary": payload.name or strategy['name']})
    return StrategyOut(id=cursor.lastrowid, name=payload.name or f"{strategy['name']} Clone", description=strategy['description'], market=strategy['market'], is_public=False, owner_id=user['id'], created_at=now, updated_at=now)
