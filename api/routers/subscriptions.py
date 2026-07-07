from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.database import get_db_connection
    from api.schemas import InvoiceOut, SubscriptionCreate, SubscriptionOut
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from database import get_db_connection
    from schemas import InvoiceOut, SubscriptionCreate, SubscriptionOut
    from services.audit import log_event

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
def create_subscription(payload: SubscriptionCreate, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO subscriptions (user_id, plan, status, billing_period, created_at) VALUES (?, ?, 'active', ?, ?)",
            (user["id"], payload.plan, payload.billing_period, now),
        )
        conn.execute(
            "INSERT INTO invoices (user_id, subscription_id, amount, currency, status, created_at) VALUES (?, ?, ?, ?, 'paid', ?)",
            (user["id"], cursor.lastrowid, 99.0 if payload.plan == 'pro' else 19.0, 'USD', now),
        )
        conn.commit()
    log_event(user["id"], "create_subscription", "subscription", cursor.lastrowid, {"summary": payload.plan})
    return SubscriptionOut(id=cursor.lastrowid, plan=payload.plan, status="active", billing_period=payload.billing_period, created_at=now)


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, plan, status, billing_period, created_at FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [SubscriptionOut(id=row["id"], plan=row["plan"], status=row["status"], billing_period=row["billing_period"], created_at=row["created_at"]) for row in rows]


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, subscription_id, amount, currency, status, created_at FROM invoices WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [InvoiceOut(id=row["id"], subscription_id=row["subscription_id"], amount=row["amount"], currency=row["currency"], status=row["status"], created_at=row["created_at"]) for row in rows]
