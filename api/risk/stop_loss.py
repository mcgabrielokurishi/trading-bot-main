"""
risk/stop_loss.py

Stop-loss and take-profit computation: fixed %, ATR-based, trailing stops,
and dynamic take-profit using support/resistance levels.
"""

import numpy as np
import pandas as pd
from typing import Optional
from config import RISK
from utils.helpers import safe_divide, clamp
from utils.logger import get_logger

log = get_logger("stop_loss")


# ─────────────────────────────────────────────────────────────────────────────
# STOP LOSS COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def fixed_pct_stop(
    entry_price: float,
    side: str,
    stop_pct: Optional[float] = None,
) -> float:
    """
    Fixed percentage stop loss.

    Args:
        entry_price: Trade entry price
        side: 'buy' or 'sell'
        stop_pct: Stop distance as fraction of price (e.g. 0.02 = 2%)

    Returns:
        Stop loss price
    """
    stop_pct = stop_pct or RISK["fixed_stop_pct"]
    if side == "buy":
        return entry_price * (1 - stop_pct)
    else:
        return entry_price * (1 + stop_pct)


def atr_stop(
    entry_price: float,
    side: str,
    atr_value: float,
    multiplier: Optional[float] = None,
) -> float:
    """
    ATR-based stop loss. Stop is placed at entry ± (multiplier × ATR).

    Args:
        entry_price: Trade entry price
        side: 'buy' or 'sell'
        atr_value: Current ATR value
        multiplier: Number of ATRs for stop distance

    Returns:
        Stop loss price
    """
    multiplier = multiplier or RISK["atr_stop_multiplier"]
    stop_distance = atr_value * multiplier
    if side == "buy":
        return entry_price - stop_distance
    else:
        return entry_price + stop_distance


class TrailingStop:
    """
    Stateful trailing stop loss tracker.
    Updates the stop price as the trade moves favorably.
    """

    def __init__(
        self,
        entry_price: float,
        side: str,
        trail_pct: Optional[float] = None,
        atr_value: Optional[float] = None,
        atr_multiplier: float = 2.0,
    ) -> None:
        self.entry_price = entry_price
        self.side = side.lower()
        self.trail_pct = trail_pct or RISK["trailing_stop_pct"]
        self.atr_value = atr_value
        self.atr_multiplier = atr_multiplier

        # Use ATR-based trailing distance if provided, else pct-based
        if atr_value:
            self.trail_distance = atr_value * atr_multiplier
        else:
            self.trail_distance = entry_price * self.trail_pct

        # Initialize stop price
        if self.side == "buy":
            self.best_price = entry_price
            self.stop_price = entry_price - self.trail_distance
        else:
            self.best_price = entry_price
            self.stop_price = entry_price + self.trail_distance

        log.debug(
            f"TrailingStop init: {side} @ {entry_price:.6f}, "
            f"stop={self.stop_price:.6f}, trail={self.trail_distance:.6f}"
        )

    def update(self, current_price: float) -> tuple[float, bool]:
        """
        Update trailing stop with current price.

        Returns:
            (new_stop_price, is_triggered)
        """
        triggered = False

        if self.side == "buy":
            if current_price > self.best_price:
                self.best_price = current_price
                new_stop = current_price - self.trail_distance
                self.stop_price = max(self.stop_price, new_stop)

            if current_price <= self.stop_price:
                triggered = True
                log.info(
                    f"Trailing stop triggered: price={current_price:.6f} <= stop={self.stop_price:.6f}"
                )
        else:
            if current_price < self.best_price:
                self.best_price = current_price
                new_stop = current_price + self.trail_distance
                self.stop_price = min(self.stop_price, new_stop)

            if current_price >= self.stop_price:
                triggered = True
                log.info(
                    f"Trailing stop triggered: price={current_price:.6f} >= stop={self.stop_price:.6f}"
                )

        return self.stop_price, triggered

    @property
    def distance_pct(self) -> float:
        """Current stop distance as % of best price."""
        return safe_divide(self.trail_distance, self.best_price)

    @property
    def unrealized_pnl_pct(self) -> float:
        """Unrealized P&L at current best price vs entry."""
        if self.side == "buy":
            return safe_divide(self.best_price - self.entry_price, self.entry_price)
        else:
            return safe_divide(self.entry_price - self.best_price, self.entry_price)


# ─────────────────────────────────────────────────────────────────────────────
# TAKE PROFIT COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def fixed_rr_take_profit(
    entry_price: float,
    stop_loss_price: float,
    side: str,
    rr_ratio: Optional[float] = None,
) -> float:
    """
    Fixed Risk:Reward take profit.

    Args:
        entry_price: Entry price
        stop_loss_price: Stop loss price
        side: 'buy' or 'sell'
        rr_ratio: Risk:Reward ratio (e.g. 2.0 means target = 2x the stop distance)

    Returns:
        Take profit price
    """
    rr_ratio = rr_ratio or RISK["take_profit_rr"]
    stop_distance = abs(entry_price - stop_loss_price)
    tp_distance = stop_distance * rr_ratio

    if side == "buy":
        return entry_price + tp_distance
    else:
        return entry_price - tp_distance


def dynamic_take_profit(
    entry_price: float,
    stop_loss_price: float,
    side: str,
    resistance_levels: Optional[list[float]] = None,
    support_levels: Optional[list[float]] = None,
    rr_ratio: Optional[float] = None,
) -> dict:
    """
    Dynamic take profit using support/resistance levels.
    Falls back to fixed R:R if no levels available.

    Args:
        entry_price: Entry price
        stop_loss_price: Stop loss price
        side: 'buy' or 'sell'
        resistance_levels: List of resistance prices (for long trades)
        support_levels: List of support prices (for short trades)
        rr_ratio: Minimum R:R ratio for the target to be acceptable

    Returns:
        dict with 'tp1', 'tp2', 'tp3' take profit levels
    """
    rr_ratio = rr_ratio or RISK["take_profit_rr"]
    stop_distance = abs(entry_price - stop_loss_price)
    min_tp_distance = stop_distance * rr_ratio

    # Fixed R:R as baseline
    base_tp = fixed_rr_take_profit(entry_price, stop_loss_price, side, rr_ratio)

    tp_levels = [base_tp]

    if side == "buy" and resistance_levels:
        # Find resistance levels above entry that meet minimum R:R
        valid = sorted([
            r for r in resistance_levels
            if r > entry_price + min_tp_distance
        ])
        tp_levels = valid[:3] if valid else tp_levels
        # Always include base_tp as fallback
        if not tp_levels:
            tp_levels = [base_tp]

    elif side == "sell" and support_levels:
        valid = sorted([
            s for s in support_levels
            if s < entry_price - min_tp_distance
        ], reverse=True)
        tp_levels = valid[:3] if valid else tp_levels
        if not tp_levels:
            tp_levels = [base_tp]

    # Pad to 3 levels if fewer
    while len(tp_levels) < 3:
        last = tp_levels[-1]
        if side == "buy":
            tp_levels.append(last + stop_distance)
        else:
            tp_levels.append(last - stop_distance)

    return {
        "tp1": tp_levels[0],
        "tp2": tp_levels[1] if len(tp_levels) > 1 else None,
        "tp3": tp_levels[2] if len(tp_levels) > 2 else None,
        "base_rr_tp": base_tp,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MASTER STOP/TP CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

def compute_stop_take_profit(
    entry_price: float,
    side: str,
    atr_value: Optional[float] = None,
    df: Optional[pd.DataFrame] = None,
    method: Optional[str] = None,
) -> dict:
    """
    Compute stop loss and take profit levels for a trade.

    Args:
        entry_price: Trade entry price
        side: 'buy' or 'sell'
        atr_value: ATR value for ATR-based stops
        df: OHLCV DataFrame for dynamic S/R levels
        method: Override stop method

    Returns:
        dict with stop_loss, take_profit levels, and trailing stop setup
    """
    method = method or RISK["stop_loss_method"]

    # Compute stop loss
    if method == "atr" and atr_value:
        sl = atr_stop(entry_price, side, atr_value)
    elif method == "trailing":
        sl = atr_stop(entry_price, side, atr_value) if atr_value else fixed_pct_stop(entry_price, side)
    else:
        sl = fixed_pct_stop(entry_price, side)

    # Extract S/R levels from DataFrame if available
    resistance_levels, support_levels = [], []
    if df is not None and not df.empty:
        try:
            from analysis.technical.indicators import swing_points
            swings = swing_points(df, window=10)
            resistance_levels = sorted(
                swings["swing_high"].dropna().tolist(), reverse=True
            )
            support_levels = sorted(swings["swing_low"].dropna().tolist())
        except Exception:
            pass

    # Compute take profit
    if RISK.get("use_dynamic_tp") and (resistance_levels or support_levels):
        tp_dict = dynamic_take_profit(
            entry_price, sl, side, resistance_levels, support_levels
        )
    else:
        base_tp = fixed_rr_take_profit(entry_price, sl, side)
        stop_dist = abs(entry_price - sl)
        tp_dict = {
            "tp1": base_tp,
            "tp2": (entry_price + stop_dist * 3) if side == "buy" else (entry_price - stop_dist * 3),
            "tp3": None,
            "base_rr_tp": base_tp,
        }

    stop_pct = abs(entry_price - sl) / entry_price
    tp_pct = abs(entry_price - tp_dict["tp1"]) / entry_price

    return {
        "stop_loss": sl,
        "take_profit_1": tp_dict["tp1"],
        "take_profit_2": tp_dict.get("tp2"),
        "take_profit_3": tp_dict.get("tp3"),
        "stop_pct": stop_pct,
        "tp_pct": tp_pct,
        "rr_ratio": safe_divide(tp_pct, stop_pct),
        "method": method,
        "use_trailing": method == "trailing",
    }
