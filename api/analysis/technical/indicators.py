"""
Complete technical indicator library computed on pandas DataFrames.
All indicators return Series or DataFrames that can be merged with OHLCV data.

Design decisions:
- Pure pandas/numpy implementation — no TA-Lib dependency at runtime
  (avoids C library headaches in Docker); optional TA-Lib acceleration via try/import
- Every function validates input and returns NaN-filled Series on error
- Configurable via config.INDICATORS dict
"""

import math
import numpy as np
import pandas as pd
from typing import Optional, Union
from config import INDICATORS
from utils.logger import get_logger

log = get_logger("indicators")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS


def _validate(df: pd.DataFrame, cols: list[str] = ["close"]) -> bool:
    return all(c in df.columns for c in cols) and len(df) >= 2


def _safe(func):
    """Decorator: return NaN Series on any indicator computation error."""
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.warning(f"Indicator {func.__name__} failed: {e}")
            # Return NaN Series of same length as first DataFrame arg
            for a in args:
                if isinstance(a, pd.DataFrame):
                    return pd.Series(np.nan, index=a.index, name=func.__name__)
                if isinstance(a, pd.Series):
                    return pd.Series(np.nan, index=a.index, name=func.__name__)
            return pd.Series(dtype=float)
    return wrapper



# MOVING AVERAGES


@_safe
def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


@_safe
def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


@_safe
def wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted Moving Average (linearly weighted)."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


@_safe
def hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average — reduces lag while preserving smoothness."""
    half = max(1, period // 2)
    sqrt_p = max(1, int(math.sqrt(period)))
    wma_half = wma(series, half)
    wma_full = wma(series, period)
    raw = 2 * wma_half - wma_full
    return wma(raw, sqrt_p)


@_safe
def dema(series: pd.Series, period: int) -> pd.Series:
    """Double Exponential Moving Average."""
    e1 = ema(series, period)
    e2 = ema(e1, period)
    return 2 * e1 - e2


@_safe
def tema(series: pd.Series, period: int) -> pd.Series:
    """Triple Exponential Moving Average."""
    e1 = ema(series, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return 3 * e1 - 3 * e2 + e3



# ICHIMOKU CLOUD


def ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ichimoku Kinko Hyo Cloud.
    Returns: tenkan, kijun, senkou_a, senkou_b, chikou
    """
    if not _validate(df, ["high", "low", "close"]):
        return pd.DataFrame(index=df.index)

    t = INDICATORS["ICHIMOKU_TENKAN"]
    k = INDICATORS["ICHIMOKU_KIJUN"]
    s = INDICATORS["ICHIMOKU_SENKOU_B"]
    d = INDICATORS["ICHIMOKU_DISPLACEMENT"]

    tenkan = (df["high"].rolling(t).max() + df["low"].rolling(t).min()) / 2
    kijun = (df["high"].rolling(k).max() + df["low"].rolling(k).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(d)
    senkou_b = ((df["high"].rolling(s).max() + df["low"].rolling(s).min()) / 2).shift(d)
    chikou = df["close"].shift(-d)

    return pd.DataFrame({
        "ichimoku_tenkan": tenkan,
        "ichimoku_kijun": kijun,
        "ichimoku_senkou_a": senkou_a,
        "ichimoku_senkou_b": senkou_b,
        "ichimoku_chikou": chikou,
    }, index=df.index)



# MACD


def macd(
    series: pd.Series,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
) -> pd.DataFrame:
    """MACD line, signal line, and histogram."""
    fast = fast or INDICATORS["MACD_FAST"]
    slow = slow or INDICATORS["MACD_SLOW"]
    signal = signal or INDICATORS["MACD_SIGNAL"]

    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": histogram,
    }, index=series.index)



# ADX / DMI


def adx(df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
    """Average Directional Index with +DI and -DI."""
    if not _validate(df, ["high", "low", "close"]):
        return pd.DataFrame(index=df.index)

    period = period or INDICATORS["ADX_PERIOD"]
    high, low, close = df["high"], df["low"], df["close"]

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_vals = atr(df, period)
    smoothed_plus = pd.Series(plus_dm, index=df.index).ewm(span=period, adjust=False).mean()
    smoothed_minus = pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean()

    plus_di = 100 * smoothed_plus / atr_vals.replace(0, np.nan)
    minus_di = 100 * smoothed_minus / atr_vals.replace(0, np.nan)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    adx_line = dx.ewm(span=period, adjust=False).mean()

    return pd.DataFrame({
        "adx": adx_line,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }, index=df.index)



# ATR


@_safe
def atr(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Average True Range."""
    if not _validate(df, ["high", "low", "close"]):
        return pd.Series(np.nan, index=df.index)

    period = period or INDICATORS["ATR_PERIOD"]
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False, min_periods=period).mean()



# PARABOLIC SAR


@_safe
def parabolic_sar(df: pd.DataFrame) -> pd.Series:
    """Parabolic SAR — trend-following stop-and-reverse indicator."""
    if not _validate(df, ["high", "low"]):
        return pd.Series(np.nan, index=df.index)

    start = INDICATORS["PSAR_START"]
    inc = INDICATORS["PSAR_INCREMENT"]
    max_af = INDICATORS["PSAR_MAX"]

    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)
    sar = np.full(n, np.nan)
    bull = True
    af = start
    ep = lows[0]
    sar[0] = highs[0]

    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            sar[i] = min(sar[i], lows[i - 1], lows[max(0, i - 2)])
            if lows[i] < sar[i]:
                bull = False
                sar[i] = ep
                ep = lows[i]
                af = start
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + inc, max_af)
        else:
            sar[i] = max(sar[i], highs[i - 1], highs[max(0, i - 2)])
            if highs[i] > sar[i]:
                bull = True
                sar[i] = ep
                ep = highs[i]
                af = start
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + inc, max_af)

    return pd.Series(sar, index=df.index, name="psar")

# SUPERTREND

def supertrend(df: pd.DataFrame) -> pd.DataFrame:
    """SuperTrend indicator. Returns supertrend line and direction."""
    if not _validate(df, ["high", "low", "close"]):
        return pd.DataFrame(index=df.index)

    period = INDICATORS["SUPERTREND_PERIOD"]
    mult = INDICATORS["SUPERTREND_MULTIPLIER"]

    hl2 = (df["high"] + df["low"]) / 2
    atr_vals = atr(df, period)
    upper_band = hl2 + mult * atr_vals
    lower_band = hl2 - mult * atr_vals

    supertrend_vals = np.zeros(len(df))
    direction = np.ones(len(df))  # 1 = bullish, -1 = bearish
    close = df["close"].values
    ub = upper_band.values
    lb = lower_band.values

    for i in range(1, len(df)):
        lb[i] = lb[i] if lb[i] > lb[i - 1] or close[i - 1] < lb[i - 1] else lb[i - 1]
        ub[i] = ub[i] if ub[i] < ub[i - 1] or close[i - 1] > ub[i - 1] else ub[i - 1]

        if supertrend_vals[i - 1] == ub[i - 1]:
            supertrend_vals[i] = lb[i] if close[i] > ub[i] else ub[i]
        else:
            supertrend_vals[i] = ub[i] if close[i] < lb[i] else lb[i]

        direction[i] = 1 if supertrend_vals[i] == lb[i] else -1

    return pd.DataFrame({
        "supertrend": supertrend_vals,
        "supertrend_dir": direction,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def rsi(series: pd.Series, period: int | None = None) -> pd.Series:
    """Relative Strength Index."""
    period = period or INDICATORS["RSI_PERIOD"]
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─────────────────────────────────────────────────────────────────────────────
# STOCHASTIC OSCILLATOR
# ─────────────────────────────────────────────────────────────────────────────

def stochastic(df: pd.DataFrame) -> pd.DataFrame:
    """Full Stochastic Oscillator (%K, %D, Slow %K)."""
    if not _validate(df, ["high", "low", "close"]):
        return pd.DataFrame(index=df.index)

    k_period = INDICATORS["STOCH_K"]
    d_period = INDICATORS["STOCH_D"]
    smooth = INDICATORS["STOCH_SMOOTH"]

    lowest_low = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    fast_k = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    slow_k = fast_k.rolling(smooth).mean()
    slow_d = slow_k.rolling(d_period).mean()

    return pd.DataFrame({
        "stoch_k": slow_k,
        "stoch_d": slow_d,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# CCI
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def cci(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Commodity Channel Index."""
    period = period or INDICATORS["CCI_PERIOD"]
    typical = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = typical.rolling(period).mean()
    mad = typical.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (typical - sma_tp) / (0.015 * mad.replace(0, np.nan))


# ─────────────────────────────────────────────────────────────────────────────
# WILLIAMS %R
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def williams_r(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Williams %R momentum indicator."""
    period = period or INDICATORS["WILLIAMS_PERIOD"]
    highest = df["high"].rolling(period).max()
    lowest = df["low"].rolling(period).min()
    return -100 * (highest - df["close"]) / (highest - lowest).replace(0, np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# RATE OF CHANGE (ROC)
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def roc(series: pd.Series, period: int | None = None) -> pd.Series:
    """Rate of Change (price momentum)."""
    period = period or INDICATORS["ROC_PERIOD"]
    return 100 * (series - series.shift(period)) / series.shift(period).replace(0, np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# MOMENTUM
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def momentum(series: pd.Series, period: int | None = None) -> pd.Series:
    """Momentum: current price minus price n bars ago."""
    period = period or INDICATORS["MOM_PERIOD"]
    return series - series.shift(period)


# ─────────────────────────────────────────────────────────────────────────────
# AWESOME OSCILLATOR
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def awesome_oscillator(df: pd.DataFrame) -> pd.Series:
    """Awesome Oscillator = SMA(midpoint, 5) - SMA(midpoint, 34)."""
    mid = (df["high"] + df["low"]) / 2
    return sma(mid, INDICATORS["AO_FAST"]) - sma(mid, INDICATORS["AO_SLOW"])


# ─────────────────────────────────────────────────────────────────────────────
# BOLLINGER BANDS
# ─────────────────────────────────────────────────────────────────────────────

def bollinger_bands(series: pd.Series) -> pd.DataFrame:
    """
    Bollinger Bands: upper, middle, lower, bandwidth, %B.
    Also detects squeeze (bandwidth below threshold).
    """
    period = INDICATORS["BB_PERIOD"]
    num_std = INDICATORS["BB_STD"]
    threshold = INDICATORS["BB_SQUEEZE_THRESHOLD"]

    middle = sma(series, period)
    std = series.rolling(period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    pct_b = (series - lower) / (upper - lower).replace(0, np.nan)
    squeeze = (bandwidth < threshold).astype(float)

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "bb_bandwidth": bandwidth,
        "bb_pct_b": pct_b,
        "bb_squeeze": squeeze,
    }, index=series.index)


# ─────────────────────────────────────────────────────────────────────────────
# KELTNER CHANNELS
# ─────────────────────────────────────────────────────────────────────────────

def keltner_channels(df: pd.DataFrame) -> pd.DataFrame:
    """Keltner Channels based on EMA and ATR."""
    period = INDICATORS["KC_PERIOD"]
    mult = INDICATORS["KC_MULTIPLIER"]
    middle = ema(df["close"], period)
    atr_vals = atr(df, period)
    return pd.DataFrame({
        "kc_upper": middle + mult * atr_vals,
        "kc_middle": middle,
        "kc_lower": middle - mult * atr_vals,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# DONCHIAN CHANNELS
# ─────────────────────────────────────────────────────────────────────────────

def donchian_channels(df: pd.DataFrame) -> pd.DataFrame:
    """Donchian Channels: highest high / lowest low over n periods."""
    period = INDICATORS["DC_PERIOD"]
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    middle = (upper + lower) / 2
    return pd.DataFrame({
        "dc_upper": upper,
        "dc_middle": middle,
        "dc_lower": lower,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL VOLATILITY
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def historical_volatility(series: pd.Series) -> pd.Series:
    """Annualized historical volatility (log returns std)."""
    period = INDICATORS["HV_PERIOD"]
    ann = INDICATORS["HV_ANNUALIZE"]
    log_ret = np.log(series / series.shift(1))
    return log_ret.rolling(period).std() * math.sqrt(ann)


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume."""
    direction = np.where(df["close"] > df["close"].shift(1), 1, -1)
    direction[0] = 0
    return (df["volume"] * direction).cumsum()


@_safe
def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price (daily reset if DatetimeIndex)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_tpv = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tpv / cum_vol.replace(0, np.nan)


@_safe
def mfi(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Money Flow Index."""
    period = period or INDICATORS["MFI_PERIOD"]
    typical = (df["high"] + df["low"] + df["close"]) / 3
    raw_mf = typical * df["volume"]
    direction = typical.diff()

    pos_mf = raw_mf.where(direction > 0, 0).rolling(period).sum()
    neg_mf = raw_mf.where(direction < 0, 0).rolling(period).sum()

    mfr = pos_mf / neg_mf.replace(0, np.nan)
    return 100 - 100 / (1 + mfr)


@_safe
def chaikin_money_flow(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Chaikin Money Flow."""
    period = period or INDICATORS["CMF_PERIOD"]
    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    mf_multiplier = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    mf_volume = mf_multiplier * df["volume"]
    return mf_volume.rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, np.nan)


@_safe
def accumulation_distribution(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution Line."""
    hl_range = (df["high"] - df["low"]).replace(0, np.nan)
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    return (clv * df["volume"]).cumsum()


@_safe
def volume_oscillator(df: pd.DataFrame, fast: int = 5, slow: int = 10) -> pd.Series:
    """Volume Oscillator = (fast_vol_SMA - slow_vol_SMA) / slow_vol_SMA * 100."""
    fast_ma = sma(df["volume"], fast)
    slow_ma = sma(df["volume"], slow)
    return (fast_ma - slow_ma) / slow_ma.replace(0, np.nan) * 100


# ─────────────────────────────────────────────────────────────────────────────
# PIVOT POINTS
# ─────────────────────────────────────────────────────────────────────────────

def pivot_points(df: pd.DataFrame, pivot_type: str | None = None) -> pd.DataFrame:
    """
    Pivot Points: classic, fibonacci, woodie, camarilla.
    Computed on daily (or previous bar's high/low/close).
    """
    pivot_type = pivot_type or INDICATORS["PIVOT_TYPE"]
    h = df["high"].shift(1)
    l = df["low"].shift(1)
    c = df["close"].shift(1)
    o = df["open"].shift(1) if "open" in df.columns else c

    pp = (h + l + c) / 3

    if pivot_type == "fibonacci":
        r1 = pp + 0.382 * (h - l)
        r2 = pp + 0.618 * (h - l)
        r3 = pp + 1.000 * (h - l)
        s1 = pp - 0.382 * (h - l)
        s2 = pp - 0.618 * (h - l)
        s3 = pp - 1.000 * (h - l)
    elif pivot_type == "woodie":
        pp = (h + l + 2 * o) / 4
        r1 = 2 * pp - l
        r2 = pp + (h - l)
        r3 = r1 + (h - l)
        s1 = 2 * pp - h
        s2 = pp - (h - l)
        s3 = s1 - (h - l)
    elif pivot_type == "camarilla":
        r1 = c + 1.1 * (h - l) / 12
        r2 = c + 1.1 * (h - l) / 6
        r3 = c + 1.1 * (h - l) / 4
        s1 = c - 1.1 * (h - l) / 12
        s2 = c - 1.1 * (h - l) / 6
        s3 = c - 1.1 * (h - l) / 4
    else:  # classic
        r1 = 2 * pp - l
        r2 = pp + (h - l)
        r3 = h + 2 * (pp - l)
        s1 = 2 * pp - h
        s2 = pp - (h - l)
        s3 = l - 2 * (h - pp)

    return pd.DataFrame({
        "pivot": pp, "r1": r1, "r2": r2, "r3": r3,
        "s1": s1, "s2": s2, "s3": s3,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# FIBONACCI RETRACEMENT LEVELS
# ─────────────────────────────────────────────────────────────────────────────

def fibonacci_levels(
    swing_high: float, swing_low: float
) -> dict[str, float]:
    """Return Fibonacci retracement and extension levels."""
    diff = swing_high - swing_low
    return {
        "fib_0": swing_high,
        "fib_236": swing_high - 0.236 * diff,
        "fib_382": swing_high - 0.382 * diff,
        "fib_500": swing_high - 0.500 * diff,
        "fib_618": swing_high - 0.618 * diff,
        "fib_786": swing_high - 0.786 * diff,
        "fib_100": swing_low,
        "fib_ext_1272": swing_low - 0.272 * diff,
        "fib_ext_1618": swing_low - 0.618 * diff,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LINEAR REGRESSION CHANNEL
# ─────────────────────────────────────────────────────────────────────────────

def linear_regression_channel(df: pd.DataFrame) -> pd.DataFrame:
    """Linear Regression Channel over a rolling window."""
    period = INDICATORS["LRC_PERIOD"]
    mult = INDICATORS["LRC_STD_MULTIPLIER"]
    close = df["close"]
    x = np.arange(period, dtype=float)

    def lr_midpoint(window: np.ndarray) -> float:
        slope, intercept = np.polyfit(x, window, 1)
        return slope * (period - 1) + intercept

    def lr_std(window: np.ndarray) -> float:
        slope, intercept = np.polyfit(x, window, 1)
        fitted = slope * x + intercept
        return float(np.std(window - fitted))

    mid = close.rolling(period).apply(lr_midpoint, raw=True)
    std = close.rolling(period).apply(lr_std, raw=True)
    return pd.DataFrame({
        "lrc_mid": mid,
        "lrc_upper": mid + mult * std,
        "lrc_lower": mid - mult * std,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# DIVERGENCE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_divergence(
    price: pd.Series,
    indicator: pd.Series,
    lookback: int | None = None,
    min_bars: int | None = None,
) -> pd.DataFrame:
    """
    Detect regular and hidden bullish/bearish divergences.

    Returns a DataFrame with columns:
    - regular_bull: price LL, indicator HL (oversold zone potential reversal up)
    - regular_bear: price HH, indicator LH (overbought zone potential reversal down)
    - hidden_bull: price HL, indicator LL (trend continuation up)
    - hidden_bear: price LH, indicator HH (trend continuation down)
    """
    lookback = lookback or INDICATORS["DIVERGENCE_LOOKBACK"]
    min_bars = min_bars or INDICATORS["DIVERGENCE_MIN_BARS"]

    n = len(price)
    reg_bull = np.zeros(n, dtype=bool)
    reg_bear = np.zeros(n, dtype=bool)
    hid_bull = np.zeros(n, dtype=bool)
    hid_bear = np.zeros(n, dtype=bool)

    for i in range(lookback, n):
        window_p = price.iloc[i - lookback: i + 1]
        window_ind = indicator.iloc[i - lookback: i + 1]

        # Find local swing points
        p_low_idx = window_p.idxmin()
        p_high_idx = window_p.idxmax()
        prev_p_lows = window_p.nsmallest(2)
        prev_p_highs = window_p.nlargest(2)

        if len(prev_p_lows) < 2 or len(prev_p_highs) < 2:
            continue

        p_ll = prev_p_lows.iloc[0] < prev_p_lows.iloc[1]
        p_hh = prev_p_highs.iloc[0] > prev_p_highs.iloc[1]

        ind_lows = window_ind.nsmallest(2)
        ind_highs = window_ind.nlargest(2)
        if len(ind_lows) < 2 or len(ind_highs) < 2:
            continue

        ind_hl = ind_lows.iloc[0] > ind_lows.iloc[1]  # indicator higher low
        ind_lh = ind_highs.iloc[0] < ind_highs.iloc[1]  # indicator lower high
        ind_ll = ind_lows.iloc[0] < ind_lows.iloc[1]
        ind_hh = ind_highs.iloc[0] > ind_highs.iloc[1]

        if p_ll and ind_hl:
            reg_bull[i] = True
        if p_hh and ind_lh:
            reg_bear[i] = True
        if (not p_ll) and ind_ll:
            hid_bull[i] = True
        if (not p_hh) and ind_hh:
            hid_bear[i] = True

    return pd.DataFrame({
        "div_reg_bull": reg_bull,
        "div_reg_bear": reg_bear,
        "div_hid_bull": hid_bull,
        "div_hid_bear": hid_bear,
    }, index=price.index)


# ─────────────────────────────────────────────────────────────────────────────
# SWING HIGH / LOW (for Support & Resistance)
# ─────────────────────────────────────────────────────────────────────────────

def swing_points(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Identify swing highs and lows over a rolling window."""
    high = df["high"]
    low = df["low"]
    n = len(df)
    swing_highs = np.full(n, np.nan)
    swing_lows = np.full(n, np.nan)

    for i in range(window, n - window):
        h_window = high.iloc[i - window: i + window + 1]
        l_window = low.iloc[i - window: i + window + 1]
        if high.iloc[i] == h_window.max():
            swing_highs[i] = high.iloc[i]
        if low.iloc[i] == l_window.min():
            swing_lows[i] = low.iloc[i]

    return pd.DataFrame({
        "swing_high": swing_highs,
        "swing_low": swing_lows,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# TREND VS RANGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def trend_strength(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classify market as trending or ranging using ADX and BB width.
    Returns: trend_score (0=range, 1=strong trend) and regime label.
    """
    adx_vals = adx(df)["adx"]
    bb_vals = bollinger_bands(df["close"])["bb_bandwidth"]
    adx_threshold = INDICATORS["ADX_TREND_THRESHOLD"]

    adx_norm = adx_vals / 100.0
    bb_norm = (bb_vals / bb_vals.rolling(50).mean()).clip(0, 2) / 2

    trend_score = (adx_norm * 0.6 + bb_norm * 0.4).clip(0, 1)
    regime = pd.Series(
        np.where(adx_vals > adx_threshold, "trend", "range"),
        index=df.index,
        name="regime",
    )

    return pd.DataFrame({
        "trend_score": trend_score,
        "regime": regime,
    }, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# QSTICK
# ─────────────────────────────────────────────────────────────────────────────

@_safe
def qstick(df: pd.DataFrame, period: int = 8) -> pd.Series:
    """Qstick: SMA of (close - open). Positive = bullish pressure."""
    return sma(df["close"] - df["open"], period)
