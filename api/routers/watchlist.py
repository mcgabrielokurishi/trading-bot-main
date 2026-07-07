from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import WatchlistItemCreate, WatchlistItemOut
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import WatchlistItemCreate, WatchlistItemOut

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])
security = HTTPBearer(auto_error=False)


def _row_to_item(row: Any) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=row["id"],
        symbol=row["symbol"],
        market=row["market"],
        notes=row["notes"] if "notes" in row.keys() else None,
        created_at=row["created_at"],
    )


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> list[WatchlistItemOut]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, symbol, market, notes, created_at FROM watchlist_items WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_row_to_item(row) for row in rows]


@router.post("/items", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
def add_watchlist_item(payload: WatchlistItemCreate, credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> WatchlistItemOut:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM watchlist_items WHERE user_id = ? AND symbol = ?",
            (user["id"], payload.symbol),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Symbol already in watchlist")
        cursor = conn.execute(
            "INSERT INTO watchlist_items (user_id, symbol, market, notes, created_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], payload.symbol, payload.market, payload.notes, now),
        )
        item_id = cursor.lastrowid
    return WatchlistItemOut(id=item_id, symbol=payload.symbol, market=payload.market, notes=payload.notes, created_at=now)


@router.delete("/items/{symbol}")
def remove_watchlist_item(symbol: str, credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, str]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_current_user(credentials.credentials)
    with get_db_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM watchlist_items WHERE user_id = ? AND symbol = ?",
            (user["id"], symbol),
        )
        conn.commit()
    if deleted.rowcount == 0:
        raise HTTPException(status_code=404, detail="Symbol not found in watchlist")
    return {"message": "Removed from watchlist", "symbol": symbol}
