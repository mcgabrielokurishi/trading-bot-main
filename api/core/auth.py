import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

try:
    from api.database import get_db_connection
except ImportError:  # pragma: no cover - fallback for direct script execution
    from database import get_db_connection

try:
    from api.config import ACCESS_TOKEN_TTL_MINUTES, SECRET_KEY
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import ACCESS_TOKEN_TTL_MINUTES, SECRET_KEY


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + derived).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        decoded = base64.b64decode(stored_hash.encode("utf-8"))
    except Exception:
        return False
    if len(decoded) < 16:
        return False
    salt = decoded[:16]
    expected = decoded[16:]
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(derived, expected)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("utf-8")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_access_token(subject: str, expires_in_minutes: Optional[int] = None) -> str:
    ttl = expires_in_minutes or ACCESS_TOKEN_TTL_MINUTES
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + (ttl * 60),
        "jti": secrets.token_hex(8),
    }
    header_json = json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header_segment = _b64url_encode(header_json)
    payload_segment = _b64url_encode(payload_json)
    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def verify_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header_segment, payload_segment, signature = parts
    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    expected_signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, _b64url_encode(expected_signature)):
        raise ValueError("Invalid signature")
    payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    if payload.get("exp", 0) < int(time.time()):
        raise ValueError("Token has expired")
    return payload


def get_user_by_identifier(conn, identifier: str) -> Optional[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT id, username, email, password_hash, full_name, created_at, is_active, role FROM users WHERE username = ? OR email = ?",
        (identifier, identifier),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_current_user(token: str) -> dict[str, Any]:
    payload = verify_access_token(token)
    with get_db_connection() as conn:
        user = get_user_by_identifier(conn, payload.get("sub", ""))
    if not user or not user.get("is_active"):
        raise ValueError("User not found")
    return user
