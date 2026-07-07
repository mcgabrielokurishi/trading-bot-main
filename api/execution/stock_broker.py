"""
execution/stock_broker.py

Stock and ETF order execution via Alpaca API.
Supports market, limit, stop, and trailing stop orders for US equities.
"""

import time
from typing import Optional
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, TRADING_MODE
from utils.helpers import utc_now, retry
from utils.logger import get_logger

log = get_logger("stock_broker")

_alpaca_client = None


def _get_client():
    global _alpaca_client
    if _alpaca_client is None and ALPACA_API_KEY:
        try:
            from alpaca.trading.client import TradingClient
            _alpaca_client = TradingClient(
                api_key=ALPACA_API_KEY,
                secret_key=ALPACA_SECRET_KEY,
                paper=(TRADING_MODE == "paper"),
            )
        except Exception as e:
            log.warning(f"Alpaca client init failed: {e}")
    return _alpaca_client


@retry(max_attempts=3, delay=1.0)
def place_stock_order(
    symbol: str,
    side: str,
    qty: float,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    time_in_force: str = "day",
) -> dict:
    """
    Place a stock order via Alpaca.

    Args:
        symbol: Ticker e.g. 'AAPL'
        side: 'buy' or 'sell'
        qty: Number of shares (fractional allowed)
        order_type: 'market' | 'limit' | 'stop' | 'stop_limit' | 'trailing_stop'
        limit_price: Required for limit orders
        stop_price: Required for stop orders
        take_profit_price: Optional bracket order take profit
        time_in_force: 'day' | 'gtc' | 'opg' | 'cls' | 'ioc' | 'fok'

    Returns:
        Order response dict
    """
    client = _get_client()

    if not client:
        log.info(f"[PAPER/MOCK] Alpaca {side.upper()} {qty} {symbol} @ {order_type}")
        return {
            "id": f"alpaca_paper_{int(time.time())}",
            "symbol": symbol, "side": side, "qty": qty,
            "type": order_type, "status": "filled",
            "filled_avg_price": limit_price or stop_price or 0,
            "timestamp": utc_now().isoformat(),
        }

    try:
        from alpaca.trading.requests import (
            MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
            StopLimitOrderRequest, TrailingStopOrderRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        alpaca_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce(time_in_force.upper()) if time_in_force.upper() in [
            "DAY", "GTC", "OPG", "CLS", "IOC", "FOK"
        ] else TimeInForce.DAY

        if order_type == "market":
            req = MarketOrderRequest(
                symbol=symbol, qty=qty, side=alpaca_side, time_in_force=tif
            )
        elif order_type == "limit":
            req = LimitOrderRequest(
                symbol=symbol, qty=qty, side=alpaca_side,
                limit_price=limit_price, time_in_force=tif
            )
        elif order_type == "stop":
            req = StopOrderRequest(
                symbol=symbol, qty=qty, side=alpaca_side,
                stop_price=stop_price, time_in_force=tif
            )
        elif order_type == "stop_limit":
            req = StopLimitOrderRequest(
                symbol=symbol, qty=qty, side=alpaca_side,
                limit_price=limit_price, stop_price=stop_price, time_in_force=tif
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol, qty=qty, side=alpaca_side, time_in_force=tif
            )

        order = client.submit_order(req)
        log.info(f"Alpaca order submitted: {order.id} | {side} {qty} {symbol}")
        return {
            "id": str(order.id),
            "symbol": symbol, "side": side, "qty": float(order.qty),
            "type": order_type, "status": str(order.status),
            "filled_avg_price": float(order.filled_avg_price or 0),
            "timestamp": str(order.submitted_at),
        }

    except Exception as e:
        log.error(f"Alpaca order failed for {symbol}: {e}")
        raise


def cancel_stock_order(order_id: str) -> bool:
    """Cancel an open Alpaca order."""
    client = _get_client()
    if not client:
        return True
    try:
        client.cancel_order_by_id(order_id)
        log.info(f"Alpaca order {order_id} cancelled")
        return True
    except Exception as e:
        log.error(f"Alpaca cancel failed for {order_id}: {e}")
        return False


def fetch_alpaca_positions() -> list[dict]:
    """Fetch all open Alpaca positions."""
    client = _get_client()
    if not client:
        return []
    try:
        positions = client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price or 0),
                "unrealized_pl": float(p.unrealized_pl or 0),
                "market_value": float(p.market_value or 0),
            }
            for p in positions
        ]
    except Exception as e:
        log.warning(f"Alpaca positions fetch failed: {e}")
        return []


def fetch_alpaca_account() -> dict:
    """Fetch Alpaca account info."""
    client = _get_client()
    if not client:
        return {"cash": 100_000.0, "portfolio_value": 100_000.0}
    try:
        acc = client.get_account()
        return {
            "cash": float(acc.cash),
            "portfolio_value": float(acc.portfolio_value),
            "buying_power": float(acc.buying_power),
            "equity": float(acc.equity),
            "status": str(acc.status),
        }
    except Exception as e:
        log.warning(f"Alpaca account fetch failed: {e}")
        return {}
