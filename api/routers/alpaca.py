from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.schemas import AlpacaOrderRequest, AlpacaOrderResponse
    from api.services.alpaca_adapter import alpaca_adapter
    from api.services.audit import log_event
except ImportError:  # pragma: no cover
    from core.auth import get_current_user
    from schemas import AlpacaOrderRequest, AlpacaOrderResponse
    from services.alpaca_adapter import alpaca_adapter
    from services.audit import log_event

router = APIRouter(prefix="/brokers/alpaca", tags=["Alpaca"])
security = HTTPBearer(auto_error=False)


def _get_authenticated_user(credentials: Optional[HTTPAuthorizationCredentials]):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/orders", response_model=AlpacaOrderResponse)
def submit_order(payload: AlpacaOrderRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    user = _get_authenticated_user(credentials)
    result = alpaca_adapter.submit_order(user["id"], payload.symbol, payload.side, payload.quantity, payload.order_type)
    log_event(user["id"], "submit_alpaca_order", "broker", None, {"summary": payload.symbol})
    return AlpacaOrderResponse(**result)
