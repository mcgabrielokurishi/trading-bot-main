"""
risk/position_sizing.py

Position sizing methods: fixed fractional, Kelly criterion, and ATR-based volatility sizing.
All methods return position size in units of the base asset.
"""

import math
import numpy as np
import pandas as pd
from typing import Optional
from config import RISK
from utils.helpers import safe_divide, clamp
from utils.logger import get_logger

log = get_logger("position_sizing")


# ─────────────────────────────────────────────────────────────────────────────
# FIXED FRACTIONAL
# ─────────────────────────────────────────────────────────────────────────────

def fixed_fractional_size(
    portfolio_value: float,
    price: float,
    risk_pct: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
) -> float:
    """
    Fixed fractional position sizing.

    Risk a fixed percentage of the portfolio per trade.
    If stop_loss_pct provided, size so that the stop loss = risk_pct of portfolio.

    Args:
        portfolio_value: Total portfolio value in quote currency
        price: Entry price of the asset
        risk_pct: Fraction of portfolio to risk (default from config)
        stop_loss_pct: Distance to stop loss as fraction of price

    Returns:
        Position size in base asset units
    """
    risk_pct = risk_pct or RISK["fixed_risk_pct"]
    risk_amount = portfolio_value * risk_pct

    if stop_loss_pct and stop_loss_pct > 0:
        # Size so that (position * price * stop_loss_pct) = risk_amount
        position_value = safe_divide(risk_amount, stop_loss_pct)
        return safe_divide(position_value, price)
    else:
        # Simple: invest risk_pct of portfolio
        return safe_divide(risk_amount, price)


# ─────────────────────────────────────────────────────────────────────────────
# KELLY CRITERION
# ─────────────────────────────────────────────────────────────────────────────

def kelly_size(
    portfolio_value: float,
    price: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: Optional[float] = None,
) -> float:
    """
    Kelly Criterion position sizing (fractional Kelly for risk control).

    Kelly fraction = (win_rate / |avg_loss|) - ((1 - win_rate) / avg_win)
    Full Kelly can be aggressive; fraction controls conservatism.

    Args:
        portfolio_value: Total portfolio value
        price: Entry price
        win_rate: Historical win probability [0, 1]
        avg_win: Average win as fraction of position value (e.g. 0.05 = 5%)
        avg_loss: Average loss as fraction of position value (positive value)
        fraction: Fraction of full Kelly to use (default from config)

    Returns:
        Position size in base asset units
    """
    fraction = fraction or RISK["kelly_fraction"]

    if avg_loss <= 0 or avg_win <= 0:
        log.warning("Kelly: invalid avg_win or avg_loss; falling back to fixed fractional")
        return fixed_fractional_size(portfolio_value, price)

    # Kelly formula
    b = avg_win / avg_loss  # odds ratio
    p = win_rate
    q = 1 - win_rate

    kelly_f = (b * p - q) / b

    if kelly_f <= 0:
        log.debug(f"Kelly fraction negative ({kelly_f:.4f}); no position recommended")
        return 0.0

    # Apply fractional Kelly
    position_fraction = clamp(kelly_f * fraction, 0.0, RISK["max_position_pct"])

    position_value = portfolio_value * position_fraction
    return safe_divide(position_value, price)


# ─────────────────────────────────────────────────────────────────────────────
# ATR-BASED VOLATILITY SIZING
# ─────────────────────────────────────────────────────────────────────────────

def atr_based_size(
    portfolio_value: float,
    price: float,
    atr_value: float,
    risk_pct: Optional[float] = None,
    atr_multiplier: Optional[float] = None,
) -> float:
    """
    Volatility-adjusted position sizing using Average True Range.

    Stop is placed at entry ± (atr_multiplier * ATR).
    Position is sized so that the stop loss = risk_pct of portfolio.

    Args:
        portfolio_value: Total portfolio value
        price: Entry price
        atr_value: Current ATR value
        risk_pct: Max risk per trade as fraction of portfolio
        atr_multiplier: Number of ATRs for stop distance

    Returns:
        Position size in base asset units
    """
    risk_pct = risk_pct or RISK["fixed_risk_pct"]
    atr_multiplier = atr_multiplier or RISK["atr_risk_multiplier"]

    if atr_value <= 0 or price <= 0:
        log.warning("ATR sizing: invalid ATR or price")
        return 0.0

    stop_distance = atr_value * atr_multiplier
    stop_pct = safe_divide(stop_distance, price)

    if stop_pct <= 0:
        return 0.0

    risk_amount = portfolio_value * risk_pct
    position_value = safe_divide(risk_amount, stop_pct)

    # Cap at max_position_pct of portfolio
    max_value = portfolio_value * RISK["max_position_pct"]
    position_value = min(position_value, max_value)

    return safe_divide(position_value, price)


# ─────────────────────────────────────────────────────────────────────────────
# MASTER POSITION SIZER
# ─────────────────────────────────────────────────────────────────────────────

def compute_position_size(
    portfolio_value: float,
    price: float,
    atr_value: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
    win_rate: float = 0.5,
    avg_win_pct: float = 0.05,
    avg_loss_pct: float = 0.03,
    method: Optional[str] = None,
    signal_score: float = 1.0,
) -> dict:
    """
    Compute position size using the configured method.

    Args:
        portfolio_value: Current total portfolio value
        price: Asset entry price
        atr_value: Current ATR for volatility sizing
        stop_loss_price: Absolute stop-loss price (alternative to pct)
        win_rate: Historical strategy win rate
        avg_win_pct: Average win as % of position
        avg_loss_pct: Average loss as % of position
        method: Override sizing method ('fixed_fractional'|'kelly'|'atr_based')
        signal_score: Score strength [0, 1]; scales position proportionally

    Returns:
        dict with 'units', 'position_value', 'risk_amount', 'stop_distance'
    """
    method = method or RISK["position_sizing_method"]
    min_order_value = RISK.get("min_order_usdt", 10.0)

    # Compute stop loss percentage if absolute stop provided
    stop_pct = None
    if stop_loss_price and price > 0:
        stop_pct = abs(price - stop_loss_price) / price

    # Compute base position size
    if method == "kelly":
        units = kelly_size(portfolio_value, price, win_rate, avg_win_pct, avg_loss_pct)
    elif method == "atr_based" and atr_value:
        units = atr_based_size(portfolio_value, price, atr_value)
    else:
        units = fixed_fractional_size(portfolio_value, price, stop_loss_pct=stop_pct)

    # Scale by signal conviction (stronger signal → larger position)
    conviction_scale = clamp(abs(signal_score), 0.25, 1.0)
    units *= conviction_scale

    position_value = units * price

    # Enforce minimum order
    if position_value < min_order_value:
        log.debug(f"Position value ${position_value:.2f} below minimum ${min_order_value}; returning 0")
        units = 0.0
        position_value = 0.0

    # Enforce maximum position cap
    max_position_value = portfolio_value * RISK["max_position_pct"]
    if position_value > max_position_value:
        units = safe_divide(max_position_value, price)
        position_value = max_position_value

    # Compute risk amount
    stop_distance = (stop_pct or RISK["fixed_stop_pct"]) * price
    risk_amount = units * stop_distance

    return {
        "units": units,
        "position_value": position_value,
        "risk_amount": risk_amount,
        "stop_distance": stop_distance,
        "sizing_method": method,
        "conviction_scale": conviction_scale,
        "pct_of_portfolio": safe_divide(position_value, portfolio_value),
    }
