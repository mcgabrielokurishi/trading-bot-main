from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import BrokerConnectRequest, BrokerConnectionOut, ExecutionCreate, ExecutionOut, PositionOut, ReconciliationOut
    from api.services.audit import log_event
    from api.services.broker import broker_service
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import BrokerConnectRequest, BrokerConnectionOut, ExecutionCreate, ExecutionOut, PositionOut, ReconciliationOut
    from services.audit import log_event
    from services.broker import broker_service

router = APIRouter(tags=["Brokers"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/brokers/{provider}/connect", response_model=BrokerConnectionOut, status_code=status.HTTP_201_CREATED)
def connect_broker(provider: str, payload: BrokerConnectRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    connection = broker_service.connect(user["id"], provider, payload.api_key, payload.secret_key, payload.paper)
    log_event(user["id"], "connect_broker", "broker", None, {"summary": provider})
    return BrokerConnectionOut(provider=connection.provider, api_key=connection.api_key, secret_key=connection.secret_key, paper=connection.paper)


@router.post("/executions", response_model=ExecutionOut, status_code=status.HTTP_201_CREATED)
def create_execution(payload: ExecutionCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO executions (user_id, symbol, side, quantity, price, status, created_at) VALUES (?, ?, ?, ?, ?, 'submitted', ?)",
            (user["id"], payload.symbol, payload.side, payload.quantity, payload.price, now),
        )
        conn.commit()
    log_event(user["id"], "create_execution", "execution", cursor.lastrowid, {"summary": payload.symbol})
    return ExecutionOut(id=cursor.lastrowid, symbol=payload.symbol, side=payload.side, quantity=payload.quantity, price=payload.price, status="submitted", created_at=now)


@router.get("/positions", response_model=list[PositionOut])
def list_positions(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, symbol, quantity, price, created_at FROM positions WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [PositionOut(id=row["id"], symbol=row["symbol"], quantity=row["quantity"], price=row["price"], created_at=row["created_at"]) for row in rows]


@router.post("/positions/sync", response_model=ReconciliationOut)
def sync_positions(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    sync_result = broker_service.sync_positions(user["id"])
    with get_db_connection() as conn:
        for position in sync_result.get("positions", []):
            conn.execute(
                "INSERT OR REPLACE INTO positions (user_id, symbol, quantity, price, created_at) VALUES (?, ?, ?, ?, ?)",
                (user["id"], position["symbol"], position["quantity"], position["price"], datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
    log_event(user["id"], "sync_positions", "position", None, {"summary": "positions synced"})
    return ReconciliationOut(status="synced", positions=sync_result.get("positions", []))


@router.get("/positions/reconcile", response_model=ReconciliationOut)
def reconcile_positions(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT symbol, quantity, price FROM positions WHERE user_id = ?", (user["id"],)).fetchall()
    return ReconciliationOut(status="reconciled", positions=[{"symbol": row["symbol"], "quantity": row["quantity"], "price": row["price"]} for row in rows])
