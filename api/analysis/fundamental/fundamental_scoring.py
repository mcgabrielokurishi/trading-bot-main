"""
analysis/fundamental/fundamental_scoring.py

Routes assets to the appropriate fundamental scorer and returns a
normalized fundamental_score in [-1, +1].
"""

from utils.helpers import clamp
from utils.logger import get_logger
from analysis.fundamental.stock_fundamentals import score_stock, compute_stock_metrics
from analysis.fundamental.crypto_fundamentals import score_crypto, compute_crypto_metrics
from analysis.fundamental.forex_fundamentals import score_forex, compute_forex_metrics
from analysis.fundamental.commodity_fundamentals import score_commodity, compute_commodity_metrics

log = get_logger("fundamental_scoring")

# Market type detection helpers
_CRYPTO_SUFFIXES = {"/USDT", "/USD", "/BTC", "/ETH", "/BNB"}
_FOREX_CURRENCIES = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "USD"}
_COMMODITY_TICKERS = {"GC=F", "SI=F", "CL=F", "NG=F", "ZC=F", "ZW=F", "HG=F", "PL=F"}


def detect_market_type(symbol: str) -> str:
    """Detect whether a symbol is crypto, stock, forex, or commodity."""
    if any(symbol.endswith(s) for s in _CRYPTO_SUFFIXES) or "/" in symbol:
        return "crypto"
    if symbol in _COMMODITY_TICKERS or symbol.endswith("=F"):
        return "commodities"
    # Check forex: format BASE_QUOTE with known currencies
    parts = symbol.split("_")
    if len(parts) == 2 and all(p in _FOREX_CURRENCIES for p in parts):
        return "forex"
    return "stocks"


def get_fundamental_score(symbol: str, market_type: str | None = None) -> dict:
    """
    Route to the appropriate fundamental scorer.

    Args:
        symbol: Asset symbol
        market_type: Override auto-detection ('crypto'|'stocks'|'forex'|'commodities')

    Returns:
        dict with 'fundamental_score' in [-1, +1] and sub-scores
    """
    mtype = market_type or detect_market_type(symbol)

    try:
        if mtype == "crypto":
            return score_crypto(symbol)
        elif mtype == "stocks":
            return score_stock(symbol)
        elif mtype == "forex":
            return score_forex(symbol)
        elif mtype == "commodities":
            return score_commodity(symbol)
        else:
            log.warning(f"Unknown market type '{mtype}' for {symbol}; returning 0")
            return {"symbol": symbol, "fundamental_score": 0.0, "market_type": mtype}
    except Exception as e:
        log.error(f"Fundamental scoring failed for {symbol}: {e}", exc_info=True)
        return {"symbol": symbol, "fundamental_score": 0.0, "error": str(e)}


def get_macro_context() -> dict:
    """
    Fetch macro-level context that applies across all markets.
    Returns a dict of key indicators.
    """
    try:
        from analysis.fundamental.forex_fundamentals import fetch_fred_series
        macro = {}
        from config import FRED_API_KEY
        if FRED_API_KEY:
            macro["fed_funds_rate"] = fetch_fred_series("FEDFUNDS")
            macro["us_cpi_yoy"] = fetch_fred_series("CPIAUCSL")
            macro["us_unemployment"] = fetch_fred_series("UNRATE")
            macro["us_gdp_growth"] = fetch_fred_series("A191RL1Q225SBEA")
            macro["vix"] = fetch_fred_series("VIXCLS")
        return macro
    except Exception as e:
        log.warning(f"Macro context fetch failed: {e}")
        return {}
