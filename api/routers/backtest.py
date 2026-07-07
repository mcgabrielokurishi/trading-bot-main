from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from api.core.auth import get_current_user
    from api.schemas import BacktestRequest, BacktestResponse
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from schemas import BacktestRequest, BacktestResponse

router = APIRouter(prefix="/backtest", tags=["Backtest"])
security = HTTPBearer(auto_error=False)


@router.post("/", response_model=BacktestResponse)
async def run_backtest_api(
    req: BacktestRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        get_current_user(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        from api.main import run_backtest
    except ImportError:  # pragma: no cover - fallback for direct script execution
        from main import run_backtest

    run_backtest(req.symbol, req.start, req.end, req.market)

    return {
        "message": "Backtest started",
        "symbol": req.symbol,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }