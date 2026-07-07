from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import OrderCreate, OrderOut
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import OrderCreate, OrderOut

router = APIRouter(prefix="/orders", tags=["Orders"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("", response_model=list[OrderOut])
def list_orders(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, symbol, market, side, quantity, price, status, notes, created_at, updated_at FROM orders WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
        return [
            OrderOut(
                id=row["id"],
                symbol=row["symbol"],
                market=row["market"],
                side=row["side"],
                quantity=row["quantity"],
                price=row["price"],
                status=row["status"],
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO orders (user_id, symbol, market, side, quantity, price, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (user["id"], payload.symbol, payload.market, payload.side, payload.quantity, payload.price, payload.notes, now, now),
        )
        conn.commit()
        order_id = cursor.lastrowid
        return OrderOut(
            id=order_id,
            symbol=payload.symbol,
            market=payload.market,
            side=payload.side,
            quantity=payload.quantity,
            price=payload.price,
            status="pending",
            notes=payload.notes,
            created_at=now,
            updated_at=now,
        )
