"""
execution/forex_broker.py

Forex order execution via OANDA v20 API.
Handles market orders with bracket stops/TPs for all major forex pairs.
"""

import time
from typing import Optional
from config import OANDA_ACCOUNT_ID, TRADING_MODE
from utils.helpers import utc_now, retry
from utils.logger import get_logger

log = get_logger("forex_broker")


@retry(max_attempts=3, delay=1.0, backoff=2.0)
def place_forex_order(
    instrument: str,
    side: str,
    units: int,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    client_id: Optional[str] = None,
) -> dict:
    """
    Place a forex market order on OANDA.

    Args:
        instrument: Pair in OANDA format e.g. 'EUR_USD'
        side: 'buy' or 'sell'
        units: Number of units (positive=long, negative=short)
        stop_loss: Stop loss price level
        take_profit: Take profit price level
        client_id: Optional client-assigned order ID

    Returns:
        Order response dict
    """
    signed_units = abs(units) if side == "buy" else -abs(units)

    if TRADING_MODE == "paper":
        log.info(f"[PAPER FOREX] {side.upper()} {abs(units):,} {instrument}")
        return {
            "id": f"oanda_paper_{int(time.time())}",
            "instrument": instrument,
            "side": side,
            "units": signed_units,
            "status": "filled",
            "type": "MARKET_ORDER",
            "timestamp": utc_now().isoformat(),
        }

    try:
        from data.forex.oanda_client import place_market_order
        resp = place_market_order(
            instrument=instrument,
            units=signed_units,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            client_id=client_id,
        )
        log.info(f"OANDA order placed: {signed_units:+,} {instrument}")
        return resp
    except Exception as e:
        log.error(f"Forex order failed for {instrument}: {e}")
        raise


def close_forex_position(instrument: str, trade_id: str) -> dict:
    """Close an open OANDA forex position by trade ID."""
    if TRADING_MODE == "paper":
        return {"id": trade_id, "state": "CLOSED"}
    try:
        from data.forex.oanda_client import close_trade
        return close_trade(trade_id)
    except Exception as e:
        log.error(f"Close forex trade {trade_id} failed: {e}")
        raise


def fetch_forex_positions() -> list[dict]:
    """Fetch all open OANDA forex positions."""
    try:
        from data.forex.oanda_client import fetch_open_trades
        trades = fetch_open_trades()
        return [
            {
                "trade_id": t.get("id"),
                "instrument": t.get("instrument"),
                "units": float(t.get("currentUnits", 0)),
                "entry_price": float(t.get("price", 0)),
                "unrealized_pl": float(t.get("unrealizedPL", 0)),
                "side": "buy" if float(t.get("currentUnits", 0)) > 0 else "sell",
            }
            for t in trades
        ]
    except Exception as e:
        log.warning(f"Forex positions fetch failed: {e}")
        return []


def calculate_forex_units(
    instrument: str,
    position_value_usd: float,
    current_price: float,
    leverage: float = 30.0,
) -> int:
    """
    Calculate OANDA units from a desired USD position value.

    Args:
        instrument: Forex pair e.g. 'EUR_USD'
        position_value_usd: Desired position size in USD
        current_price: Current exchange rate
        leverage: Account leverage (default 30:1 for retail)

    Returns:
        Integer units for OANDA
    """
    # For EUR_USD: units = position_value / price
    # For USD_JPY: units = position_value (denominated in USD)
    base, quote = instrument.split("_")
    if base == "USD":
        units = int(position_value_usd)
    else:
        units = int(position_value_usd / current_price)
    return max(1, units)
