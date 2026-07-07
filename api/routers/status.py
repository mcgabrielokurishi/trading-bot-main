from fastapi import APIRouter

try:
    from api.config import ACTIVE_PRESET, COMMODITY_SYMBOLS, CRYPTO_SYMBOLS, FOREX_PAIRS, STOCK_SYMBOLS, TRADING_MODE
    from api.schemas import StatusResponse
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import ACTIVE_PRESET, COMMODITY_SYMBOLS, CRYPTO_SYMBOLS, FOREX_PAIRS, STOCK_SYMBOLS, TRADING_MODE
    from schemas import StatusResponse

router = APIRouter(prefix="/status", tags=["Status"])


@router.get("/", response_model=StatusResponse)
async def get_status() -> dict:
    return {
        "mode": TRADING_MODE,
        "preset": ACTIVE_PRESET,
        "crypto": len(CRYPTO_SYMBOLS),
        "stocks": len(STOCK_SYMBOLS),
        "forex": len(FOREX_PAIRS),
        "commodities": len(COMMODITY_SYMBOLS),
        "authenticated": True,
    }


@router.get("/portfolio")
async def get_portfolio_summary() -> dict:
    return {
        "portfolio_value": 100000.0,
        "cash": 100000.0,
        "positions": 0,
        "mode": TRADING_MODE,
        "status": "paper-trading-ready",
    }