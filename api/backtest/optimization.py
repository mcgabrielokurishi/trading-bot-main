"""
backtest/optimization.py

Walk-forward analysis and parameter grid search for strategy optimization.

Walk-forward:
  - Splits data into N in-sample + out-of-sample windows
  - Optimizes on IS, tests on OOS
  - Averages OOS results for realistic performance estimate

Grid search:
  - Exhaustive search over parameter combinations
  - Optimizes a chosen metric (Sharpe, CAGR, profit_factor, etc.)
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from config import BACKTEST
from backtest.backtester import Backtester
from backtest.metrics import compute_all_metrics, print_metrics_table
from utils.logger import get_logger

log = get_logger("optimization")


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WalkForwardWindow:
    window_idx: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    is_metrics: dict
    oos_metrics: dict
    best_params: dict


class WalkForwardBacktester:
    """
    Walk-forward analysis wrapper.

    Splits the full date range into N windows, each with:
      - In-sample (IS) period: used to optimize parameters
      - Out-of-sample (OOS) period: used to evaluate performance

    Args:
        symbol: Asset symbol
        df: Full OHLCV DataFrame
        signal_factory: Callable(params: dict) → signal_func
        param_grid: Dict of {param_name: [values_to_try]}
        n_windows: Number of walk-forward windows
        oos_pct: Fraction of each window reserved for OOS
        optimize_metric: Metric to maximize on IS period
        initial_capital: Starting capital per window
    """

    def __init__(
        self,
        symbol: str,
        df: pd.DataFrame,
        signal_factory: Callable[[dict], Callable[[pd.DataFrame], float]],
        param_grid: dict[str, list],
        n_windows: int = BACKTEST["walk_forward_periods"],
        oos_pct: float = BACKTEST["out_of_sample_pct"],
        optimize_metric: str = BACKTEST["optimization_metric"],
        initial_capital: float = BACKTEST["initial_capital"],
    ) -> None:
        self.symbol = symbol
        self.df = df
        self.signal_factory = signal_factory
        self.param_grid = param_grid
        self.n_windows = n_windows
        self.oos_pct = oos_pct
        self.optimize_metric = optimize_metric
        self.initial_capital = initial_capital

    def _split_windows(self) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        """Split DataFrame index into N IS/OOS windows."""
        idx = self.df.index
        total = len(idx)
        window_size = total // self.n_windows
        oos_size = max(1, int(window_size * self.oos_pct))
        is_size = window_size - oos_size

        windows = []
        for i in range(self.n_windows):
            start = i * window_size
            is_end = start + is_size
            oos_end = start + window_size
            if oos_end > total:
                oos_end = total
            if is_end >= total:
                break
            windows.append((
                idx[start], idx[is_end - 1],
                idx[is_end], idx[oos_end - 1],
            ))
        return windows

    def run(self) -> dict:
        """
        Execute full walk-forward analysis.

        Returns:
            dict with per-window results, OOS aggregate metrics, best params per window
        """
        windows = self._split_windows()
        if not windows:
            log.error("Could not create walk-forward windows (insufficient data)")
            return {}

        log.info(
            f"Walk-forward: {self.symbol} | {len(windows)} windows | "
            f"OOS={self.oos_pct:.0%} | optimize={self.optimize_metric}"
        )

        wf_results = []
        all_oos_trades = []
        oos_equity_parts = []

        for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
            log.info(f"Window {i+1}/{len(windows)}: IS={is_start.date()}–{is_end.date()} | OOS={oos_start.date()}–{oos_end.date()}")

            # ── Optimize on IS ───────────────────────────────────────────
            best_params, is_metrics = self._optimize_is(
                str(is_start.date()), str(is_end.date())
            )

            # ── Evaluate on OOS with best params ─────────────────────────
            signal_func = self.signal_factory(best_params)
            bt_oos = Backtester(
                symbol=self.symbol,
                df=self.df,
                signal_func=signal_func,
                initial_capital=self.initial_capital,
            )
            oos_result = bt_oos.run(str(oos_start.date()), str(oos_end.date()))
            oos_metrics = oos_result.get("metrics", {})
            oos_trades = oos_result.get("trades", [])
            oos_eq = oos_result.get("equity_curve", pd.Series(dtype=float))

            all_oos_trades.extend(oos_trades)
            if not oos_eq.empty:
                oos_equity_parts.append(oos_eq)

            wf_results.append(WalkForwardWindow(
                window_idx=i + 1,
                is_start=str(is_start.date()),
                is_end=str(is_end.date()),
                oos_start=str(oos_start.date()),
                oos_end=str(oos_end.date()),
                is_metrics=is_metrics,
                oos_metrics=oos_metrics,
                best_params=best_params,
            ))

            log.info(
                f"  IS: Sharpe={is_metrics.get('sharpe_ratio',0):.2f} "
                f"CAGR={is_metrics.get('cagr_pct',0):.1f}% | "
                f"OOS: Sharpe={oos_metrics.get('sharpe_ratio',0):.2f} "
                f"CAGR={oos_metrics.get('cagr_pct',0):.1f}% | "
                f"params={best_params}"
            )

        # Aggregate OOS equity curve
        if oos_equity_parts:
            # Chain OOS periods: normalize each to start at 1, then chain
            chained = self._chain_equity_curves(oos_equity_parts)
        else:
            chained = pd.Series(dtype=float)

        agg_oos_metrics = compute_all_metrics(
            equity_curve=chained if not chained.empty else pd.Series(
                [self.initial_capital], index=[pd.Timestamp("2020-01-01", tz="UTC")]
            ),
            trades=all_oos_trades,
            initial_capital=self.initial_capital,
        )

        # Robustness: IS vs OOS metric ratio (>0.5 = good)
        avg_is_sharpe = float(np.mean([w.is_metrics.get("sharpe_ratio", 0) for w in wf_results]))
        avg_oos_sharpe = float(np.mean([w.oos_metrics.get("sharpe_ratio", 0) for w in wf_results]))
        robustness = min(1.0, max(0.0, avg_oos_sharpe / max(avg_is_sharpe, 0.001)))

        log.info(f"Walk-forward complete | Robustness={robustness:.2f} | OOS Sharpe={avg_oos_sharpe:.2f}")
        print("\n=== Walk-Forward OOS Aggregate Metrics ===")
        print_metrics_table(agg_oos_metrics)

        return {
            "windows": [vars(w) for w in wf_results],
            "oos_aggregate_metrics": agg_oos_metrics,
            "oos_equity_curve": chained,
            "all_oos_trades": all_oos_trades,
            "avg_is_sharpe": round(avg_is_sharpe, 3),
            "avg_oos_sharpe": round(avg_oos_sharpe, 3),
            "robustness_score": round(robustness, 3),
        }

    def _optimize_is(self, start: str, end: str) -> tuple[dict, dict]:
        """Grid search over param_grid on the IS period."""
        best_score = -np.inf
        best_params = {}
        best_metrics = {}

        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())

        for combo in itertools.product(*param_values):
            params = dict(zip(param_names, combo))
            try:
                signal_func = self.signal_factory(params)
                bt = Backtester(
                    symbol=self.symbol,
                    df=self.df,
                    signal_func=signal_func,
                    initial_capital=self.initial_capital,
                )
                result = bt.run(start, end)
                metrics = result.get("metrics", {})
                score = metrics.get(self.optimize_metric, -np.inf)

                # Guard against degenerate results
                if metrics.get("total_trades", 0) < 5:
                    continue
                if metrics.get("max_drawdown_pct", 100) > 50:
                    score *= 0.5  # Penalize high drawdown

                if score > best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics
            except Exception as e:
                log.debug(f"IS optimization error for params {params}: {e}")

        return best_params or {p: v[0] for p, v in self.param_grid.items()}, best_metrics

    @staticmethod
    def _chain_equity_curves(curves: list[pd.Series]) -> pd.Series:
        """Chain multiple equity curve segments end-to-end."""
        if not curves:
            return pd.Series(dtype=float)
        chains = []
        multiplier = 1.0
        for curve in curves:
            if curve.empty:
                continue
            # Normalize to start at multiplier
            normalized = curve / float(curve.iloc[0]) * multiplier
            multiplier = float(normalized.iloc[-1])
            chains.append(normalized)
        if not chains:
            return pd.Series(dtype=float)
        return pd.concat(chains).sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# SIMPLE GRID SEARCH
# ─────────────────────────────────────────────────────────────────────────────

def grid_search(
    symbol: str,
    df: pd.DataFrame,
    signal_factory: Callable[[dict], Callable[[pd.DataFrame], float]],
    param_grid: dict[str, list],
    optimize_metric: str = "sharpe_ratio",
    start: Optional[str] = None,
    end: Optional[str] = None,
    initial_capital: float = BACKTEST["initial_capital"],
    top_n: int = 5,
) -> list[dict]:
    """
    Exhaustive grid search over parameter combinations.

    Args:
        symbol: Asset symbol
        df: OHLCV DataFrame
        signal_factory: Callable(params) → signal_func
        param_grid: Dict of {param_name: [values_to_try]}
        optimize_metric: Metric to maximize
        start / end: Date filter strings
        initial_capital: Starting capital
        top_n: Return top N results

    Returns:
        List of top_n result dicts sorted by optimize_metric descending
    """
    param_names = list(param_grid.keys())
    combinations = list(itertools.product(*param_grid.values()))
    log.info(f"Grid search: {symbol} | {len(combinations)} combinations | metric={optimize_metric}")

    results = []
    for combo in combinations:
        params = dict(zip(param_names, combo))
        try:
            signal_func = signal_factory(params)
            bt = Backtester(symbol=symbol, df=df, signal_func=signal_func, initial_capital=initial_capital)
            result = bt.run(start, end)
            metrics = result.get("metrics", {})
            if metrics.get("total_trades", 0) >= 5:
                results.append({"params": params, "metrics": metrics})
        except Exception as e:
            log.debug(f"Grid search error for {params}: {e}")

    results.sort(key=lambda x: x["metrics"].get(optimize_metric, -np.inf), reverse=True)

    log.info(f"Grid search complete: {len(results)} valid results")
    if results:
        best = results[0]
        log.info(
            f"Best params: {best['params']} | "
            f"{optimize_metric}={best['metrics'].get(optimize_metric, 0):.3f}"
        )

    return results[:top_n]
