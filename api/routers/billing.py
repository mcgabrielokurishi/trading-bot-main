from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.schemas import BillingCheckoutRequest, BillingCheckoutResponse, BillingWebhookRequest, BillingWebhookResponse
    from api.services.audit import log_event
    from api.services.billing import billing_service
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from schemas import BillingCheckoutRequest, BillingCheckoutResponse, BillingWebhookRequest, BillingWebhookResponse
    from services.audit import log_event
    from services.billing import billing_service

router = APIRouter(prefix="/billing", tags=["Billing"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/checkout", response_model=BillingCheckoutResponse, status_code=status.HTTP_201_CREATED)
def create_checkout(payload: BillingCheckoutRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    checkout = billing_service.create_checkout(user["id"], payload.plan, payload.currency)
    log_event(user["id"], "create_checkout", "billing", checkout.id, {"summary": payload.plan})
    return BillingCheckoutResponse(id=checkout.id, plan=checkout.plan, currency=checkout.currency, status=checkout.status, created_at=checkout.created_at)


@router.post("/webhooks", response_model=BillingWebhookResponse, status_code=status.HTTP_201_CREATED)
def record_webhook(payload: BillingWebhookRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    result = billing_service.record_webhook(user["id"], payload.provider, payload.event, payload.payload)
    log_event(user["id"], "billing_webhook", "billing", None, {"summary": payload.event})
    return BillingWebhookResponse(status=result["status"], provider=result["provider"], event=result["event"])
