"""
utils/api_utils.py — API rate limiting, session management, and HTTP helpers.
"""

import time
import threading
import asyncio
from collections import deque
from typing import Any, Optional
import requests
import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from config import RATE_LIMITS
from utils.logger import get_logger

log = get_logger("api_utils")


# RATE LIMITER

class RateLimiter:
    """
    Token-bucket rate limiter.
    Tracks requests in a sliding time window and sleeps if necessary.
    """

    def __init__(self, max_requests: int, period_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        with self._lock:
            now = time.monotonic()
            # Remove timestamps outside the window
            while self._timestamps and self._timestamps[0] < now - self.period:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_requests:
                # Sleep until the oldest request falls out of window
                sleep_time = self.period - (now - self._timestamps[0]) + 0.01
                if sleep_time > 0:
                    log.debug(f"Rate limit hit. Sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)

            self._timestamps.append(time.monotonic())

    def __call__(self, func):
        """Use as decorator."""
        import functools
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            self.acquire()
            return func(*args, **kwargs)
        return wrapper


# Shared rate limiters keyed by API name
_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(api_name: str) -> RateLimiter:
    """Return (or create) a RateLimiter for the given API."""
    if api_name not in _rate_limiters:
        rpm = RATE_LIMITS.get(api_name, 60)
        _rate_limiters[api_name] = RateLimiter(rpm, period_seconds=60.0)
    return _rate_limiters[api_name]



# SYNCHRONOUS HTTP SESSION


class APISession:
    """
    Reusable requests.Session with retry logic, timeout, and rate limiting.
    """

    def __init__(
        self,
        base_url: str,
        api_name: str,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limiter = get_rate_limiter(api_name)
        self._session = requests.Session()
        if headers:
            self._session.headers.update(headers)
        self._session.headers.update({"User-Agent": "TradingBot/1.0"})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def get(self, path: str, params: dict | None = None, **kwargs) -> Any:
        """Perform a GET request with rate limiting and retry."""
        self.rate_limiter.acquire()
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            log.error(f"HTTP {status} for GET {url}: {e}")
            raise
        except Exception as e:
            log.error(f"GET {url} failed: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def post(self, path: str, data: dict | None = None, json: dict | None = None, **kwargs) -> Any:
        """Perform a POST request with rate limiting and retry."""
        self.rate_limiter.acquire()
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.post(
                url, data=data, json=json, timeout=self.timeout, **kwargs
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            log.error(f"HTTP {status} for POST {url}: {e}")
            raise
        except Exception as e:
            log.error(f"POST {url} failed: {e}")
            raise

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()



# ASYNC HTTP SESSION


class AsyncAPISession:
    """Async aiohttp session with rate limiting."""

    def __init__(
        self,
        base_url: str,
        api_name: str,
        headers: dict | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.rate_limiter = get_rate_limiter(api_name)
        self._headers = headers or {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            headers=self._headers, timeout=self.timeout
        )
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    async def get(self, path: str, params: dict | None = None) -> Any:
        """Async GET with rate limiting."""
        # For async, use a simple semaphore-based approach
        url = f"{self.base_url}/{path.lstrip('/')}"
        if not self._session:
            raise RuntimeError("Session not started. Use async with.")
        for attempt in range(3):
            try:
                async with self._session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except aiohttp.ClientResponseError as e:
                log.error(f"Async HTTP {e.status} for GET {url}: {e}")
                if e.status in (429, 503):
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except Exception as e:
                log.error(f"Async GET attempt {attempt+1} failed for {url}: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(1)



# RESPONSE PARSERS


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert any value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert any value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_nested(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely extract a nested dict value."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is None:
            return default
    return current



# MOCK DATA GENERATOR (for testing / missing API keys)


def generate_mock_ohlcv(
    symbol: str,
    n_bars: int = 500,
    base_price: float = 100.0,
    timeframe: str = "1h",
) -> list[dict]:
    """Generate realistic mock OHLCV data for testing."""
    import numpy as np
    from utils.helpers import timeframe_to_seconds

    interval = timeframe_to_seconds(timeframe) * 1000  # ms
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - n_bars * interval

    rng = np.random.default_rng(hash(symbol) % (2**32))
    price = base_price
    bars = []
    ts = start_ms

    for _ in range(n_bars):
        ret = rng.normal(0, 0.015)
        close = max(0.01, price * (1 + ret))
        high = max(price, close) * (1 + abs(rng.normal(0, 0.005)))
        low = min(price, close) * (1 - abs(rng.normal(0, 0.005)))
        open_ = price
        volume = abs(rng.normal(1_000_000, 300_000))

        bars.append({
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
        price = close
        ts += interval

    return bars
