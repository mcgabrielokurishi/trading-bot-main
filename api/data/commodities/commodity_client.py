"""
data/commodities/commodity_client.py

Commodity price data aggregator using yfinance futures tickers.
Handles price fetch, term structure, and seasonal calendar.
"""

import pandas as pd
from typing import Optional
from data.stocks.yfinance_client import fetch_ohlcv as yf_ohlcv
from utils.helpers import validate_ohlcv
from utils.logger import get_logger

log = get_logger("commodity_client")

# Front-month and next-month contract tickers
COMMODITY_TICKERS = {
    "gold":        ("GC=F", "GCM24.CMX"),
    "silver":      ("SI=F", "SIK24.CMX"),
    "crude_oil":   ("CL=F", "CLM24.NYM"),
    "natural_gas": ("NG=F", "NGM24.NYM"),
    "corn":        ("ZC=F", "ZCN24.CBT"),
    "wheat":       ("ZW=F", "ZWN24.CBT"),
    "copper":      ("HG=F", "HGK24.CMX"),
    "platinum":    ("PL=F", "PLJ24.NYM"),
}


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 500,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch OHLCV for a commodity futures symbol via yfinance."""
    try:
        df = yf_ohlcv(symbol, timeframe=timeframe, limit=limit, start=start, end=end)
        if df.empty:
            log.warning(f"Empty OHLCV for commodity {symbol}")
        return df
    except Exception as e:
        log.warning(f"Commodity OHLCV failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_ohlcv_multi_timeframe(
    symbol: str,
    timeframes: list[str],
    limit: int = 500,
) -> dict[str, pd.DataFrame]:
    """Fetch commodity OHLCV across multiple timeframes."""
    result = {}
    for tf in timeframes:
        try:
            result[tf] = fetch_ohlcv(symbol, tf, limit)
        except Exception as e:
            log.warning(f"Commodity multi-tf failed for {symbol} @ {tf}: {e}")
    return result


def fetch_term_structure(base_symbol: str, num_contracts: int = 3) -> list[dict]:
    """
    Fetch approximate futures term structure.
    Returns list of {symbol, price} for front and deferred months.
    """
    term = []
    commodity_name = None
    for name, (front, next_month) in COMMODITY_TICKERS.items():
        if front == base_symbol:
            commodity_name = name
            break

    tickers_to_check = [base_symbol]
    if commodity_name:
        _, next_t = COMMODITY_TICKERS.get(commodity_name, (base_symbol, None))
        if next_t:
            tickers_to_check.append(next_t)

    for ticker in tickers_to_check[:num_contracts]:
        try:
            df = fetch_ohlcv(ticker, "1d", 2)
            if not df.empty:
                term.append({"symbol": ticker, "price": float(df["close"].iloc[-1])})
        except Exception:
            pass

    return term


def get_all_commodity_prices() -> dict[str, float]:
    """Fetch latest closing prices for all tracked commodities."""
    prices = {}
    for name, (symbol, _) in COMMODITY_TICKERS.items():
        try:
            df = fetch_ohlcv(symbol, "1d", 2)
            if not df.empty:
                prices[symbol] = float(df["close"].iloc[-1])
        except Exception as e:
            log.debug(f"Price fetch failed for {symbol}: {e}")
    return prices
