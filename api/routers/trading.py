from fastapi import APIRouter, Depends, HTTPException, status

try:
    from api.schemas import TradeSignalRequest, TradeSignalResponse
    from api.core.auth import get_current_user
except ImportError:  # pragma: no cover - fallback for direct script execution
    from schemas import TradeSignalRequest, TradeSignalResponse
    from core.auth import get_current_user

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter(prefix="/signals", tags=["Signals"])
security = HTTPBearer(auto_error=False)


@router.post("/{symbol}", response_model=TradeSignalResponse)
async def get_signal(
    symbol: str,
    payload: TradeSignalRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        from api.main import fetch_ohlcv_for_symbol
        from api.config import TIMEFRAMES
        from api.strategies.multi_factor_strategy import MultiFactorStrategy
    except ImportError:  # pragma: no cover - fallback for direct script execution
        from main import fetch_ohlcv_for_symbol
        from config import TIMEFRAMES
        from strategies.multi_factor_strategy import MultiFactorStrategy

    data = fetch_ohlcv_for_symbol(symbol, payload.market, TIMEFRAMES)

    try:
        strategy = MultiFactorStrategy(None, None, "balanced")
        signal = strategy.evaluate(symbol=symbol, ohlcv_by_tf=data, market_type=payload.market)
        return {
            "symbol": symbol,
            "direction": signal.direction,
            "score": round(signal.final_score, 4),
            "market": payload.market,
            "message": signal.reason,
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "direction": "hold",
            "score": 0.0,
            "market": payload.market,
            "message": f"Signal generation unavailable: {exc}",
        }