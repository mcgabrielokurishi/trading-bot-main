"""
data/crypto/binance_client.py

Binance REST and WebSocket client for OHLCV, order book, and trade data.
Uses ccxt library for unified API access with Binance-specific extensions.
"""

import time
import ccxt
import pandas as pd
from typing import Optional
from config import (
    BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET,
    LOOKBACK_BARS,
)
from utils.helpers import ohlcv_to_df, validate_ohlcv, retry
from utils.api_utils import generate_mock_ohlcv
from utils.logger import get_logger

log = get_logger("binance_client")

# Binance timeframe mapping
TIMEFRAME_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h",
    "12h": "12h", "1d": "1d", "3d": "3d", "1w": "1w", "1M": "1M",
}


def _create_exchange(use_futures: bool = False) -> ccxt.Exchange:
    """Create and configure a Binance ccxt exchange instance."""
    exchange_class = ccxt.binanceusdm if use_futures else ccxt.binance
    exchange = exchange_class({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET_KEY,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future" if use_futures else "spot",
            "adjustForTimeDifference": True,
        },
    })
    if BINANCE_TESTNET:
        exchange.set_sandbox_mode(True)
    return exchange


_spot_exchange: Optional[ccxt.Exchange] = None
_futures_exchange: Optional[ccxt.Exchange] = None


def get_spot_exchange() -> ccxt.Exchange:
    global _spot_exchange
    if _spot_exchange is None:
        _spot_exchange = _create_exchange(use_futures=False)
    return _spot_exchange


def get_futures_exchange() -> ccxt.Exchange:
    global _futures_exchange
    if _futures_exchange is None:
        _futures_exchange = _create_exchange(use_futures=True)
    return _futures_exchange


# ─────────────────────────────────────────────────────────────────────────────
# OHLCV
# ─────────────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=1.0, backoff=2.0)
def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = LOOKBACK_BARS,
    since: Optional[int] = None,
    use_futures: bool = False,
) -> pd.DataFrame:
    """
    Fetch OHLCV candlestick data from Binance.

    Args:
        symbol: Trading pair e.g. 'BTC/USDT'
        timeframe: Candle interval e.g. '1h'
        limit: Number of candles to fetch
        since: Start timestamp in ms (optional)
        use_futures: Use USDT-margined futures market

    Returns:
        DataFrame with columns [open, high, low, close, volume]
    """
    if not BINANCE_API_KEY:
        log.debug(f"No Binance API key; returning mock OHLCV for {symbol}")
        raw = generate_mock_ohlcv(symbol, n_bars=limit, timeframe=timeframe)
        rows = [[r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in raw]
        return ohlcv_to_df(rows)

    try:
        exchange = get_futures_exchange() if use_futures else get_spot_exchange()
        tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        raw = exchange.fetch_ohlcv(symbol, tf, since=since, limit=limit)
        df = ohlcv_to_df(raw)
        if not validate_ohlcv(df):
            raise ValueError(f"Invalid OHLCV data for {symbol}")
        log.debug(f"Fetched {len(df)} {timeframe} candles for {symbol}")
        return df
    except ccxt.NetworkError as e:
        log.warning(f"Network error fetching {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        log.error(f"Exchange error fetching {symbol}: {e}")
        raise


def fetch_ohlcv_multi_timeframe(
    symbol: str,
    timeframes: list[str],
    limit: int = LOOKBACK_BARS,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for multiple timeframes at once."""
    result = {}
    for tf in timeframes:
        try:
            result[tf] = fetch_ohlcv(symbol, tf, limit)
        except Exception as e:
            log.warning(f"Failed to fetch {symbol} {tf}: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TICKER / ORDER BOOK
# ─────────────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=0.5)
def fetch_ticker(symbol: str) -> dict:
    """Fetch current ticker data (bid, ask, last, volume)."""
    if not BINANCE_API_KEY:
        return {"symbol": symbol, "last": 0.0, "bid": 0.0, "ask": 0.0, "volume": 0.0}
    try:
        exchange = get_spot_exchange()
        ticker = exchange.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "last": float(ticker.get("last") or 0),
            "bid": float(ticker.get("bid") or 0),
            "ask": float(ticker.get("ask") or 0),
            "volume": float(ticker.get("baseVolume") or 0),
            "quote_volume": float(ticker.get("quoteVolume") or 0),
            "change_pct": float(ticker.get("percentage") or 0),
            "high_24h": float(ticker.get("high") or 0),
            "low_24h": float(ticker.get("low") or 0),
            "timestamp": ticker.get("timestamp"),
        }
    except Exception as e:
        log.warning(f"Ticker fetch failed for {symbol}: {e}")
        return {"symbol": symbol, "last": 0.0}


@retry(max_attempts=3, delay=0.5)
def fetch_order_book(symbol: str, depth: int = 20) -> dict:
    """Fetch order book snapshot."""
    if not BINANCE_API_KEY:
        return {"bids": [], "asks": []}
    try:
        exchange = get_spot_exchange()
        book = exchange.fetch_order_book(symbol, depth)
        return {
            "bids": book.get("bids", []),
            "asks": book.get("asks", []),
            "timestamp": book.get("timestamp"),
        }
    except Exception as e:
        log.warning(f"Order book fetch failed for {symbol}: {e}")
        return {"bids": [], "asks": []}


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT
# ─────────────────────────────────────────────────────────────────────────────

def fetch_balance() -> dict:
    """Fetch account balance for all assets."""
    if not BINANCE_API_KEY:
        return {"USDT": {"free": 100_000.0, "used": 0.0, "total": 100_000.0}}
    try:
        exchange = get_spot_exchange()
        balance = exchange.fetch_balance()
        return {
            asset: {
                "free": float(info.get("free", 0)),
                "used": float(info.get("used", 0)),
                "total": float(info.get("total", 0)),
            }
            for asset, info in balance.get("total", {}).items()
            if float(info) > 0 if isinstance(info, (int, float)) else float(info.get("total", 0)) > 0
        }
    except Exception as e:
        log.error(f"Balance fetch failed: {e}")
        return {}


def fetch_open_orders(symbol: Optional[str] = None) -> list[dict]:
    """Fetch all open orders, optionally filtered by symbol."""
    if not BINANCE_API_KEY:
        return []
    try:
        exchange = get_spot_exchange()
        orders = exchange.fetch_open_orders(symbol)
        return orders
    except Exception as e:
        log.warning(f"Open orders fetch failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ORDER EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def place_order(
    symbol: str,
    side: str,
    order_type: str,
    amount: float,
    price: Optional[float] = None,
    params: Optional[dict] = None,
) -> dict:
    """
    Place an order on Binance.

    Args:
        symbol: Trading pair
        side: 'buy' or 'sell'
        order_type: 'market', 'limit', 'stop', 'stop_market'
        amount: Order quantity in base asset
        price: Limit price (required for limit orders)
        params: Additional exchange-specific parameters

    Returns:
        Order dict from ccxt
    """
    if not BINANCE_API_KEY:
        log.info(f"[PAPER] {side.upper()} {amount:.6f} {symbol} @ {price}")
        return {
            "id": f"paper_{int(time.time())}",
            "symbol": symbol, "side": side, "type": order_type,
            "amount": amount, "price": price, "status": "closed",
            "filled": amount, "average": price,
        }

    try:
        exchange = get_spot_exchange()
        params = params or {}
        order = exchange.create_order(symbol, order_type, side, amount, price, params)
        log.info(
            f"Order placed: {side.upper()} {amount:.6f} {symbol} "
            f"@ {price} [{order.get('id')}]"
        )
        return order
    except ccxt.InsufficientFunds as e:
        log.error(f"Insufficient funds for {side} {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        log.error(f"Order placement failed for {symbol}: {e}")
        raise


def cancel_order(order_id: str, symbol: str) -> dict:
    """Cancel an open order."""
    if not BINANCE_API_KEY:
        return {"id": order_id, "status": "canceled"}
    try:
        exchange = get_spot_exchange()
        return exchange.cancel_order(order_id, symbol)
    except Exception as e:
        log.error(f"Cancel order {order_id} failed: {e}")
        raise


def fetch_order_status(order_id: str, symbol: str) -> dict:
    """Fetch the current status of an order."""
    if not BINANCE_API_KEY:
        return {"id": order_id, "status": "closed"}
    try:
        exchange = get_spot_exchange()
        return exchange.fetch_order(order_id, symbol)
    except Exception as e:
        log.warning(f"Order status fetch failed for {order_id}: {e}")
        return {}
