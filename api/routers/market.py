from fastapi import APIRouter

try:
    from api.config import ACTIVE_PRESET, COMMODITY_SYMBOLS, CRYPTO_SYMBOLS, FOREX_PAIRS, STOCK_SYMBOLS, TRADING_MODE
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import ACTIVE_PRESET, COMMODITY_SYMBOLS, CRYPTO_SYMBOLS, FOREX_PAIRS, STOCK_SYMBOLS, TRADING_MODE

router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/overview")
def market_overview() -> dict:
    return {
        "mode": TRADING_MODE,
        "preset": ACTIVE_PRESET,
        "crypto_symbols": len(CRYPTO_SYMBOLS),
        "stock_symbols": len(STOCK_SYMBOLS),
        "forex_pairs": len(FOREX_PAIRS),
        "commodity_symbols": len(COMMODITY_SYMBOLS),
        "supported_markets": ["crypto", "stocks", "forex", "commodities"],
    }
