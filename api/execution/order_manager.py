"""
execution/order_manager.py

Central order management system. Routes orders to the appropriate broker/exchange
based on market type, handles retries, and maintains trade logs.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from config import EXECUTION, TRADING_MODE
from utils.helpers import utc_now
from utils.logger import get_logger, log_trade
from risk.portfolio_risk import Position

log = get_logger("order_manager")


class OrderManager:
    """
    Routes and manages orders across all markets.

    Supports:
    - Crypto: Binance (spot/futures)
    - Stocks: Alpaca
    - Forex: OANDA
    - Commodities: Alpaca (futures ETFs) or paper
    """

    def __init__(self, portfolio_risk_manager=None) -> None:
        self._risk_manager = portfolio_risk_manager
        self._pending_orders: dict[str, dict] = {}
        self._order_history: list[dict] = []

    # ── Routing ─────────────────────────────────────────────────────────────

    def _detect_market(self, symbol: str) -> str:
        if "/" in symbol or symbol.endswith("USDT"):
            return "crypto"
        if "_" in symbol and len(symbol.split("_")) == 2:
            return "forex"
        if symbol.endswith("=F"):
            return "commodities"
        return "stocks"

    # ── Order Execution ──────────────────────────────────────────────────────

    def submit_order(
        self,
        symbol: str,
        side: str,
        units: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy: str = "balanced",
        signal_score: float = 0.0,
        reason: str = "",
        market_type: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Submit an order to the appropriate exchange/broker.

        Args:
            symbol: Asset symbol
            side: 'buy' or 'sell'
            units: Quantity to trade
            order_type: 'market' | 'limit' | 'stop'
            price: Limit price (required for limit orders)
            stop_loss: Stop loss price
            take_profit: Take profit price
            strategy: Strategy preset name
            signal_score: Signal score that triggered the trade
            reason: Human-readable reason for the trade
            market_type: Override auto-detected market type

        Returns:
            Order dict or None on failure
        """
        if units <= 0:
            log.warning(f"Invalid order size {units} for {symbol}")
            return None

        mtype = market_type or self._detect_market(symbol)
        order_id = str(uuid.uuid4())[:12]

        log.info(
            f"Submitting {order_type.upper()} {side.upper()} {units:.6f} {symbol} "
            f"@ {'market' if not price else price:.6f} | score={signal_score:.3f} | {reason}"
        )

        if TRADING_MODE == "paper":
            return self._paper_order(
                order_id, symbol, side, units, price, stop_loss,
                take_profit, strategy, signal_score, reason, mtype
            )

        # Live execution routing
        for attempt in range(EXECUTION["order_retry_attempts"]):
            try:
                order = self._route_order(
                    symbol, side, units, order_type, price,
                    stop_loss, take_profit, mtype
                )
                if order:
                    self._log_order(
                        order_id, symbol, side, units,
                        price or self._get_fill_price(order),
                        mtype, strategy, signal_score, reason,
                        stop_loss, take_profit, order.get("id", order_id)
                    )
                    return order
            except Exception as e:
                log.warning(f"Order attempt {attempt + 1} failed for {symbol}: {e}")
                if attempt < EXECUTION["order_retry_attempts"] - 1:
                    time.sleep(EXECUTION["order_retry_delay"])

        log.error(f"Order failed after {EXECUTION['order_retry_attempts']} attempts: {symbol}")
        return None

    def _route_order(
        self,
        symbol: str,
        side: str,
        units: float,
        order_type: str,
        price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        market_type: str,
    ) -> Optional[dict]:
        """Route order to appropriate exchange module."""
        if market_type == "crypto":
            from execution.crypto_exchange import place_crypto_order
            return place_crypto_order(symbol, side, units, order_type, price, stop_loss, take_profit)
        elif market_type == "stocks":
            from execution.stock_broker import place_stock_order
            return place_stock_order(symbol, side, units, order_type, price, stop_loss, take_profit)
        elif market_type == "forex":
            from execution.forex_broker import place_forex_order
            return place_forex_order(symbol, side, int(units * 1000), stop_loss, take_profit)
        else:
            # Commodities: use stock broker (ETFs/futures via Alpaca)
            from execution.stock_broker import place_stock_order
            return place_stock_order(symbol, side, units, order_type, price, stop_loss, take_profit)

    def _paper_order(
        self, order_id, symbol, side, units, price, stop_loss,
        take_profit, strategy, signal_score, reason, mtype
    ) -> dict:
        """Simulate order execution in paper trading mode."""
        fill_price = price or 0.0  # caller should provide last price

        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "units": units,
            "price": fill_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "filled",
            "filled": units,
            "average": fill_price,
            "market_type": mtype,
            "strategy": strategy,
            "timestamp": utc_now().isoformat(),
        }

        self._log_order(
            order_id, symbol, side, units, fill_price, mtype,
            strategy, signal_score, reason, stop_loss, take_profit, order_id
        )
        self._order_history.append(order)
        return order

    def _log_order(
        self, order_id, symbol, side, units, price, mtype,
        strategy, signal_score, reason, stop_loss, take_profit, exchange_order_id
    ) -> None:
        """Log a completed order to the trade log."""
        value_usd = units * (price or 0)
        log_trade(
            timestamp=utc_now().isoformat(),
            asset=symbol,
            market=mtype,
            side=side,
            price=price or 0,
            size=units,
            value_usd=value_usd,
            reason=reason,
            signal_score=signal_score,
            strategy=strategy,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=exchange_order_id,
        )

    def _get_fill_price(self, order: dict) -> float:
        """Extract fill price from an order response."""
        return float(
            order.get("average") or order.get("price") or
            order.get("avgPrice") or 0.0
        )

    def cancel_order(self, order_id: str, symbol: str, market_type: str) -> bool:
        """Cancel an open order."""
        if TRADING_MODE == "paper":
            log.info(f"[PAPER] Cancelled order {order_id}")
            return True
        try:
            if market_type == "crypto":
                from data.crypto.binance_client import cancel_order
                cancel_order(order_id, symbol)
            elif market_type in ("stocks", "commodities"):
                from execution.stock_broker import cancel_stock_order
                cancel_stock_order(order_id)
            elif market_type == "forex":
                pass  # OANDA uses trade close, not order cancel
            return True
        except Exception as e:
            log.error(f"Cancel order {order_id} failed: {e}")
            return False

    def get_order_history(self) -> list[dict]:
        return list(self._order_history)
