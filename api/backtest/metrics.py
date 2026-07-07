"""
backtest/metrics.py

Backtesting performance metrics: CAGR, Sharpe, Sortino, max drawdown,
win rate, profit factor, expectancy, and more.
"""

import math
import numpy as np
import pandas as pd
from typing import Optional
from utils.helpers import (
    safe_divide, annualized_return, sharpe_ratio,
    sortino_ratio, max_drawdown, calmar_ratio
)
from utils.logger import get_logger

log = get_logger("metrics")


def compute_all_metrics(
    equity_curve: pd.Series,
    trades: list[dict],
    initial_capital: float,
    risk_free_rate: float = 0.04,
    periods_per_year: int = 252,
) -> dict:
    """
    Compute the full suite of backtest performance metrics.

    Args:
        equity_curve: Portfolio value over time (DatetimeIndex)
        trades: List of completed trade dicts with 'pnl', 'pnl_pct', etc.
        initial_capital: Starting portfolio value
        risk_free_rate: Annual risk-free rate for Sharpe computation
        periods_per_year: Trading periods per year (252 for daily, 8760 for hourly)

    Returns:
        dict with all metrics
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return _empty_metrics()

    returns = equity_curve.pct_change().dropna()
    final_value = float(equity_curve.iloc[-1])
    total_return = safe_divide(final_value - initial_capital, initial_capital)

    # ── Return Metrics ───────────────────────────────────────────────────────
    cagr = annualized_return(returns, periods_per_year)
    sharpe = sharpe_ratio(returns, risk_free_rate, periods_per_year)
    sortino = sortino_ratio(returns, risk_free_rate, periods_per_year)
    mdd = max_drawdown(equity_curve)
    calmar = calmar_ratio(returns, periods_per_year)

    # Volatility
    ann_vol = float(returns.std() * math.sqrt(periods_per_year))
    downside_returns = returns[returns < 0]
    downside_vol = float(downside_returns.std() * math.sqrt(periods_per_year)) if len(downside_returns) > 1 else 0.0

    # ── Drawdown Analysis ────────────────────────────────────────────────────
    rolling_max = equity_curve.cummax()
    drawdown_series = (equity_curve - rolling_max) / rolling_max
    max_dd_duration = _max_drawdown_duration(equity_curve)

    # Recovery factor
    recovery_factor = safe_divide(total_return, mdd)

    # ── Trade Metrics ────────────────────────────────────────────────────────
    trade_metrics = _compute_trade_metrics(trades) if trades else {}

    # ── Distribution Metrics ─────────────────────────────────────────────────
    monthly_returns = _compute_monthly_returns(equity_curve)
    best_month = float(monthly_returns.max()) if not monthly_returns.empty else 0.0
    worst_month = float(monthly_returns.min()) if not monthly_returns.empty else 0.0
    positive_months_pct = float((monthly_returns > 0).mean()) if not monthly_returns.empty else 0.0

    return {
        # Capital
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return * 100, 2),
        "total_pnl": round(final_value - initial_capital, 2),

        # Risk-adjusted returns
        "cagr_pct": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "recovery_factor": round(recovery_factor, 3),

        # Risk
        "max_drawdown_pct": round(mdd * 100, 2),
        "max_dd_duration_days": max_dd_duration,
        "annual_volatility_pct": round(ann_vol * 100, 2),
        "downside_volatility_pct": round(downside_vol * 100, 2),

        # Monthly
        "best_month_pct": round(best_month * 100, 2),
        "worst_month_pct": round(worst_month * 100, 2),
        "positive_months_pct": round(positive_months_pct * 100, 2),

        # Trades
        **trade_metrics,
    }


def _compute_trade_metrics(trades: list[dict]) -> dict:
    """Compute trade-level statistics."""
    if not trades:
        return {
            "total_trades": 0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0, "expectancy": 0.0,
            "avg_hold_hours": 0.0, "largest_win_pct": 0.0,
            "largest_loss_pct": 0.0, "consecutive_wins": 0,
            "consecutive_losses": 0,
        }

    pnls = [t.get("pnl", 0) for t in trades]
    pnl_pcts = [t.get("pnl_pct", 0) for t in trades]
    hold_times = [t.get("hold_hours", 0) for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_pcts = [p for p in pnl_pcts if p > 0]
    loss_pcts = [p for p in pnl_pcts if p < 0]

    win_rate = safe_divide(len(wins), len(pnls))
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    avg_win_pct = float(np.mean(win_pcts)) if win_pcts else 0.0
    avg_loss_pct = float(np.mean(loss_pcts)) if loss_pcts else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = safe_divide(gross_profit, gross_loss)

    # Expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # Consecutive wins/losses
    max_consec_wins = max_consec_losses = 0
    cur_wins = cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins = 0
        max_consec_wins = max(max_consec_wins, cur_wins)
        max_consec_losses = max(max_consec_losses, cur_losses)

    return {
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 3),
        "avg_win_pct": round(avg_win_pct * 100, 4),
        "avg_loss_pct": round(avg_loss_pct * 100, 4),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "expectancy_usd": round(expectancy, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_hold_hours": round(float(np.mean(hold_times)) if hold_times else 0.0, 1),
        "largest_win_pct": round(max(win_pcts) * 100, 2) if win_pcts else 0.0,
        "largest_loss_pct": round(min(loss_pcts) * 100, 2) if loss_pcts else 0.0,
        "consecutive_wins": max_consec_wins,
        "consecutive_losses": max_consec_losses,
    }


def _max_drawdown_duration(equity_curve: pd.Series) -> int:
    """Compute maximum drawdown duration in days."""
    rolling_max = equity_curve.cummax()
    in_drawdown = equity_curve < rolling_max
    if not in_drawdown.any():
        return 0
    # Find longest continuous True streak
    max_dur = 0
    current = 0
    for val in in_drawdown:
        if val:
            current += 1
            max_dur = max(max_dur, current)
        else:
            current = 0
    # Convert periods to approximate days
    if isinstance(equity_curve.index, pd.DatetimeIndex) and len(equity_curve) > 1:
        period_seconds = (equity_curve.index[-1] - equity_curve.index[0]).total_seconds()
        seconds_per_period = period_seconds / len(equity_curve)
        return int(max_dur * seconds_per_period / 86400)
    return max_dur


def _compute_monthly_returns(equity_curve: pd.Series) -> pd.Series:
    """Resample equity curve to monthly returns."""
    try:
        if not isinstance(equity_curve.index, pd.DatetimeIndex):
            return pd.Series(dtype=float)
        monthly = equity_curve.resample("ME").last()
        return monthly.pct_change().dropna()
    except Exception:
        return pd.Series(dtype=float)


def _empty_metrics() -> dict:
    """Return zero-filled metrics dict for empty backtests."""
    return {
        "initial_capital": 0, "final_value": 0, "total_return_pct": 0,
        "total_pnl": 0, "cagr_pct": 0, "sharpe_ratio": 0,
        "sortino_ratio": 0, "calmar_ratio": 0, "recovery_factor": 0,
        "max_drawdown_pct": 0, "max_dd_duration_days": 0,
        "annual_volatility_pct": 0, "downside_volatility_pct": 0,
        "best_month_pct": 0, "worst_month_pct": 0, "positive_months_pct": 0,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "win_rate_pct": 0, "profit_factor": 0, "avg_win_pct": 0,
        "avg_loss_pct": 0, "avg_win_usd": 0, "avg_loss_usd": 0,
        "expectancy_usd": 0, "gross_profit": 0, "gross_loss": 0,
        "avg_hold_hours": 0, "largest_win_pct": 0, "largest_loss_pct": 0,
        "consecutive_wins": 0, "consecutive_losses": 0,
    }


def print_metrics_table(metrics: dict) -> None:
    """Pretty-print a metrics dict to the console."""
    try:
        from tabulate import tabulate
        rows = [(k, v) for k, v in metrics.items() if not isinstance(v, dict)]
        print(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))
    except ImportError:
        for k, v in metrics.items():
            if not isinstance(v, dict):
                print(f"  {k:<35} {v}")
