from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import JournalEntryCreate, JournalEntryOut
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import JournalEntryCreate, JournalEntryOut

router = APIRouter(prefix="/journal", tags=["Journal"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("", response_model=list[JournalEntryOut])
def list_entries(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, entry_type, content, tags, created_at FROM journal_entries WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
        return [
            JournalEntryOut(
                id=row["id"],
                title=row["title"],
                entry_type=row["entry_type"],
                content=row["content"],
                tags=row["tags"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@router.post("", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(payload: JournalEntryCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO journal_entries (user_id, title, entry_type, content, tags, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], payload.title, payload.entry_type, payload.content, payload.tags, now),
        )
        conn.commit()
        return JournalEntryOut(
            id=cursor.lastrowid,
            title=payload.title,
            entry_type=payload.entry_type,
            content=payload.content,
            tags=payload.tags,
            created_at=now,
        )
