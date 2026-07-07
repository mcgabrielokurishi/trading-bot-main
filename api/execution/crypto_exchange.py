"""
execution/crypto_exchange.py

Crypto order execution via Binance (spot and futures).
Wraps the binance_client with execution-specific logic.
"""

from typing import Optional
from config import EXECUTION, TRADING_MODE
from utils.helpers import utc_now
from utils.logger import get_logger

log = get_logger("crypto_exchange")


def place_crypto_order(
    symbol: str,
    side: str,
    units: float,
    order_type: str = "market",
    price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    use_futures: bool = False,
) -> dict:
    """
    Place a crypto order on Binance.

    For limit orders, applies a slight slippage offset to improve fill rate.
    """
    from data.crypto.binance_client import place_order, fetch_ticker

    # For limit orders, price needed
    if order_type == "limit" and price is None:
        ticker = fetch_ticker(symbol)
        slippage = EXECUTION["limit_slippage_pct"]
        if side == "buy":
            price = ticker.get("ask", 0) * (1 + slippage)
        else:
            price = ticker.get("bid", 0) * (1 - slippage)

    params = {}
    if stop_loss and order_type == "market":
        # Use OCO orders for market orders with stop
        params["stopLossPrice"] = str(stop_loss)
    if take_profit and order_type == "market":
        params["takeProfitPrice"] = str(take_profit)

    order = place_order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        amount=units,
        price=price,
        params=params,
    )
    return order
