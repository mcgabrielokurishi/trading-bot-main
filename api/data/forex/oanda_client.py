"""
data/forex/oanda_client.py

OANDA v20 REST API client for forex price data, account management, and order execution.
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Optional
import oandapyV20
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades_api
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.pricing as pricing
from oandapyV20.exceptions import V20Error
from config import OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT, LOOKBACK_BARS
from utils.helpers import validate_ohlcv, ohlcv_to_df, retry
from utils.api_utils import generate_mock_ohlcv
from utils.logger import get_logger

log = get_logger("oanda_client")

OANDA_GRANULARITY = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D", "1w": "W", "1M": "M",
}

_client: Optional[oandapyV20.API] = None


def get_client() -> Optional[oandapyV20.API]:
    global _client
    if _client is None and OANDA_API_KEY:
        env = "live" if OANDA_ENVIRONMENT == "live" else "practice"
        _client = oandapyV20.API(access_token=OANDA_API_KEY, environment=env)
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# OHLCV
# ─────────────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=1.0, backoff=2.0)
def fetch_ohlcv(
    instrument: str,
    timeframe: str = "1h",
    count: int = LOOKBACK_BARS,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from OANDA.

    Args:
        instrument: Forex pair e.g. 'EUR_USD'
        timeframe: '1m', '15m', '1h', '4h', '1d'
        count: Number of candles
        from_time: ISO 8601 start datetime (optional)
        to_time: ISO 8601 end datetime (optional)

    Returns:
        OHLCV DataFrame
    """
    client = get_client()
    if not client:
        log.debug(f"No OANDA credentials; returning mock for {instrument}")
        raw = generate_mock_ohlcv(instrument, n_bars=count, base_price=1.10, timeframe=timeframe)
        rows = [[r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in raw]
        return ohlcv_to_df(rows)

    granularity = OANDA_GRANULARITY.get(timeframe, "H1")
    params: dict = {"granularity": granularity}

    if from_time and to_time:
        params["from"] = from_time
        params["to"] = to_time
    else:
        params["count"] = min(count, 5000)  # OANDA max per request

    try:
        req = instruments.InstrumentsCandles(instrument=instrument, params=params)
        resp = client.request(req)
        candles = resp.get("candles", [])

        rows = []
        for candle in candles:
            if not candle.get("complete", True):
                continue
            mid = candle.get("mid", {})
            rows.append([
                int(datetime.fromisoformat(
                    candle["time"].replace("Z", "+00:00")
                ).timestamp() * 1000),
                float(mid.get("o", 0)),
                float(mid.get("h", 0)),
                float(mid.get("l", 0)),
                float(mid.get("c", 0)),
                float(candle.get("volume", 0)),
            ])

        df = ohlcv_to_df(rows)
        if not validate_ohlcv(df):
            raise ValueError(f"Invalid OHLCV for {instrument}")

        log.debug(f"OANDA: {len(df)} {timeframe} candles for {instrument}")
        return df

    except V20Error as e:
        log.error(f"OANDA V20Error for {instrument}: {e}")
        raise
    except Exception as e:
        log.warning(f"OANDA OHLCV failed for {instrument}: {e}")
        raise


def fetch_ohlcv_multi_timeframe(
    instrument: str,
    timeframes: list[str],
    count: int = LOOKBACK_BARS,
) -> dict[str, pd.DataFrame]:
    result = {}
    for tf in timeframes:
        try:
            result[tf] = fetch_ohlcv(instrument, tf, count)
        except Exception as e:
            log.warning(f"OANDA multi-tf failed for {instrument} @ {tf}: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PRICING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_current_price(instrument: str) -> dict:
    """Fetch current bid/ask for a forex pair."""
    client = get_client()
    if not client:
        return {"instrument": instrument, "bid": 1.0, "ask": 1.0002}
    try:
        params = {"instruments": instrument}
        req = pricing.PricingInfo(accountID=OANDA_ACCOUNT_ID, params=params)
        resp = client.request(req)
        prices = resp.get("prices", [{}])[0]
        return {
            "instrument": instrument,
            "bid": float(prices.get("bids", [{}])[0].get("price", 0)),
            "ask": float(prices.get("asks", [{}])[0].get("price", 0)),
            "tradeable": prices.get("tradeable", False),
            "status": prices.get("status", "unknown"),
        }
    except Exception as e:
        log.warning(f"OANDA price fetch failed for {instrument}: {e}")
        return {"instrument": instrument, "bid": 0.0, "ask": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT
# ─────────────────────────────────────────────────────────────────────────────

def fetch_account_summary() -> dict:
    """Fetch OANDA account summary (balance, NAV, margin, P&L)."""
    client = get_client()
    if not client:
        return {"balance": 100_000.0, "NAV": 100_000.0, "currency": "USD"}
    try:
        req = accounts.AccountSummary(OANDA_ACCOUNT_ID)
        resp = client.request(req)
        acc = resp.get("account", {})
        return {
            "balance": float(acc.get("balance", 0)),
            "NAV": float(acc.get("NAV", 0)),
            "unrealized_pl": float(acc.get("unrealizedPL", 0)),
            "realized_pl": float(acc.get("pl", 0)),
            "margin_used": float(acc.get("marginUsed", 0)),
            "margin_available": float(acc.get("marginAvailable", 0)),
            "open_trade_count": int(acc.get("openTradeCount", 0)),
            "currency": acc.get("currency", "USD"),
        }
    except Exception as e:
        log.error(f"OANDA account summary failed: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# ORDER EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def place_market_order(
    instrument: str,
    units: int,
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    client_id: Optional[str] = None,
) -> dict:
    """
    Place a market order on OANDA.

    Args:
        instrument: Forex pair e.g. 'EUR_USD'
        units: Positive for buy, negative for sell
        stop_loss_price: Stop loss level
        take_profit_price: Take profit level
        client_id: Custom order reference

    Returns:
        Order response dict
    """
    client = get_client()
    if not client:
        log.info(f"[PAPER OANDA] {'BUY' if units > 0 else 'SELL'} {abs(units)} {instrument}")
        return {
            "id": f"paper_oanda_{int(datetime.now().timestamp())}",
            "instrument": instrument, "units": units,
            "status": "filled", "type": "MARKET_ORDER",
        }

    order_body: dict = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
    }

    if stop_loss_price:
        order_body["order"]["stopLossOnFill"] = {"price": f"{stop_loss_price:.5f}"}
    if take_profit_price:
        order_body["order"]["takeProfitOnFill"] = {"price": f"{take_profit_price:.5f}"}
    if client_id:
        order_body["order"]["clientExtensions"] = {"id": client_id}

    try:
        req = orders.OrderCreate(OANDA_ACCOUNT_ID, data=order_body)
        resp = client.request(req)
        log.info(f"OANDA order: {units} {instrument}")
        return resp
    except V20Error as e:
        log.error(f"OANDA order failed for {instrument}: {e}")
        raise


def close_trade(trade_id: str) -> dict:
    """Close an open OANDA trade."""
    client = get_client()
    if not client:
        return {"id": trade_id, "state": "CLOSED"}
    try:
        req = trades_api.TradeClose(OANDA_ACCOUNT_ID, tradeID=trade_id)
        return client.request(req)
    except V20Error as e:
        log.error(f"OANDA close trade {trade_id} failed: {e}")
        raise


def fetch_open_trades() -> list[dict]:
    """Fetch all open OANDA trades."""
    client = get_client()
    if not client:
        return []
    try:
        req = trades_api.TradesList(OANDA_ACCOUNT_ID, params={"state": "OPEN"})
        resp = client.request(req)
        return resp.get("trades", [])
    except Exception as e:
        log.warning(f"OANDA open trades fetch failed: {e}")
        return []
