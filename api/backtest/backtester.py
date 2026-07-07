"""
backtest/backtester.py

Event-driven backtesting engine supporting multi-asset, multi-timeframe strategies.

Design:
- Iterates over time bar-by-bar to prevent look-ahead bias
- Simulates slippage and commission on every trade
- Tracks equity curve, open positions, and trade log
- Supports walk-forward analysis via the WalkForwardBacktester wrapper
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable

from config import BACKTEST, TIMEFRAMES, PRIMARY_TIMEFRAME
from analysis.technical.technical_scoring import score_single_timeframe
from analysis.technical.indicators import atr
from risk.position_sizing import compute_position_size
from risk.stop_loss import compute_stop_take_profit
from backtest.metrics import compute_all_metrics, print_metrics_table
from utils.helpers import safe_divide, clamp, utc_now
from utils.logger import get_logger

log = get_logger("backtester")


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST POSITION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BTPosition:
    symbol: str
    side: str           # 'buy' | 'sell'
    entry_price: float
    units: float
    stop_loss: float
    take_profit: Optional[float]
    entry_bar: int
    entry_time: pd.Timestamp
    strategy: str = "balanced"

    @property
    def position_value(self) -> float:
        return self.units * self.entry_price

    def pnl(self, price: float) -> float:
        if self.side == "buy":
            return (price - self.entry_price) * self.units
        return (self.entry_price - price) * self.units

    def pnl_pct(self, price: float) -> float:
        return safe_divide(self.pnl(price), self.position_value)


# ─────────────────────────────────────────────────────────────────────────────
# BACKTESTER
# ─────────────────────────────────────────────────────────────────────────────

class Backtester:
    """
    Event-driven single-asset backtester.

    Args:
        symbol: Asset symbol
        df: OHLCV DataFrame with DatetimeIndex
        signal_func: Callable(df_slice) -> float score in [-1, +1]
        initial_capital: Starting capital in USD
        commission_pct: Round-trip commission fraction
        slippage_pct: Slippage on each fill
        market_type: 'crypto' | 'stocks' | 'forex' | 'commodities'
    """

    def __init__(
        self,
        symbol: str,
        df: pd.DataFrame,
        signal_func: Callable[[pd.DataFrame], float],
        initial_capital: float = BACKTEST["initial_capital"],
        commission_pct: float = BACKTEST["commission_pct"],
        slippage_pct: float = BACKTEST["slippage_pct"],
        market_type: str = "crypto",
    ) -> None:
        self.symbol = symbol
        self.df = df.copy()
        self.signal_func = signal_func
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.market_type = market_type

        self._positions: dict[str, BTPosition] = {}
        self._trades: list[dict] = []
        self._equity: list[float] = []
        self._equity_index: list[pd.Timestamp] = []

        # Minimum lookback before generating signals
        self._min_bars = 100

    def run(self, start: Optional[str] = None, end: Optional[str] = None) -> dict:
        """
        Run the backtest over the full DataFrame.

        Returns:
            dict with metrics, equity_curve, and trades
        """
        df = self._filter_dates(start, end)
        if len(df) < self._min_bars + 10:
            log.warning(f"Insufficient data for {self.symbol} backtest ({len(df)} bars)")
            return {"metrics": {}, "trades": [], "equity_curve": pd.Series(dtype=float)}

        log.info(
            f"Backtesting {self.symbol} | {len(df)} bars | "
            f"{df.index[0].date()} → {df.index[-1].date()} | "
            f"capital=${self.initial_capital:,.0f}"
        )

        self.capital = self.initial_capital
        self._positions.clear()
        self._trades.clear()
        self._equity.clear()
        self._equity_index.clear()

        for i in range(self._min_bars, len(df)):
            bar = df.iloc[i]
            bar_time = df.index[i]
            df_slice = df.iloc[:i + 1]       # No look-ahead

            close = float(bar["close"])
            high = float(bar["high"])
            low = float(bar["low"])

            # ── Check Exits First ────────────────────────────────────────
            self._check_exits(bar_time, high, low, close)

            # ── Generate Signal ──────────────────────────────────────────
            try:
                score = self.signal_func(df_slice)
            except Exception as e:
                log.debug(f"Signal error at bar {i}: {e}")
                score = 0.0

            # ── Compute ATR for sizing ────────────────────────────────────
            atr_val = 0.0
            try:
                atr_series = atr(df_slice)
                if not atr_series.empty and not math.isnan(atr_series.iloc[-1]):
                    atr_val = float(atr_series.iloc[-1])
            except Exception:
                pass

            # ── Entry Logic ──────────────────────────────────────────────
            portfolio_val = self._portfolio_value(close)
            already_open = self.symbol in self._positions

            if not already_open:
                if score >= 0.20:   # buy threshold
                    side = "buy"
                elif score <= -0.20:  # sell threshold
                    side = "sell"
                else:
                    side = None

                if side:
                    self._open_position(
                        bar_time, i, side, close, atr_val, portfolio_val, score
                    )

            # ── Record Equity ────────────────────────────────────────────
            self._equity.append(self._portfolio_value(close))
            self._equity_index.append(bar_time)

        # Close any remaining positions at last price
        if self._positions:
            last_close = float(df["close"].iloc[-1])
            last_time = df.index[-1]
            for sym in list(self._positions.keys()):
                self._close_position(sym, last_time, last_close, "end_of_backtest")

        equity_curve = pd.Series(
            self._equity,
            index=pd.DatetimeIndex(self._equity_index),
            name="equity",
        )

        metrics = compute_all_metrics(
            equity_curve=equity_curve,
            trades=self._trades,
            initial_capital=self.initial_capital,
        )

        log.info(
            f"Backtest complete: {self.symbol} | "
            f"CAGR={metrics.get('cagr_pct',0):.1f}% | "
            f"Sharpe={metrics.get('sharpe_ratio',0):.2f} | "
            f"MaxDD={metrics.get('max_drawdown_pct',0):.1f}% | "
            f"Trades={metrics.get('total_trades',0)}"
        )

        return {
            "metrics": metrics,
            "trades": self._trades,
            "equity_curve": equity_curve,
        }

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _filter_dates(self, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
        df = self.df
        if start:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df

    def _portfolio_value(self, current_price: float) -> float:
        unrealized = sum(
            p.pnl(current_price) for p in self._positions.values()
        )
        return self.capital + unrealized

    def _open_position(
        self,
        bar_time: pd.Timestamp,
        bar_idx: int,
        side: str,
        price: float,
        atr_val: float,
        portfolio_val: float,
        score: float,
    ) -> None:
        """Open a new backtest position."""
        # Apply slippage
        fill_price = price * (1 + self.slippage_pct) if side == "buy" else price * (1 - self.slippage_pct)

        # Size position
        sizing = compute_position_size(
            portfolio_value=portfolio_val,
            price=fill_price,
            atr_value=atr_val if atr_val > 0 else None,
            signal_score=abs(score),
        )
        units = sizing["units"]
        position_value = sizing["position_value"]

        if units <= 0:
            return

        # Commission
        commission = position_value * self.commission_pct

        # Compute stops
        stp = compute_stop_take_profit(fill_price, side, atr_val if atr_val > 0 else None)

        pos = BTPosition(
            symbol=self.symbol,
            side=side,
            entry_price=fill_price,
            units=units,
            stop_loss=stp["stop_loss"],
            take_profit=stp["take_profit_1"],
            entry_bar=bar_idx,
            entry_time=bar_time,
        )
        self._positions[self.symbol] = pos
        self.capital -= commission

        log.debug(
            f"[{bar_time.date()}] OPEN {side.upper()} {units:.6f} {self.symbol} "
            f"@ {fill_price:.4f} | SL={stp['stop_loss']:.4f} "
            f"TP={stp['take_profit_1']:.4f} | score={score:.3f}"
        )

    def _check_exits(
        self,
        bar_time: pd.Timestamp,
        high: float,
        low: float,
        close: float,
    ) -> None:
        """Check stop loss and take profit for open positions."""
        for sym in list(self._positions.keys()):
            pos = self._positions[sym]

            exit_price = None
            exit_reason = None

            if pos.side == "buy":
                if low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and high >= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"
            else:
                if high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and low <= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"

            if exit_price:
                self._close_position(sym, bar_time, exit_price, exit_reason)

    def _close_position(
        self,
        symbol: str,
        bar_time: pd.Timestamp,
        close_price: float,
        reason: str,
    ) -> None:
        """Close a backtest position and record the trade."""
        pos = self._positions.pop(symbol, None)
        if not pos:
            return

        # Apply slippage on close
        fill_price = (
            close_price * (1 - self.slippage_pct)
            if pos.side == "buy"
            else close_price * (1 + self.slippage_pct)
        )

        pnl = pos.pnl(fill_price)
        commission = pos.position_value * self.commission_pct
        net_pnl = pnl - commission
        self.capital += net_pnl

        hold_hours = (bar_time - pos.entry_time).total_seconds() / 3600

        trade = {
            "symbol": symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": fill_price,
            "units": pos.units,
            "position_value": pos.position_value,
            "pnl": net_pnl,
            "pnl_pct": safe_divide(net_pnl, pos.position_value),
            "gross_pnl": pnl,
            "commission": commission,
            "reason": reason,
            "entry_time": pos.entry_time.isoformat(),
            "exit_time": bar_time.isoformat(),
            "hold_hours": hold_hours,
        }
        self._trades.append(trade)

        log.debug(
            f"[{bar_time.date()}] CLOSE {pos.side.upper()} {symbol} "
            f"@ {fill_price:.4f} | PnL=${net_pnl:+.2f} ({safe_divide(net_pnl, pos.position_value):+.2%}) | {reason}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-ASSET BACKTESTER
# ─────────────────────────────────────────────────────────────────────────────

class MultiAssetBacktester:
    """
    Backtests a strategy across multiple assets simultaneously.
    Each asset runs its own Backtester; results are combined.
    """

    def __init__(
        self,
        symbols: list[str],
        ohlcv_data: dict[str, pd.DataFrame],
        signal_func: Callable[[pd.DataFrame], float],
        initial_capital: float = BACKTEST["initial_capital"],
        market_types: Optional[dict[str, str]] = None,
    ) -> None:
        self.symbols = symbols
        self.ohlcv_data = ohlcv_data
        self.signal_func = signal_func
        self.initial_capital = initial_capital
        self.market_types = market_types or {}
        # Split capital equally across symbols
        self._per_symbol_capital = initial_capital / max(len(symbols), 1)

    def run(self, start: Optional[str] = None, end: Optional[str] = None) -> dict:
        """Run backtest for all symbols and aggregate results."""
        all_results = {}
        combined_trades = []
        equity_curves = {}

        for sym in self.symbols:
            df = self.ohlcv_data.get(sym)
            if df is None or df.empty:
                log.warning(f"No data for {sym}; skipping backtest")
                continue

            bt = Backtester(
                symbol=sym,
                df=df,
                signal_func=self.signal_func,
                initial_capital=self._per_symbol_capital,
                market_type=self.market_types.get(sym, "crypto"),
            )
            result = bt.run(start, end)
            all_results[sym] = result
            combined_trades.extend(result.get("trades", []))

            eq = result.get("equity_curve")
            if eq is not None and not eq.empty:
                equity_curves[sym] = eq

        # Combine equity curves
        if equity_curves:
            combined_equity = pd.DataFrame(equity_curves).fillna(method="ffill").sum(axis=1)
        else:
            combined_equity = pd.Series(dtype=float)

        portfolio_metrics = compute_all_metrics(
            equity_curve=combined_equity,
            trades=combined_trades,
            initial_capital=self.initial_capital,
        )

        return {
            "portfolio_metrics": portfolio_metrics,
            "per_symbol_results": all_results,
            "combined_trades": combined_trades,
            "combined_equity_curve": combined_equity,
        }
