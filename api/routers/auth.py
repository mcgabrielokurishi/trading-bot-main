import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.config import ACCESS_TOKEN_TTL_MINUTES
    from api.core.auth import create_access_token, get_current_user, get_user_by_identifier, hash_password, verify_password
    from api.database import get_db_connection
    from api.schemas import PasswordResetConfirmRequest, PasswordResetRequest, TokenResponse, UserCreate, UserLogin, UserOut, VerifyEmailRequest
    from api.services.email import email_service
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import ACCESS_TOKEN_TTL_MINUTES
    from core.auth import create_access_token, get_current_user, get_user_by_identifier, hash_password, verify_password
    from database import get_db_connection
    from schemas import PasswordResetConfirmRequest, PasswordResetRequest, TokenResponse, UserCreate, UserLogin, UserOut, VerifyEmailRequest
    from services.email import email_service

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)


def _user_to_out(row: dict[str, Any]) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        full_name=row.get("full_name"),
        created_at=row["created_at"],
        is_active=bool(row["is_active"]),
        role=row.get("role", "user"),
    )


def _create_token(conn, user_id: int, token_type: str, ttl_minutes: int = 60) -> str:
    token_value = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
    conn.execute(
        "INSERT INTO account_tokens (user_id, token_type, token_value, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, ?, NULL)",
        (user_id, token_type, token_value, datetime.now(timezone.utc).isoformat(), expires_at),
    )
    return token_value


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate):
    with get_db_connection() as conn:
        existing = get_user_by_identifier(conn, payload.username)
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists")
        existing = get_user_by_identifier(conn, payload.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")

        now = datetime.now(timezone.utc).isoformat()
        password_hash = hash_password(payload.password)
        cursor = conn.execute(
            """
            INSERT INTO users (username, email, password_hash, full_name, created_at, updated_at, is_active, role)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'user')
            """,
            (payload.username, payload.email, password_hash, payload.full_name, now, now),
        )
        user_id = cursor.lastrowid
        user = {
            "id": user_id,
            "username": payload.username,
            "email": payload.email,
            "full_name": payload.full_name,
            "created_at": now,
            "is_active": 1,
            "role": "user",
        }
        access_token = create_access_token(user["email"])
        return TokenResponse(access_token=access_token, expires_in=ACCESS_TOKEN_TTL_MINUTES * 60, user=_user_to_out(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin):
    with get_db_connection() as conn:
        user = get_user_by_identifier(conn, payload.email_or_username)
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.get("is_active"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
        access_token = create_access_token(user["email"])
        return TokenResponse(access_token=access_token, expires_in=ACCESS_TOKEN_TTL_MINUTES * 60, user=_user_to_out(user))


@router.post("/verify-email/request")
def request_email_verification(payload: PasswordResetRequest):
    with get_db_connection() as conn:
        user = get_user_by_identifier(conn, payload.email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        token = _create_token(conn, user["id"], "email_verification")
        email_service.send(
            user["email"],
            "Verify your email",
            f"Use this token to verify your account: {token}",
        )
        return {"message": "Verification email sent", "token": token}


@router.post("/verify-email/confirm")
def confirm_email_verification(payload: VerifyEmailRequest):
    with get_db_connection() as conn:
        token_row = conn.execute(
            "SELECT id, user_id, expires_at, used_at FROM account_tokens WHERE token_type = ? AND token_value = ?",
            ("email_verification", payload.token),
        ).fetchone()
        if not token_row:
            raise HTTPException(status_code=404, detail="Token not found")
        if token_row["used_at"]:
            raise HTTPException(status_code=409, detail="Token already used")
        if datetime.fromisoformat(token_row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Token expired")
        conn.execute("UPDATE account_tokens SET used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), token_row["id"]))
        conn.commit()
        return {"message": "Email verified successfully"}


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest):
    with get_db_connection() as conn:
        user = get_user_by_identifier(conn, payload.email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        token = _create_token(conn, user["id"], "password_reset")
        email_service.send(
            user["email"],
            "Reset your password",
            f"Use this token to reset your password: {token}",
        )
        return {"message": "Password reset email sent", "token": token}


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirmRequest):
    with get_db_connection() as conn:
        token_row = conn.execute(
            "SELECT id, user_id, expires_at, used_at FROM account_tokens WHERE token_type = ? AND token_value = ?",
            ("password_reset", payload.token),
        ).fetchone()
        if not token_row:
            raise HTTPException(status_code=404, detail="Token not found")
        if token_row["used_at"]:
            raise HTTPException(status_code=409, detail="Token already used")
        if datetime.fromisoformat(token_row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Token expired")
        password_hash = hash_password(payload.new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, token_row["user_id"]))
        conn.execute("UPDATE account_tokens SET used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), token_row["id"]))
        conn.commit()
        return {"message": "Password reset successfully"}


@router.get("/me", response_model=UserOut)
def get_me(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        user = get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _user_to_out(user)
