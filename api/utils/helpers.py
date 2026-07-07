"""
General-purpose helper functions used across the bot.
"""

import time
import math
import hashlib
import functools
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, TypeVar, Optional
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger("helpers")
F = TypeVar("F", bound=Callable[..., Any])



# TIME UTILITIES


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def ts_to_dt(ts: int | float, unit: str = "ms") -> datetime:
    """Convert Unix timestamp to UTC datetime."""
    if unit == "ms":
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def dt_to_ts(dt: datetime, unit: str = "ms") -> int:
    """Convert datetime to Unix timestamp."""
    ts = dt.timestamp()
    return int(ts * 1000) if unit == "ms" else int(ts)


def timeframe_to_seconds(tf: str) -> int:
    """Convert timeframe string to seconds. E.g., '1h' -> 3600."""
    mapping = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
        "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800,
    }
    tf = tf.lower()
    if tf not in mapping:
        raise ValueError(f"Unknown timeframe: {tf}")
    return mapping[tf]


def get_date_range(
    start: str, end: str | None = None
) -> tuple[datetime, datetime]:
    """Parse date strings into UTC datetimes."""
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = (
        datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
        if end
        else utc_now()
    )
    return start_dt, end_dt



# MATH / STATISTICS


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that returns default instead of ZeroDivisionError."""
    if denominator == 0 or math.isnan(denominator) or math.isnan(numerator):
        return default
    return numerator / denominator


def normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize value to [0, 1] range."""
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def normalize_score(value: float, center: float = 0.0) -> float:
    """Normalize score to [-1, +1] using tanh squashing."""
    return float(np.tanh(value - center))


def ewma(values: list[float], alpha: float) -> list[float]:
    """Exponentially weighted moving average."""
    result = []
    ema = values[0] if values else 0.0
    for v in values:
        ema = alpha * v + (1 - alpha) * ema
        result.append(ema)
    return result


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score."""
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std.replace(0, np.nan)


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Calculate CAGR from a returns series."""
    if len(returns) == 0:
        return 0.0
    cumulative = (1 + returns).prod()
    n_years = len(returns) / periods_per_year
    if n_years <= 0:
        return 0.0
    return float(cumulative ** (1 / n_years) - 1)


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04,
    periods_per_year: int = 252,
) -> float:
    """Calculate annualized Sharpe ratio."""
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float((excess.mean() / excess.std()) * math.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04,
    periods_per_year: int = 252,
) -> float:
    """Calculate annualized Sortino ratio (downside deviation)."""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    downside = excess[excess < 0].std()
    if downside == 0:
        return 0.0
    return float((excess.mean() / downside) * math.sqrt(periods_per_year))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Calculate maximum drawdown as a positive fraction (e.g., 0.25 = 25%)."""
    if len(equity_curve) == 0:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(abs(drawdown.min()))


def calmar_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """CAGR / MaxDrawdown."""
    equity = (1 + returns).cumprod()
    cagr = annualized_return(returns, periods_per_year)
    mdd = max_drawdown(equity)
    return safe_divide(cagr, mdd)



# DECORATORS


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Retry decorator with exponential backoff."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        log.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    log.warning(
                        f"{func.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    wait *= backoff
        return wrapper  # type: ignore
    return decorator


def timed(func: F) -> F:
    """Log execution time of a function."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        log.debug(f"{func.__name__} completed in {elapsed:.3f}s")
        return result
    return wrapper  # type: ignore


def cache_result(ttl_seconds: int = 300) -> Callable:
    """Simple in-memory TTL cache for function results."""
    _cache: dict[str, tuple[Any, float]] = {}

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = hashlib.md5(
                f"{func.__name__}{args}{kwargs}".encode()
            ).hexdigest()
            now = time.time()
            if key in _cache:
                value, ts = _cache[key]
                if now - ts < ttl_seconds:
                    return value
            result = func(*args, **kwargs)
            _cache[key] = (result, now)
            return result
        return wrapper  # type: ignore
    return decorator



# DATA HELPERS


def ohlcv_to_df(data: list[list], columns: list[str] | None = None) -> pd.DataFrame:
    """Convert raw OHLCV list to a clean DataFrame."""
    cols = columns or ["timestamp", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(data, columns=cols)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    df.dropna(subset=["close"], inplace=True)
    return df


def validate_ohlcv(df: pd.DataFrame) -> bool:
    """Check that DataFrame has required OHLCV columns and reasonable values."""
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return False
    if df.empty or len(df) < 10:
        return False
    if (df["high"] < df["low"]).any():
        return False
    if (df["close"] <= 0).any():
        return False
    return True


def symbol_to_binance(symbol: str) -> str:
    """Convert 'BTC/USDT' -> 'BTCUSDT' for Binance REST calls."""
    return symbol.replace("/", "")


def symbol_to_yfinance(symbol: str) -> str:
    """Convert 'BTC/USDT' -> 'BTC-USD' for yfinance."""
    return symbol.replace("/USDT", "-USD").replace("/USD", "-USD")


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


def weighted_average(values: list[float], weights: list[float]) -> float:
    """Compute weighted average, ignoring NaN values."""
    total_w = 0.0
    total_v = 0.0
    for v, w in zip(values, weights):
        if not math.isnan(v) and w > 0:
            total_v += v * w
            total_w += w
    return safe_divide(total_v, total_w)


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten a nested dict."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: list, size: int) -> list[list]:
    """Split list into chunks of given size."""
    return [lst[i: i + size] for i in range(0, len(lst), size)]
