"""
risk/portfolio_risk.py

Portfolio-level risk management: exposure limits, drawdown monitoring,
correlation checks, daily loss limits, and risk scoring.
"""

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Optional
from config import RISK
from utils.helpers import safe_divide, clamp, max_drawdown, utc_now
from utils.logger import get_logger

log = get_logger("portfolio_risk")


# ─────────────────────────────────────────────────────────────────────────────
# POSITION TRACKING
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    market_type: str       # 'crypto' | 'stocks' | 'forex' | 'commodities'
    side: str              # 'buy' | 'sell'
    entry_price: float
    units: float
    stop_loss: float
    take_profit: Optional[float]
    entry_time: datetime = field(default_factory=utc_now)
    order_id: Optional[str] = None
    strategy: str = "balanced"

    @property
    def position_value(self) -> float:
        return self.units * self.entry_price

    @property
    def risk_amount(self) -> float:
        return self.units * abs(self.entry_price - self.stop_loss)

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "buy":
            return (current_price - self.entry_price) * self.units
        else:
            return (self.entry_price - current_price) * self.units

    def unrealized_pnl_pct(self, current_price: float) -> float:
        return safe_divide(self.unrealized_pnl(current_price), self.position_value)


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioRiskManager:
    """
    Tracks portfolio state and enforces risk rules.

    Key rules:
    - Max % of portfolio in a single position
    - Max total portfolio exposure
    - Max drawdown halt
    - Daily loss limit
    - Max correlated positions
    - Max open trades
    """

    def __init__(self, initial_capital: float) -> None:
        self.initial_capital = initial_capital
        self.peak_value = initial_capital
        self._positions: dict[str, Position] = {}  # key: symbol
        self._daily_pnl: dict[date, float] = {}
        self._equity_history: list[tuple[datetime, float]] = [
            (utc_now(), initial_capital)
        ]
        self._closed_trades: list[dict] = []
        self._trading_halted = False
        self._halt_reason = ""

    # ── State Properties ────────────────────────────────────────────────────

    @property
    def open_positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    def portfolio_value(self, current_prices: dict[str, float]) -> float:
        """Compute total portfolio value including unrealized P&L."""
        cash = self.initial_capital
        for sym, pos in self._positions.items():
            price = current_prices.get(sym, pos.entry_price)
            cash += pos.unrealized_pnl(price)
        return cash

    def total_exposure(self, portfolio_val: float) -> float:
        """Total position value as fraction of portfolio."""
        total = sum(p.position_value for p in self._positions.values())
        return safe_divide(total, portfolio_val)

    def current_drawdown(self, portfolio_val: float) -> float:
        """Current drawdown from peak as positive fraction."""
        self.peak_value = max(self.peak_value, portfolio_val)
        return safe_divide(self.peak_value - portfolio_val, self.peak_value)

    def daily_pnl(self, portfolio_val: float) -> float:
        """Today's P&L as fraction of portfolio."""
        today = utc_now().date()
        start_val = self._daily_pnl.get(today)
        if start_val is None:
            # First check today — record starting value
            self._daily_pnl[today] = portfolio_val
            return 0.0
        return safe_divide(portfolio_val - start_val, start_val)

    # ── Risk Checks ─────────────────────────────────────────────────────────

    def can_open_trade(
        self,
        symbol: str,
        position_value: float,
        portfolio_val: float,
        current_prices: dict[str, float],
    ) -> tuple[bool, str]:
        """
        Check whether a new trade is allowed under current risk rules.

        Returns:
            (allowed: bool, reason: str)
        """
        if self._trading_halted:
            return False, f"Trading halted: {self._halt_reason}"

        # Max open trades
        if self.open_position_count >= RISK["max_open_trades"]:
            return False, f"Max open trades reached ({RISK['max_open_trades']})"

        # Max position size
        pos_pct = safe_divide(position_value, portfolio_val)
        if pos_pct > RISK["max_position_pct"]:
            return False, (
                f"Position size {pos_pct:.1%} exceeds max {RISK['max_position_pct']:.1%}"
            )

        # Max portfolio exposure
        current_exposure = self.total_exposure(portfolio_val)
        new_exposure = current_exposure + pos_pct
        if new_exposure > RISK["max_portfolio_exposure"]:
            return False, (
                f"Adding this position would exceed max exposure "
                f"({new_exposure:.1%} > {RISK['max_portfolio_exposure']:.1%})"
            )

        # Max drawdown
        dd = self.current_drawdown(portfolio_val)
        if dd >= RISK["max_drawdown_pct"]:
            self._halt_trading(f"Max drawdown {dd:.1%} exceeded")
            return False, f"Max drawdown {dd:.1%} exceeded"

        # Daily loss limit
        daily_loss = self.daily_pnl(portfolio_val)
        if daily_loss <= -RISK["daily_loss_limit_pct"]:
            self._halt_trading(f"Daily loss limit {daily_loss:.1%} exceeded")
            return False, f"Daily loss limit exceeded ({daily_loss:.1%})"

        # Duplicate position check
        if symbol in self._positions:
            return False, f"Already have open position in {symbol}"

        return True, "OK"

    def check_correlation_limit(
        self,
        symbol: str,
        market_type: str,
        ohlcv_data: dict[str, pd.DataFrame],
    ) -> tuple[bool, str]:
        """
        Check if adding this position would create excessive correlation.

        Args:
            symbol: New asset symbol
            market_type: Market type of new asset
            ohlcv_data: Dict of {symbol: DataFrame} for correlation computation

        Returns:
            (allowed, reason)
        """
        max_correlated = RISK["max_correlated_positions"]
        threshold = RISK["correlation_threshold"]

        existing_symbols = list(self._positions.keys())
        if len(existing_symbols) < 2:
            return True, "OK"  # Not enough positions to check

        new_df = ohlcv_data.get(symbol)
        if new_df is None or new_df.empty:
            return True, "OK"  # Can't compute correlation; allow

        try:
            returns = {}
            returns[symbol] = new_df["close"].pct_change().dropna()

            correlated_count = 0
            for sym in existing_symbols:
                sym_df = ohlcv_data.get(sym)
                if sym_df is None or sym_df.empty:
                    continue
                sym_ret = sym_df["close"].pct_change().dropna()
                # Align on common index
                aligned = pd.concat([returns[symbol], sym_ret], axis=1, join="inner")
                if len(aligned) < 20:
                    continue
                corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                if abs(corr) > threshold:
                    correlated_count += 1

            if correlated_count >= max_correlated:
                return False, (
                    f"Too many correlated positions ({correlated_count} >= {max_correlated})"
                )
        except Exception as e:
            log.warning(f"Correlation check failed: {e}")

        return True, "OK"

    def check_stops(
        self, current_prices: dict[str, float]
    ) -> list[dict]:
        """
        Check all open positions against their stop loss levels.

        Returns:
            List of positions that have breached their stop loss
        """
        triggered = []
        for symbol, pos in self._positions.items():
            price = current_prices.get(symbol)
            if price is None:
                continue

            stop_triggered = False
            if pos.side == "buy" and price <= pos.stop_loss:
                stop_triggered = True
            elif pos.side == "sell" and price >= pos.stop_loss:
                stop_triggered = True

            if stop_triggered:
                log.warning(
                    f"Stop loss triggered: {symbol} {pos.side} "
                    f"price={price:.6f} stop={pos.stop_loss:.6f}"
                )
                triggered.append({
                    "symbol": symbol,
                    "position": pos,
                    "current_price": price,
                    "reason": "stop_loss",
                    "pnl": pos.unrealized_pnl(price),
                    "pnl_pct": pos.unrealized_pnl_pct(price),
                })
        return triggered

    def check_take_profits(
        self, current_prices: dict[str, float]
    ) -> list[dict]:
        """Check all open positions against take profit levels."""
        triggered = []
        for symbol, pos in self._positions.items():
            if pos.take_profit is None:
                continue
            price = current_prices.get(symbol)
            if price is None:
                continue

            tp_triggered = False
            if pos.side == "buy" and price >= pos.take_profit:
                tp_triggered = True
            elif pos.side == "sell" and price <= pos.take_profit:
                tp_triggered = True

            if tp_triggered:
                log.info(
                    f"Take profit triggered: {symbol} {pos.side} "
                    f"price={price:.6f} tp={pos.take_profit:.6f}"
                )
                triggered.append({
                    "symbol": symbol,
                    "position": pos,
                    "current_price": price,
                    "reason": "take_profit",
                    "pnl": pos.unrealized_pnl(price),
                    "pnl_pct": pos.unrealized_pnl_pct(price),
                })
        return triggered

    # ── Position Lifecycle ──────────────────────────────────────────────────

    def add_position(self, position: Position) -> None:
        """Record a newly opened position."""
        self._positions[position.symbol] = position
        log.info(
            f"Position opened: {position.side.upper()} {position.units:.6f} "
            f"{position.symbol} @ {position.entry_price:.6f}"
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        reason: str = "signal",
    ) -> Optional[dict]:
        """Record a closed position and compute P&L."""
        pos = self._positions.pop(symbol, None)
        if not pos:
            log.warning(f"No open position for {symbol}")
            return None

        pnl = pos.unrealized_pnl(close_price)
        pnl_pct = pos.unrealized_pnl_pct(close_price)
        hold_hours = (utc_now() - pos.entry_time).total_seconds() / 3600

        trade_record = {
            "symbol": symbol,
            "market_type": pos.market_type,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "close_price": close_price,
            "units": pos.units,
            "position_value": pos.position_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "hold_hours": hold_hours,
            "reason": reason,
            "entry_time": pos.entry_time.isoformat(),
            "close_time": utc_now().isoformat(),
            "strategy": pos.strategy,
        }

        self._closed_trades.append(trade_record)
        today = utc_now().date()
        self._daily_pnl[today] = self._daily_pnl.get(today, 0) + pnl

        log.info(
            f"Position closed: {symbol} {pos.side} | "
            f"P&L={pnl:+.2f} ({pnl_pct:+.2%}) | hold={hold_hours:.1f}h | reason={reason}"
        )
        return trade_record

    # ── Portfolio Analytics ─────────────────────────────────────────────────

    def get_portfolio_stats(self, current_prices: dict[str, float]) -> dict:
        """Compute current portfolio statistics."""
        portfolio_val = self.portfolio_value(current_prices)
        exposure = self.total_exposure(portfolio_val)
        drawdown = self.current_drawdown(portfolio_val)
        daily_pl = self.daily_pnl(portfolio_val)

        position_details = []
        for sym, pos in self._positions.items():
            price = current_prices.get(sym, pos.entry_price)
            position_details.append({
                "symbol": sym,
                "side": pos.side,
                "units": pos.units,
                "entry_price": pos.entry_price,
                "current_price": price,
                "pnl": pos.unrealized_pnl(price),
                "pnl_pct": pos.unrealized_pnl_pct(price),
                "pct_of_portfolio": safe_divide(pos.position_value, portfolio_val),
            })

        closed_pnls = [t["pnl"] for t in self._closed_trades]
        wins = [p for p in closed_pnls if p > 0]
        losses = [p for p in closed_pnls if p < 0]

        return {
            "portfolio_value": portfolio_val,
            "initial_capital": self.initial_capital,
            "total_return_pct": safe_divide(portfolio_val - self.initial_capital, self.initial_capital),
            "total_exposure": exposure,
            "current_drawdown": drawdown,
            "peak_value": self.peak_value,
            "daily_pnl": daily_pl,
            "open_positions": len(self._positions),
            "position_details": position_details,
            "closed_trades": len(self._closed_trades),
            "win_rate": safe_divide(len(wins), max(len(closed_pnls), 1)),
            "avg_win": float(np.mean(wins)) if wins else 0.0,
            "avg_loss": float(np.mean(losses)) if losses else 0.0,
            "profit_factor": safe_divide(sum(wins), abs(sum(losses))),
            "trading_halted": self._trading_halted,
            "halt_reason": self._halt_reason,
        }

    def trade_risk_score(self, position: Position, portfolio_val: float) -> float:
        """
        Compute a risk score for a single trade [0, 1].
        Higher = more risky.
        """
        scores = []

        # Position size vs max allowed
        pos_pct = safe_divide(position.position_value, portfolio_val)
        scores.append(clamp(pos_pct / RISK["max_position_pct"]))

        # Stop distance (wider stop = more risk per pip)
        stop_pct = safe_divide(abs(position.entry_price - position.stop_loss), position.entry_price)
        scores.append(clamp(stop_pct / 0.10))  # 10% stop = max risk score

        # Portfolio exposure
        scores.append(clamp(self.total_exposure(portfolio_val) / RISK["max_portfolio_exposure"]))

        return float(np.mean(scores))

    def reset_daily_loss_tracker(self) -> None:
        """Reset daily P&L tracker (call at market open each day)."""
        today = utc_now().date()
        if today not in self._daily_pnl:
            portfolio_approx = sum(
                p.position_value for p in self._positions.values()
            ) + self.initial_capital
            self._daily_pnl[today] = portfolio_approx

    def resume_trading(self) -> None:
        """Resume trading after a halt (manual override)."""
        self._trading_halted = False
        self._halt_reason = ""
        log.info("Trading resumed by manual override")

    def _halt_trading(self, reason: str) -> None:
        self._trading_halted = True
        self._halt_reason = reason
        log.critical(f"TRADING HALTED: {reason}")
