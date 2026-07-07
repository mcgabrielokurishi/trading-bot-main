"""
data/stocks/alpha_vantage_client.py

Alpha Vantage API client for stock prices and fundamental data.
Free tier: 5 requests/min, 500/day.
"""

import pandas as pd
from typing import Optional
from config import ALPHA_VANTAGE_API_KEY
from utils.api_utils import APISession, safe_float
from utils.helpers import validate_ohlcv, retry
from utils.logger import get_logger

log = get_logger("alpha_vantage_client")

AV_BASE = "https://www.alphavantage.co"

TIMEFRAME_TO_FUNCTION = {
    "1m":  "TIME_SERIES_INTRADAY",
    "5m":  "TIME_SERIES_INTRADAY",
    "15m": "TIME_SERIES_INTRADAY",
    "30m": "TIME_SERIES_INTRADAY",
    "1h":  "TIME_SERIES_INTRADAY",
    "1d":  "TIME_SERIES_DAILY_ADJUSTED",
    "1w":  "TIME_SERIES_WEEKLY_ADJUSTED",
    "1M":  "TIME_SERIES_MONTHLY_ADJUSTED",
}

INTRADAY_INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}


def _session() -> APISession:
    return APISession(AV_BASE, "alpha_vantage")


def _params(extra: dict) -> dict:
    return {"apikey": ALPHA_VANTAGE_API_KEY, **extra}


def _parse_time_series(raw: dict, key_prefix: str) -> pd.DataFrame:
    """Parse AV time-series response into a clean OHLCV DataFrame."""
    series_key = next((k for k in raw if "Time Series" in k), None)
    if not series_key:
        return pd.DataFrame()

    rows = []
    for ts_str, candle in raw[series_key].items():
        rows.append({
            "timestamp": pd.Timestamp(ts_str, tz="UTC"),
            "open":   safe_float(candle.get(f"{key_prefix}open")),
            "high":   safe_float(candle.get(f"{key_prefix}high")),
            "low":    safe_float(candle.get(f"{key_prefix}low")),
            "close":  safe_float(candle.get(f"{key_prefix}close")),
            "volume": safe_float(candle.get(f"{key_prefix}volume")),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("timestamp").sort_index()
    return df


@retry(max_attempts=3, delay=12.0, backoff=1.5)  # respect 5 req/min limit
def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 500,
    outputsize: str = "full",
) -> pd.DataFrame:
    """
    Fetch OHLCV from Alpha Vantage.

    Args:
        symbol: Stock ticker e.g. 'AAPL'
        timeframe: '1m','5m','15m','30m','1h','1d','1w','1M'
        limit: Number of bars to return
        outputsize: 'compact' (100) or 'full' (20y for daily)
    """
    if not ALPHA_VANTAGE_API_KEY:
        log.debug(f"No AV key; skipping {symbol}")
        return pd.DataFrame()

    function = TIMEFRAME_TO_FUNCTION.get(timeframe, "TIME_SERIES_DAILY_ADJUSTED")
    session = _session()

    try:
        params: dict = {"function": function, "symbol": symbol, "outputsize": outputsize}
        if timeframe in INTRADAY_INTERVALS:
            params["interval"] = INTRADAY_INTERVALS[timeframe]
            params["extended_hours"] = "false"

        raw = session.get("query", params=_params(params))
        if not raw:
            return pd.DataFrame()

        if "Error Message" in raw or "Note" in raw:
            msg = raw.get("Error Message") or raw.get("Note", "")
            log.warning(f"AV API message for {symbol}: {msg[:100]}")
            return pd.DataFrame()

        # Key prefix varies by function
        if "ADJUSTED" in function:
            key_prefix = "5. adjusted " if timeframe == "1d" else "4. close"
            df = _parse_time_series(raw, "")
            # Adjust column names from AV format
            series_key = next((k for k in raw if "Time Series" in k), None)
            if series_key:
                rows = []
                for ts_str, candle in raw[series_key].items():
                    rows.append({
                        "timestamp": pd.Timestamp(ts_str, tz="UTC"),
                        "open":   safe_float(candle.get("1. open")),
                        "high":   safe_float(candle.get("2. high")),
                        "low":    safe_float(candle.get("3. low")),
                        "close":  safe_float(candle.get("5. adjusted close") or candle.get("4. close")),
                        "volume": safe_float(candle.get("6. volume") or candle.get("5. volume")),
                    })
                df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        else:
            series_key = next((k for k in raw if "Time Series" in k), None)
            rows = []
            if series_key:
                for ts_str, candle in raw[series_key].items():
                    rows.append({
                        "timestamp": pd.Timestamp(ts_str, tz="UTC"),
                        "open":   safe_float(candle.get("1. open")),
                        "high":   safe_float(candle.get("2. high")),
                        "low":    safe_float(candle.get("3. low")),
                        "close":  safe_float(candle.get("4. close")),
                        "volume": safe_float(candle.get("5. volume")),
                    })
            df = pd.DataFrame(rows).set_index("timestamp").sort_index() if rows else pd.DataFrame()

        if not df.empty and limit:
            df = df.tail(limit)

        if not df.empty and not validate_ohlcv(df):
            log.warning(f"AV OHLCV validation failed for {symbol}")

        log.debug(f"AV: {len(df)} candles for {symbol} @ {timeframe}")
        return df

    except Exception as e:
        log.warning(f"AV OHLCV fetch failed for {symbol}: {e}")
        raise


def fetch_company_overview(symbol: str) -> dict:
    """Fetch fundamental overview from Alpha Vantage."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = _session()
        return session.get("query", params=_params({
            "function": "OVERVIEW", "symbol": symbol
        })) or {}
    except Exception as e:
        log.warning(f"AV overview failed for {symbol}: {e}")
        return {}


def fetch_earnings(symbol: str) -> dict:
    """Fetch quarterly and annual earnings."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = _session()
        return session.get("query", params=_params({
            "function": "EARNINGS", "symbol": symbol
        })) or {}
    except Exception as e:
        log.warning(f"AV earnings failed for {symbol}: {e}")
        return {}
