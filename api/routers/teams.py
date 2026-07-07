from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import TeamCreate, TeamMemberOut, TeamOut
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import TeamCreate, TeamMemberOut, TeamOut
    from services.audit import log_event

router = APIRouter(prefix="/teams", tags=["Teams"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO teams (name, description, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (payload.name, payload.description, user["id"], now),
        )
        conn.execute(
            "INSERT INTO team_memberships (team_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
            (cursor.lastrowid, user["id"], now),
        )
        conn.commit()
    log_event(user["id"], "create_team", "team", cursor.lastrowid, {"summary": payload.name})
    return TeamOut(id=cursor.lastrowid, name=payload.name, description=payload.description, owner_id=user["id"], created_at=now)


@router.get("", response_model=list[TeamOut])
def list_teams(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t JOIN team_memberships tm ON tm.team_id = t.id WHERE tm.user_id = ? ORDER BY t.created_at DESC",
            (user["id"],),
        ).fetchall()
    return [TeamOut(id=row["id"], name=row["name"], description=row["description"], owner_id=row["owner_id"], created_at=row["created_at"]) for row in rows]


@router.post("/{team_id}/members", response_model=TeamMemberOut)
def add_member(team_id: int, payload: dict[str, str], credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        team = conn.execute("SELECT id, owner_id FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if team["owner_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Only team owners can add members")
        member_identifier = payload.get("username") or payload.get("email")
        if not member_identifier:
            raise HTTPException(status_code=400, detail="username or email is required")
        member_row = conn.execute("SELECT id, username, email FROM users WHERE username = ? OR email = ?", (member_identifier, member_identifier)).fetchone()
        if not member_row:
            raise HTTPException(status_code=404, detail="User not found")
        existing = conn.execute("SELECT id FROM team_memberships WHERE team_id = ? AND user_id = ?", (team_id, member_row["id"])).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="User already a member")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO team_memberships (team_id, user_id, role, created_at) VALUES (?, ?, 'member', ?)", (team_id, member_row["id"], now))
        conn.commit()
    log_event(user["id"], "add_team_member", "team", team_id, {"summary": member_identifier})
    return TeamMemberOut(id=member_row["id"], username=member_row["username"], email=member_row["email"], role="member")
