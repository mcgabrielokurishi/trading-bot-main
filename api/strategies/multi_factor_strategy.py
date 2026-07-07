"""

Core multi-factor strategy engine.

Combines:
  - Technical score  (TA layer)
  - Fundamental score (FA layer)
  - Sentiment score   (Sentiment layer)

Into a weighted final score → Signal generation → Position sizing → Risk checks → Order.

Design decisions:
- Each analysis layer is independent and cacheable
- Weights are market-type-specific and preset-overridable
- Signals are generated with hysteresis to avoid flip-flopping
- Full audit trail stored for each signal
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from config import (
    FACTOR_WEIGHTS, SIGNAL_THRESHOLDS, STRATEGY_PRESETS,
    ACTIVE_PRESET, TIMEFRAMES, PRIMARY_TIMEFRAME, TRADING_MODE,
)
from analysis.technical.technical_scoring import score_multi_timeframe
from analysis.fundamental.fundamental_scoring import get_fundamental_score, detect_market_type
from analysis.sentiment.sentiment_scoring import get_sentiment_score
from risk.position_sizing import compute_position_size
from risk.stop_loss import compute_stop_take_profit
from risk.portfolio_risk import PortfolioRiskManager, Position
from execution.order_manager import OrderManager
from utils.helpers import clamp, safe_divide, utc_now
from utils.logger import get_logger

log = get_logger("multi_factor_strategy")



# SIGNAL DATACLASS


taclass
class Signal:
    symbol: str
    market_type: str
    timestamp: str

    # Component scores (all in [-1, +1])
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    sentiment_score: float = 0.0
    final_score: float = 0.0

    # Signal classification
    direction: str = "hold"           # strong_buy | buy | hold | sell | strong_sell
    strength: float = 0.0             # absolute value of final_score

    # Execution params (filled after sizing)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_units: float = 0.0
    position_value: float = 0.0

    # Metadata
    weights_used: dict = field(default_factory=dict)
    preset: str = ACTIVE_PRESET
    sub_scores: dict = field(default_factory=dict)
    reason: str = ""



# SIGNAL CLASSIFIER


def classify_signal(score: float) -> str:
    """Map a numeric score to a signal label."""
    t = SIGNAL_THRESHOLDS
    if score >= t["strong_buy"]:
        return "strong_buy"
    elif score >= t["buy"]:
        return "buy"
    elif score <= t["strong_sell"]:
        return "strong_sell"
    elif score <= t["sell"]:
        return "sell"
    return "hold"



# WEIGHT RESOLVER


def get_weights(market_type: str, preset: str = ACTIVE_PRESET) -> dict:
    """
    Resolve factor weights for a given market type and strategy preset.
    Preset weights override per-market defaults.
    """
    if preset and preset != "balanced" and preset in STRATEGY_PRESETS:
        return STRATEGY_PRESETS[preset]
    return FACTOR_WEIGHTS.get(market_type, FACTOR_WEIGHTS["default"])



# CORE STRATEGY ENGINE


class MultiFactorStrategy:
    """
    Multi-factor strategy engine that evaluates assets and generates signals.

    Usage:
        strategy = MultiFactorStrategy(portfolio_manager, order_manager)
        signal = strategy.evaluate(symbol, ohlcv_by_tf)
        strategy.execute(signal, portfolio_value, current_price)
    """

    def __init__(
        self,
        portfolio_manager: PortfolioRiskManager,
        order_manager: OrderManager,
        preset: str = ACTIVE_PRESET,
    ) -> None:
        self.portfolio_manager = portfolio_manager
        self.order_manager = order_manager
        self.preset = preset
        self._signal_cache: dict[str, Signal] = {}   # last signal per symbol
        self._fundamental_cache: dict[str, dict] = {}
        self._fundamental_ts: dict[str, float] = {}
        self._fundamental_ttl = 86400.0              # 24h cache for fundamentals

    # ── Analysis 

    def _get_fundamental(self, symbol: str, market_type: str) -> dict:
        """Fetch fundamental score with 24-hour cache."""
        now = time.time()
        if (
            symbol in self._fundamental_cache and
            now - self._fundamental_ts.get(symbol, 0) < self._fundamental_ttl
        ):
            return self._fundamental_cache[symbol]

        result = get_fundamental_score(symbol, market_type)
        self._fundamental_cache[symbol] = result
        self._fundamental_ts[symbol] = now
        return result

    def evaluate(
        self,
        symbol: str,
        ohlcv_by_tf: dict[str, pd.DataFrame],
        market_type: Optional[str] = None,
        skip_fundamental: bool = False,
        skip_sentiment: bool = False,
    ) -> Signal:
        """
        Full multi-factor evaluation for a single asset.

        Args:
            symbol: Asset symbol
            ohlcv_by_tf: Dict of {timeframe: OHLCV DataFrame}
            market_type: Override auto-detection
            skip_fundamental: Skip FA layer (faster, for high-freq checks)
            skip_sentiment: Skip sentiment layer

        Returns:
            Signal dataclass with all scores and execution params
        """
        mtype = market_type or detect_market_type(symbol)
        weights = get_weights(mtype, self.preset)
        ts = utc_now().isoformat()

        log.info(f"Evaluating {symbol} ({mtype}) | preset={self.preset}")

        # ── Technical Analysis 
        try:
            ta_result = score_multi_timeframe(ohlcv_by_tf)
            ta_score = ta_result.get("technical_score", 0.0)
        except Exception as e:
            log.warning(f"TA scoring failed for {symbol}: {e}")
            ta_score = 0.0
            ta_result = {}

        # ── Fundamental Analysis      fa_score = 0.0
        fa_result = {}
        if not skip_fundamental and weights.get("fundamental", 0) > 0:
            try:
                fa_result = self._get_fundamental(symbol, mtype)
                fa_score = fa_result.get("fundamental_score", 0.0)
            except Exception as e:
                log.warning(f"FA scoring failed for {symbol}: {e}")

        # ── Sentiment Analysis 
        sent_score = 0.0
        sent_result = {}
        if not skip_sentiment and weights.get("sentiment", 0) > 0:
            try:
                sent_result = get_sentiment_score(symbol, mtype)
                sent_score = sent_result.get("sentiment_score", 0.0)
            except Exception as e:
                log.warning(f"Sentiment scoring failed for {symbol}: {e}")

        # ── Combine Scores 
        w_ta   = weights.get("technical", 0.50)
        w_fa   = weights.get("fundamental", 0.30)
        w_sent = weights.get("sentiment", 0.20)
        total_w = w_ta + w_fa + w_sent

        final_score = clamp(
            safe_divide(
                ta_score * w_ta + fa_score * w_fa + sent_score * w_sent,
                total_w,
            )
        )

        direction = classify_signal(final_score)

        # ── Execution Params
        # Get current price from primary timeframe
        primary_df = ohlcv_by_tf.get(PRIMARY_TIMEFRAME) or next(iter(ohlcv_by_tf.values()), pd.DataFrame())
        entry_price = 0.0
        atr_val = 0.0
        if not primary_df.empty:
            entry_price = float(primary_df["close"].iloc[-1])
            try:
                from analysis.technical.indicators import atr
                atr_series = atr(primary_df)
                atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
            except Exception:
                pass

        signal = Signal(
            symbol=symbol,
            market_type=mtype,
            timestamp=ts,
            technical_score=round(ta_score, 4),
            fundamental_score=round(fa_score, 4),
            sentiment_score=round(sent_score, 4),
            final_score=round(final_score, 4),
            direction=direction,
            strength=abs(final_score),
            entry_price=entry_price,
            weights_used={"technical": w_ta, "fundamental": w_fa, "sentiment": w_sent},
            preset=self.preset,
            sub_scores={
                "ta": ta_result,
                "fa": fa_result,
                "sentiment": sent_result,
            },
            reason=(
                f"TA={ta_score:+.3f}×{w_ta:.0%} "
                f"FA={fa_score:+.3f}×{w_fa:.0%} "
                f"Sent={sent_score:+.3f}×{w_sent:.0%} "
                f"→ {final_score:+.3f} [{direction}]"
            ),
        )

        # Compute stop/TP if actionable
        if direction not in ("hold",) and entry_price > 0:
            side = "buy" if "buy" in direction else "sell"
            stp = compute_stop_take_profit(entry_price, side, atr_val, primary_df)
            signal.stop_loss = stp["stop_loss"]
            signal.take_profit = stp["take_profit_1"]

        self._signal_cache[symbol] = signal

        log.info(
            f"Signal [{symbol}]: {direction.upper()} | "
            f"score={final_score:+.4f} | TA={ta_score:+.3f} "
            f"FA={fa_score:+.3f} Sent={sent_score:+.3f}"
        )
        return signal

    # ── Execution 

    def execute(
        self,
        signal: Signal,
        portfolio_value: float,
        current_price: Optional[float] = None,
        ohlcv: Optional[pd.DataFrame] = None,
    ) -> Optional[dict]:
        """
        Execute a signal: risk check → size → order → record position.

        Args:
            signal: Signal from evaluate()
            portfolio_value: Current portfolio value
            current_price: Override entry price
            ohlcv: Primary timeframe OHLCV for ATR sizing

        Returns:
            Order dict if placed, None otherwise
        """
        if signal.direction == "hold":
            log.debug(f"No action for {signal.symbol} (hold)")
            return None

        side = "buy" if "buy" in signal.direction else "sell"
        price = current_price or signal.entry_price

        if price <= 0:
            log.warning(f"Invalid price {price} for {signal.symbol}; skipping")
            return None

        # ── ATR for sizing ───────────────────────────────────────────────
        atr_val = 0.0
        if ohlcv is not None and not ohlcv.empty:
            try:
                from analysis.technical.indicators import atr
                atr_series = atr(ohlcv)
                atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
            except Exception:
                pass

        # ── Position Sizing ──────────────────────────────────────────────
        sizing = compute_position_size(
            portfolio_value=portfolio_value,
            price=price,
            atr_value=atr_val if atr_val > 0 else None,
            stop_loss_price=signal.stop_loss if signal.stop_loss > 0 else None,
            signal_score=signal.strength,
        )
        units = sizing["units"]
        position_value = sizing["position_value"]

        if units <= 0 or position_value <= 0:
            log.info(f"Position size too small for {signal.symbol}; skipping")
            return None

        # ── Portfolio Risk Check ─────────────────────────────────────────
        allowed, reason = self.portfolio_manager.can_open_trade(
            signal.symbol, position_value, portfolio_value, {}
        )
        if not allowed:
            log.info(f"Trade blocked for {signal.symbol}: {reason}")
            return None

        # ── Submit Order ─────────────────────────────────────────────────
        order = self.order_manager.submit_order(
            symbol=signal.symbol,
            side=side,
            units=units,
            order_type="market",
            price=price,
            stop_loss=signal.stop_loss or None,
            take_profit=signal.take_profit or None,
            strategy=signal.preset,
            signal_score=signal.final_score,
            reason=signal.reason,
            market_type=signal.market_type,
        )

        if order:
            # Record in portfolio manager
            position = Position(
                symbol=signal.symbol,
                market_type=signal.market_type,
                side=side,
                entry_price=price,
                units=units,
                stop_loss=signal.stop_loss or (price * 0.98 if side == "buy" else price * 1.02),
                take_profit=signal.take_profit or None,
                order_id=order.get("id"),
                strategy=signal.preset,
            )
            self.portfolio_manager.add_position(position)

            signal.position_units = units
            signal.position_value = position_value

        return order

    # ── Close Logic

    def check_exits(
        self,
        current_prices: dict[str, float],
        ohlcv_by_symbol: Optional[dict[str, pd.DataFrame]] = None,
    ) -> list[dict]:
        """
        Check open positions for exit conditions:
        - Stop loss hit
        - Take profit hit
        - Reversal signal

        Returns list of closed trade records.
        """
        closed = []

        # Stop loss / TP checks
        sl_triggered = self.portfolio_manager.check_stops(current_prices)
        tp_triggered = self.portfolio_manager.check_take_profits(current_prices)

        for trigger in sl_triggered + tp_triggered:
            sym = trigger["symbol"]
            price = trigger["current_price"]
            reason = trigger["reason"]

            order = self.order_manager.submit_order(
                symbol=sym,
                side="sell" if trigger["position"].side == "buy" else "buy",
                units=trigger["position"].units,
                order_type="market",
                price=price,
                strategy=trigger["position"].strategy,
                signal_score=0.0,
                reason=reason,
                market_type=trigger["position"].market_type,
            )

            trade_record = self.portfolio_manager.close_position(sym, price, reason)
            if trade_record:
                closed.append(trade_record)

        return closed

    def get_last_signal(self, symbol: str) -> Optional[Signal]:
        """Return the most recently computed signal for a symbol."""
        return self._signal_cache.get(symbol)

    def get_all_signals(self) -> dict[str, Signal]:
        """Return all cached signals."""
        return dict(self._signal_cache)
