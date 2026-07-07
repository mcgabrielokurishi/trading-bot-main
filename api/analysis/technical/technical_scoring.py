"""
Combines all technical indicators into a unified score in [-1, +1].
Each indicator group is scored independently, then weighted into a final score.

Design:
- Trend score: direction from MAs, Ichimoku, ADX, SAR, SuperTrend
- Momentum score: RSI, Stoch, CCI, Williams %R, MACD, AO
- Volatility score: BB position, squeeze, ATR regime
- Volume score: OBV trend, MFI, CMF, VWAP relationship
- Pattern score: from patterns.py
All sub-scores are normalized to [-1, +1] then weighted.
"""

import numpy as np
import pandas as pd
from typing import Optional
from config import INDICATORS
from analysis.technical.indicators import (
    sma, ema, hma, ichimoku, macd, adx, atr,
    parabolic_sar, supertrend, rsi, stochastic,
    cci, williams_r, roc, momentum, awesome_oscillator,
    bollinger_bands, keltner_channels, donchian_channels,
    historical_volatility, obv, vwap, mfi, chaikin_money_flow,
    accumulation_distribution, volume_oscillator,
    pivot_points, linear_regression_channel,
    detect_divergence, swing_points, trend_strength, qstick,
)
from analysis.technical.patterns import pattern_score
from utils.helpers import clamp, safe_divide, normalize
from utils.logger import get_logger

log = get_logger("technical_scoring")


# SUB-SCORERS


def _score_trend(df: pd.DataFrame) -> pd.Series:
    """Score trend direction: +1 = strong uptrend, -1 = strong downtrend."""
    scores = pd.DataFrame(index=df.index)
    close = df["close"]

    # MA alignment: each EMA above longer EMA is bullish
    for p in INDICATORS["EMA_PERIODS"]:
        ema_s = ema(close, p)
        scores[f"ema_{p}_vs_close"] = np.where(close > ema_s, 1.0, -1.0)

    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e55 = ema(close, 55)
    scores["ema_9_21"] = np.where(e9 > e21, 1.0, -1.0)
    scores["ema_21_55"] = np.where(e21 > e55, 1.0, -1.0)

    # Ichimoku
    ichi = ichimoku(df)
    if "ichimoku_tenkan" in ichi.columns and "ichimoku_kijun" in ichi.columns:
        scores["ichi_tk"] = np.where(
            ichi["ichimoku_tenkan"] > ichi["ichimoku_kijun"], 1.0, -1.0
        )
        scores["ichi_price_cloud"] = np.where(
            close > ichi["ichimoku_senkou_a"].fillna(0), 1.0, -1.0
        )

    # ADX trend direction
    adx_df = adx(df)
    if "plus_di" in adx_df.columns:
        di_signal = np.where(
            adx_df["plus_di"] > adx_df["minus_di"], 1.0, -1.0
        )
        adx_strength = (adx_df["adx"].fillna(0) / 50).clip(0, 1)
        scores["adx_di"] = di_signal * adx_strength

    # Parabolic SAR
    psar = parabolic_sar(df)
    scores["psar"] = np.where(close > psar, 1.0, -1.0)

    # SuperTrend
    st = supertrend(df)
    if "supertrend_dir" in st.columns:
        scores["supertrend"] = st["supertrend_dir"].fillna(0)

    # Linear Regression Channel
    lrc = linear_regression_channel(df)
    if "lrc_mid" in lrc.columns:
        scores["lrc"] = np.where(close > lrc["lrc_mid"], 1.0, -1.0)

    # MACD histogram direction
    macd_df = macd(close)
    if "macd_hist" in macd_df.columns:
        scores["macd_hist_sign"] = np.sign(macd_df["macd_hist"]).fillna(0)
        scores["macd_line_sign"] = np.sign(macd_df["macd"]).fillna(0)

    return scores.mean(axis=1).clip(-1, 1).rename("trend_score")


def _score_momentum(df: pd.DataFrame) -> pd.Series:
    """Score momentum strength and direction."""
    scores = pd.DataFrame(index=df.index)
    close = df["close"]

    # RSI: 50 is neutral, normalize to [-1, +1]
    rsi_val = rsi(close)
    scores["rsi"] = ((rsi_val - 50) / 50).clip(-1, 1)

    # RSI divergence bonus
    rsi_div = detect_divergence(close, rsi_val)
    if "div_reg_bull" in rsi_div.columns:
        scores["rsi_div_bull"] = rsi_div["div_reg_bull"].astype(float) * 0.5
        scores["rsi_div_bear"] = -rsi_div["div_reg_bear"].astype(float) * 0.5

    # Stochastic: normalize %K to [-1, +1]
    stoch_df = stochastic(df)
    if "stoch_k" in stoch_df.columns:
        scores["stoch"] = ((stoch_df["stoch_k"] - 50) / 50).clip(-1, 1)

    # CCI: normalize, clamped
    cci_val = cci(df)
    scores["cci"] = (cci_val / 200).clip(-1, 1)

    # Williams %R: normalize from [-100, 0] to [-1, +1]
    wr = williams_r(df)
    scores["williams_r"] = ((wr + 50) / 50).clip(-1, 1)

    # ROC
    roc_val = roc(close)
    scores["roc"] = np.tanh(roc_val / 5)

    # Awesome Oscillator
    ao = awesome_oscillator(df)
    if ao is not None:
        scores["ao"] = np.tanh(ao / (ao.abs().rolling(20).mean().replace(0, np.nan)))

    # Momentum
    mom = momentum(close)
    scores["mom"] = np.tanh(mom / close.rolling(20).std().replace(0, np.nan))

    # Qstick
    scores["qstick"] = np.tanh(qstick(df) / close.rolling(20).std().replace(0, np.nan))

    return scores.mean(axis=1).clip(-1, 1).rename("momentum_score")


def _score_volatility(df: pd.DataFrame) -> pd.Series:
    """
    Score volatility context.
    High volatility in expanding BB = momentum potential.
    Squeeze = coiling energy (neutral until breakout).
    """
    scores = pd.DataFrame(index=df.index)
    close = df["close"]

    bb = bollinger_bands(close)
    if "bb_pct_b" in bb.columns:
        # %B: 0 = at lower band, 1 = at upper band; center at 0.5
        scores["bb_pct_b"] = ((bb["bb_pct_b"] - 0.5) * 2).clip(-1, 1)
        # Squeeze: zero out signal when squeeze active (ambiguous)
        squeeze_mask = bb["bb_squeeze"].fillna(0).astype(bool)
        scores.loc[squeeze_mask, "bb_pct_b"] = 0.0

    kc = keltner_channels(df)
    if "kc_middle" in kc.columns:
        kc_range = (kc["kc_upper"] - kc["kc_lower"]).replace(0, np.nan)
        scores["kc_pos"] = ((close - kc["kc_middle"]) / (kc_range / 2)).clip(-1, 1)

    dc = donchian_channels(df)
    if "dc_middle" in dc.columns:
        dc_range = (dc["dc_upper"] - dc["dc_lower"]).replace(0, np.nan)
        scores["dc_pos"] = ((close - dc["dc_middle"]) / (dc_range / 2)).clip(-1, 1)

    # Historical volatility percentile (low vol → less conviction → reduce weight)
    hv = historical_volatility(close)
    hv_pct = hv.rank(pct=True)
    # Not a directional signal; used for weighting elsewhere

    return scores.mean(axis=1).clip(-1, 1).rename("volatility_score")


def _score_volume(df: pd.DataFrame) -> pd.Series:
    """Score volume-based signals."""
    scores = pd.DataFrame(index=df.index)
    close = df["close"]

    # OBV slope: rising OBV = bullish
    obv_s = obv(df)
    obv_slope = obv_s.diff(5)
    scores["obv"] = np.tanh(obv_slope / (obv_slope.abs().rolling(20).mean() + 1e-10))

    # VWAP: price above VWAP is bullish
    vwap_s = vwap(df)
    vwap_diff_pct = (close - vwap_s) / vwap_s.replace(0, np.nan)
    scores["vwap"] = np.tanh(vwap_diff_pct * 10)

    # MFI: like RSI but volume-weighted
    mfi_s = mfi(df)
    scores["mfi"] = ((mfi_s - 50) / 50).clip(-1, 1)

    # CMF: positive = accumulation, negative = distribution
    cmf_s = chaikin_money_flow(df)
    scores["cmf"] = cmf_s.clip(-1, 1)

    # Accumulation/Distribution slope
    ad_s = accumulation_distribution(df)
    ad_slope = ad_s.diff(5)
    scores["ad_line"] = np.tanh(ad_slope / (ad_slope.abs().rolling(20).mean() + 1e-10))

    # Volume oscillator: positive = above-average volume on moves
    vol_osc = volume_oscillator(df)
    direction = np.sign(close.diff())
    scores["vol_osc"] = np.tanh(vol_osc / 10) * direction

    return scores.mean(axis=1).clip(-1, 1).rename("volume_score")


def _score_support_resistance(df: pd.DataFrame) -> pd.Series:
    """
    Score proximity to support/resistance.
    Being near support = bullish, near resistance = bearish.
    """
    close = df["close"]
    piv = pivot_points(df)
    scores = pd.DataFrame(index=df.index)

    if "pivot" in piv.columns:
        for level, direction in [("r1", -1), ("r2", -1), ("r3", -1),
                                   ("s1", 1), ("s2", 1), ("s3", 1)]:
            if level in piv.columns:
                dist_pct = (close - piv[level]) / close.replace(0, np.nan)
                # If price is very close to level (within 0.3%), assign signal
                near = dist_pct.abs() < 0.003
                scores[f"pivot_{level}"] = np.where(near, direction * 0.5, 0.0)

        # Price vs pivot: above = bullish, below = bearish
        scores["vs_pivot"] = np.where(close > piv["pivot"], 0.3, -0.3)

    return scores.mean(axis=1).clip(-1, 1).rename("sr_score")

# MULTI-TIMEFRAME WRAPPER

def score_single_timeframe(df: pd.DataFrame) -> dict[str, float]:
    """
    Compute all sub-scores for a single OHLCV DataFrame.
    Returns a dict of latest values for each sub-score.
    """
    if df is None or df.empty or len(df) < 50:
        log.warning("Insufficient data for technical scoring")
        return {
            "trend_score": 0.0, "momentum_score": 0.0,
            "volatility_score": 0.0, "volume_score": 0.0,
            "pattern_score": 0.0, "sr_score": 0.0,
            "technical_score": 0.0,
        }

    try:
        trend = _score_trend(df)
        momentum_s = _score_momentum(df)
        volatility = _score_volatility(df)
        volume = _score_volume(df)
        patterns = pattern_score(df)
        sr = _score_support_resistance(df)

        # Weighted combination
        weights = {
            "trend": 0.30,
            "momentum": 0.25,
            "volatility": 0.15,
            "volume": 0.20,
            "patterns": 0.05,
            "sr": 0.05,
        }

        combined = (
            trend.iloc[-1] * weights["trend"] +
            momentum_s.iloc[-1] * weights["momentum"] +
            volatility.iloc[-1] * weights["volatility"] +
            volume.iloc[-1] * weights["volume"] +
            patterns.iloc[-1] * weights["patterns"] +
            sr.iloc[-1] * weights["sr"]
        )

        return {
            "trend_score": float(clamp(trend.iloc[-1])),
            "momentum_score": float(clamp(momentum_s.iloc[-1])),
            "volatility_score": float(clamp(volatility.iloc[-1])),
            "volume_score": float(clamp(volume.iloc[-1])),
            "pattern_score": float(clamp(patterns.iloc[-1])),
            "sr_score": float(clamp(sr.iloc[-1])),
            "technical_score": float(clamp(combined)),
        }

    except Exception as e:
        log.error(f"Technical scoring error: {e}", exc_info=True)
        return {k: 0.0 for k in [
            "trend_score", "momentum_score", "volatility_score",
            "volume_score", "pattern_score", "sr_score", "technical_score"
        ]}


def score_multi_timeframe(
    ohlcv_by_tf: dict[str, pd.DataFrame],
    tf_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Aggregate technical scores across multiple timeframes.

    Args:
        ohlcv_by_tf: dict of {timeframe: DataFrame}
        tf_weights: optional custom weights per timeframe

    Returns:
        dict with per-timeframe scores and final weighted score
    """
    default_weights = {
        "15m": 0.10,
        "1h":  0.30,
        "4h":  0.35,
        "1d":  0.25,
    }
    weights = tf_weights or default_weights

    scores_by_tf: dict[str, dict] = {}
    for tf, df in ohlcv_by_tf.items():
        scores_by_tf[tf] = score_single_timeframe(df)

    # Compute weighted final technical score
    total_w = 0.0
    weighted_score = 0.0
    for tf, scores in scores_by_tf.items():
        w = weights.get(tf, 0.15)
        weighted_score += scores["technical_score"] * w
        total_w += w

    final_score = clamp(safe_divide(weighted_score, total_w)) if total_w > 0 else 0.0

    result: dict[str, float] = {"technical_score": final_score}
    for tf, scores in scores_by_tf.items():
        for k, v in scores.items():
            result[f"{tf}_{k}"] = v

    return result
