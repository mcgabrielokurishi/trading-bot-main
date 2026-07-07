"""
data/stocks/yfinance_client.py

Yahoo Finance data client for stocks, ETFs, indices, and commodity futures.
yfinance is free, no API key required, but has rate limits.
"""

import time
import pandas as pd
import yfinance as yf
from typing import Optional
from utils.helpers import validate_ohlcv, retry
from utils.api_utils import generate_mock_ohlcv
from utils.logger import get_logger

log = get_logger("yfinance_client")


def _to_yf_period(timeframe: str) -> tuple[str, str]:
    """Map bot timeframe string to yfinance (interval, period) pair."""
    mapping = {
        "1m":  ("1m",  "7d"),
        "5m":  ("5m",  "60d"),
        "15m": ("15m", "60d"),
        "30m": ("30m", "60d"),
        "1h":  ("60m", "730d"),
        "4h":  ("1h",  "730d"),   # yf max for intraday
        "1d":  ("1d",  "5y"),
        "1w":  ("1wk", "10y"),
        "1M":  ("1mo", "20y"),
    }
    return mapping.get(timeframe, ("1d", "2y"))


@retry(max_attempts=3, delay=2.0, backoff=2.0, exceptions=(Exception,))
def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 500,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV data from Yahoo Finance.

    Args:
        symbol: Ticker symbol (e.g. 'AAPL', 'GC=F', 'BTC-USD')
        timeframe: Candle interval ('1d', '1h', '15m', etc.)
        limit: Max number of bars (approximate)
        start: Start date string 'YYYY-MM-DD'
        end: End date string 'YYYY-MM-DD'

    Returns:
        DataFrame with [open, high, low, close, volume] columns
    """
    try:
        interval, period = _to_yf_period(timeframe)
        ticker = yf.Ticker(symbol)

        if start:
            hist = ticker.history(interval=interval, start=start, end=end)
        else:
            hist = ticker.history(interval=interval, period=period)

        if hist.empty:
            log.warning(f"yfinance returned empty data for {symbol}")
            return pd.DataFrame()

        df = hist.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })[["open", "high", "low", "close", "volume"]]

        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = "timestamp"

        # Apply limit from tail
        if limit and len(df) > limit:
            df = df.tail(limit)

        if not validate_ohlcv(df):
            log.warning(f"OHLCV validation failed for {symbol}")
            return pd.DataFrame()

        log.debug(f"yfinance: {len(df)} candles for {symbol} @ {timeframe}")
        return df

    except Exception as e:
        log.warning(f"yfinance fetch failed for {symbol} @ {timeframe}: {e}")
        raise


def fetch_ohlcv_multi_timeframe(
    symbol: str,
    timeframes: list[str],
    limit: int = 500,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for multiple timeframes."""
    result = {}
    for tf in timeframes:
        try:
            result[tf] = fetch_ohlcv(symbol, tf, limit)
        except Exception as e:
            log.warning(f"yfinance multi-tf failed for {symbol} @ {tf}: {e}")
    return result


def fetch_ticker_info(symbol: str) -> dict:
    """Fetch complete ticker metadata and fundamental info."""
    try:
        ticker = yf.Ticker(symbol)
        return ticker.info or {}
    except Exception as e:
        log.warning(f"yfinance info failed for {symbol}: {e}")
        return {}


def fetch_financials(symbol: str) -> dict:
    """Fetch income statement, balance sheet, and cash flow."""
    try:
        ticker = yf.Ticker(symbol)
        return {
            "income_statement": ticker.financials,
            "balance_sheet": ticker.balance_sheet,
            "cash_flow": ticker.cashflow,
            "quarterly_income": ticker.quarterly_financials,
            "quarterly_balance": ticker.quarterly_balance_sheet,
        }
    except Exception as e:
        log.warning(f"yfinance financials failed for {symbol}: {e}")
        return {}


def fetch_options_chain(symbol: str) -> dict:
    """Fetch full options chain for the nearest expiry."""
    try:
        ticker = yf.Ticker(symbol)
        dates = ticker.options
        if not dates:
            return {}
        chain = ticker.option_chain(dates[0])
        return {
            "expiry": dates[0],
            "calls": chain.calls,
            "puts": chain.puts,
            "all_expiries": dates,
        }
    except Exception as e:
        log.warning(f"yfinance options failed for {symbol}: {e}")
        return {}
