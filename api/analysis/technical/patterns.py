"""

Candlestick pattern recognition and basic chart pattern detection.
All functions operate on OHLCV DataFrames and return boolean or scored Series.
"""

import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger("patterns")


# HELPERS


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()

def _upper_shadow(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df[["close", "open"]].max(axis=1)

def _lower_shadow(df: pd.DataFrame) -> pd.Series:
    return df[["close", "open"]].min(axis=1) - df["low"]

def _range(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).replace(0, np.nan)

def _is_bullish(df: pd.DataFrame) -> pd.Series:
    return df["close"] > df["open"]

def _is_bearish(df: pd.DataFrame) -> pd.Series:
    return df["close"] < df["open"]

def _avg_body(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _body(df).rolling(period).mean()



# SINGLE-BAR CANDLESTICK PATTERNS


def doji(df: pd.DataFrame, threshold: float = 0.05) -> pd.Series:
    """Doji: body is very small relative to the candle range."""
    body_ratio = _body(df) / _range(df).replace(0, np.nan)
    return (body_ratio < threshold).rename("doji")


def hammer(df: pd.DataFrame) -> pd.Series:
    """
    Hammer (bullish reversal at bottom):
    - Small body in upper third
    - Lower shadow >= 2x body
    - Little or no upper shadow
    """
    body = _body(df)
    lower = _lower_shadow(df)
    upper = _upper_shadow(df)
    rng = _range(df)
    avg_b = _avg_body(df)

    cond = (
        (body < avg_b * 0.6) &
        (lower >= 2 * body) &
        (upper <= body * 0.3) &
        (rng > 0)
    )
    return cond.rename("hammer")


def shooting_star(df: pd.DataFrame) -> pd.Series:
    """
    Shooting Star (bearish reversal at top):
    - Small body in lower third
    - Upper shadow >= 2x body
    - Little or no lower shadow
    """
    body = _body(df)
    lower = _lower_shadow(df)
    upper = _upper_shadow(df)
    avg_b = _avg_body(df)

    cond = (
        (body < avg_b * 0.6) &
        (upper >= 2 * body) &
        (lower <= body * 0.3)
    )
    return cond.rename("shooting_star")


def spinning_top(df: pd.DataFrame) -> pd.Series:
    """Spinning top: small body with shadows larger than body on both sides."""
    body = _body(df)
    lower = _lower_shadow(df)
    upper = _upper_shadow(df)
    avg_b = _avg_body(df)

    cond = (
        (body < avg_b * 0.5) &
        (upper > body) &
        (lower > body)
    )
    return cond.rename("spinning_top")


def marubozu(df: pd.DataFrame, shadow_threshold: float = 0.03) -> pd.Series:
    """
    Marubozu: very long body with almost no shadows.
    Returns: +1 for bullish marubozu, -1 for bearish, 0 otherwise.
    """
    body = _body(df)
    rng = _range(df)
    avg_b = _avg_body(df)
    upper = _upper_shadow(df)
    lower = _lower_shadow(df)

    full_body = body >= avg_b * 1.5
    no_shadows = (upper < rng * shadow_threshold) & (lower < rng * shadow_threshold)

    result = pd.Series(0, index=df.index, name="marubozu")
    result[full_body & no_shadows & _is_bullish(df)] = 1
    result[full_body & no_shadows & _is_bearish(df)] = -1
    return result



# TWO-BAR CANDLESTICK PATTERNS


def engulfing(df: pd.DataFrame) -> pd.Series:
    """
    Engulfing pattern.
    Returns: +1 for bullish engulfing, -1 for bearish engulfing, 0 otherwise.
    """
    prev_open = df["open"].shift(1)
    prev_close = df["close"].shift(1)
    curr_open = df["open"]
    curr_close = df["close"]

    bullish = (
        _is_bearish(df.shift(1)) &
        _is_bullish(df) &
        (curr_open < prev_close) &
        (curr_close > prev_open)
    )
    bearish = (
        _is_bullish(df.shift(1)) &
        _is_bearish(df) &
        (curr_open > prev_close) &
        (curr_close < prev_open)
    )

    result = pd.Series(0, index=df.index, name="engulfing")
    result[bullish] = 1
    result[bearish] = -1
    return result


def harami(df: pd.DataFrame) -> pd.Series:
    """
    Harami pattern (inside bar reversal).
    Returns: +1 bullish harami, -1 bearish harami, 0 otherwise.
    """
    prev_body_high = df[["open", "close"]].shift(1).max(axis=1)
    prev_body_low = df[["open", "close"]].shift(1).min(axis=1)
    curr_body_high = df[["open", "close"]].max(axis=1)
    curr_body_low = df[["open", "close"]].min(axis=1)

    inside = (curr_body_high < prev_body_high) & (curr_body_low > prev_body_low)
    avg_b = _avg_body(df)

    bullish = inside & _is_bearish(df.shift(1)) & _is_bullish(df) & (_body(df.shift(1)) > avg_b)
    bearish = inside & _is_bullish(df.shift(1)) & _is_bearish(df) & (_body(df.shift(1)) > avg_b)

    result = pd.Series(0, index=df.index, name="harami")
    result[bullish] = 1
    result[bearish] = -1
    return result


def piercing_line(df: pd.DataFrame) -> pd.Series:
    """
    Piercing Line (bullish) / Dark Cloud Cover (bearish).
    Returns: +1 / -1 / 0
    """
    prev_mid = (df["open"].shift(1) + df["close"].shift(1)) / 2
    avg_b = _avg_body(df)

    bullish = (
        _is_bearish(df.shift(1)) &
        _is_bullish(df) &
        (df["open"] < df["low"].shift(1)) &
        (df["close"] > prev_mid) &
        (df["close"] < df["open"].shift(1)) &
        (_body(df) > avg_b * 0.5)
    )
    bearish = (
        _is_bullish(df.shift(1)) &
        _is_bearish(df) &
        (df["open"] > df["high"].shift(1)) &
        (df["close"] < prev_mid) &
        (df["close"] > df["open"].shift(1)) &
        (_body(df) > avg_b * 0.5)
    )

    result = pd.Series(0, index=df.index, name="piercing_dark_cloud")
    result[bullish] = 1
    result[bearish] = -1
    return result


def tweezer(df: pd.DataFrame, tolerance: float = 0.001) -> pd.Series:
    """
    Tweezer Tops and Bottoms.
    Returns: +1 tweezer bottom (bullish), -1 tweezer top (bearish), 0 otherwise.
    """
    low_match = (df["low"] - df["low"].shift(1)).abs() / df["low"].shift(1) < tolerance
    high_match = (df["high"] - df["high"].shift(1)).abs() / df["high"].shift(1) < tolerance

    result = pd.Series(0, index=df.index, name="tweezer")
    result[low_match & _is_bearish(df.shift(1)) & _is_bullish(df)] = 1
    result[high_match & _is_bullish(df.shift(1)) & _is_bearish(df)] = -1
    return result



# THREE-BAR CANDLESTICK PATTERNS


def morning_evening_star(df: pd.DataFrame) -> pd.Series:
    """
    Morning Star (bullish) and Evening Star (bearish) reversal patterns.
    Returns: +1 morning star, -1 evening star, 0 otherwise.
    """
    avg_b = _avg_body(df)
    b1 = _body(df.shift(2))
    b2 = _body(df.shift(1))
    b3 = _body(df)

    morning = (
        _is_bearish(df.shift(2)) &
        (b1 > avg_b.shift(2)) &
        (b2 < avg_b.shift(1) * 0.5) &
        _is_bullish(df) &
        (b3 > avg_b * 0.5) &
        (df["close"] > (df["open"].shift(2) + df["close"].shift(2)) / 2)
    )
    evening = (
        _is_bullish(df.shift(2)) &
        (b1 > avg_b.shift(2)) &
        (b2 < avg_b.shift(1) * 0.5) &
        _is_bearish(df) &
        (b3 > avg_b * 0.5) &
        (df["close"] < (df["open"].shift(2) + df["close"].shift(2)) / 2)
    )

    result = pd.Series(0, index=df.index, name="morning_evening_star")
    result[morning] = 1
    result[evening] = -1
    return result


def three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    """Three consecutive bullish candles each closing higher."""
    avg_b = _avg_body(df)
    cond = (
        _is_bullish(df) &
        _is_bullish(df.shift(1)) &
        _is_bullish(df.shift(2)) &
        (df["close"] > df["close"].shift(1)) &
        (df["close"].shift(1) > df["close"].shift(2)) &
        (_body(df) > avg_b * 0.6) &
        (_body(df.shift(1)) > avg_b.shift(1) * 0.6)
    )
    return cond.astype(int).rename("three_white_soldiers")


def three_black_crows(df: pd.DataFrame) -> pd.Series:
    """Three consecutive bearish candles each closing lower."""
    avg_b = _avg_body(df)
    cond = (
        _is_bearish(df) &
        _is_bearish(df.shift(1)) &
        _is_bearish(df.shift(2)) &
        (df["close"] < df["close"].shift(1)) &
        (df["close"].shift(1) < df["close"].shift(2)) &
        (_body(df) > avg_b * 0.6) &
        (_body(df.shift(1)) > avg_b.shift(1) * 0.6)
    )
    return (-cond.astype(int)).rename("three_black_crows")



# CHART PATTERNS (basic, window-based detection)


def detect_double_top_bottom(
    df: pd.DataFrame,
    window: int = 40,
    tolerance: float = 0.02,
) -> pd.DataFrame:
    """
    Basic double top and double bottom detection.
    Returns boolean columns 'double_top' and 'double_bottom'.
    """
    n = len(df)
    double_top = np.zeros(n, dtype=bool)
    double_bottom = np.zeros(n, dtype=bool)

    for i in range(window * 2, n):
        seg = df.iloc[i - window * 2: i]
        highs = seg["high"]
        lows = seg["low"]

        h_max = highs.max()
        h_idxs = highs[highs > h_max * (1 - tolerance)].index
        if len(h_idxs) >= 2:
            first, last = h_idxs[0], h_idxs[-1]
            mid_lows = lows.loc[first:last]
            if len(mid_lows) > 0 and mid_lows.min() < h_max * (1 - 0.05):
                double_top[i] = True

        l_min = lows.min()
        l_idxs = lows[lows < l_min * (1 + tolerance)].index
        if len(l_idxs) >= 2:
            first, last = l_idxs[0], l_idxs[-1]
            mid_highs = highs.loc[first:last]
            if len(mid_highs) > 0 and mid_highs.max() > l_min * (1 + 0.05):
                double_bottom[i] = True

    return pd.DataFrame({
        "double_top": double_top,
        "double_bottom": double_bottom,
    }, index=df.index)


def detect_head_and_shoulders(
    df: pd.DataFrame, window: int = 60, tolerance: float = 0.03
) -> pd.Series:
    """
    Basic Head and Shoulders detection (bearish reversal).
    Returns +1 for inverse H&S (bullish), -1 for H&S (bearish), 0 otherwise.
    """
    n = len(df)
    result = np.zeros(n, dtype=int)

    for i in range(window, n):
        seg = df["high"].iloc[i - window: i]
        seg_low = df["low"].iloc[i - window: i]
        q = window // 4

        # Head and Shoulders: head higher than both shoulders
        left_shoulder = seg[:q].max()
        head = seg[q: 3 * q].max()
        right_shoulder = seg[3 * q:].max()
        neckline = seg_low.mean()

        if (
            head > left_shoulder * (1 + tolerance) and
            head > right_shoulder * (1 + tolerance) and
            abs(left_shoulder - right_shoulder) / left_shoulder < tolerance * 2
        ):
            result[i] = -1

        # Inverse H&S: head lower than both shoulders
        left_s_low = seg_low[:q].min()
        head_low = seg_low[q: 3 * q].min()
        right_s_low = seg_low[3 * q:].min()

        if (
            head_low < left_s_low * (1 - tolerance) and
            head_low < right_s_low * (1 - tolerance) and
            abs(left_s_low - right_s_low) / left_s_low < tolerance * 2
        ):
            result[i] = 1

    return pd.Series(result, index=df.index, name="head_shoulders")


def detect_triangle(df: pd.DataFrame, window: int = 30) -> pd.Series:
    """
    Detect ascending, descending, and symmetrical triangles.
    Returns: 'ascending', 'descending', 'symmetrical', or 'none'.
    """
    n = len(df)
    result = pd.Series("none", index=df.index, name="triangle")

    for i in range(window, n):
        seg_high = df["high"].iloc[i - window: i]
        seg_low = df["low"].iloc[i - window: i]

        x = np.arange(window, dtype=float)
        high_slope = np.polyfit(x, seg_high.values, 1)[0]
        low_slope = np.polyfit(x, seg_low.values, 1)[0]

        flat_thresh = seg_high.mean() * 0.0005

        if high_slope > flat_thresh and low_slope > flat_thresh and high_slope < low_slope:
            result.iloc[i] = "ascending"
        elif high_slope < -flat_thresh and low_slope < -flat_thresh and high_slope > low_slope:
            result.iloc[i] = "descending"
        elif high_slope < 0 and low_slope > 0:
            result.iloc[i] = "symmetrical"

    return result


def detect_flag_pennant(df: pd.DataFrame, pole_window: int = 10, flag_window: int = 15) -> pd.Series:
    """
    Detect bull/bear flags and pennants.
    Returns: 'bull_flag', 'bear_flag', 'pennant', or 'none'.
    """
    n = len(df)
    result = pd.Series("none", index=df.index, name="flag_pennant")

    for i in range(pole_window + flag_window, n):
        pole = df["close"].iloc[i - pole_window - flag_window: i - flag_window]
        flag_seg = df["close"].iloc[i - flag_window: i]

        pole_return = (pole.iloc[-1] - pole.iloc[0]) / pole.iloc[0]
        flag_return = (flag_seg.iloc[-1] - flag_seg.iloc[0]) / flag_seg.iloc[0]
        flag_vol = flag_seg.std() / flag_seg.mean()

        if pole_return > 0.05 and -0.05 < flag_return < 0 and flag_vol < 0.02:
            result.iloc[i] = "bull_flag"
        elif pole_return < -0.05 and 0 < flag_return < 0.05 and flag_vol < 0.02:
            result.iloc[i] = "bear_flag"
        elif abs(pole_return) > 0.05 and abs(flag_return) < 0.01 and flag_vol < 0.01:
            result.iloc[i] = "pennant"

    return result



# AGGREGATE PATTERN SCORE

def all_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all candlestick and chart patterns.
    Returns a DataFrame with one column per pattern.
    """
    results = pd.DataFrame(index=df.index)

    results["doji"] = doji(df).astype(float)
    results["hammer"] = hammer(df).astype(float)
    results["shooting_star"] = shooting_star(df).astype(float) * -1
    results["spinning_top"] = spinning_top(df).astype(float)
    results["marubozu"] = marubozu(df).astype(float)
    results["engulfing"] = engulfing(df).astype(float)
    results["harami"] = harami(df).astype(float)
    results["piercing_dark_cloud"] = piercing_line(df).astype(float)
    results["tweezer"] = tweezer(df).astype(float)
    results["morning_evening_star"] = morning_evening_star(df).astype(float)
    results["three_white_soldiers"] = three_white_soldiers(df).astype(float)
    results["three_black_crows"] = three_black_crows(df).astype(float)

    try:
        dt = detect_double_top_bottom(df)
        results["double_top"] = (-dt["double_top"].astype(float))
        results["double_bottom"] = dt["double_bottom"].astype(float)
    except Exception as e:
        log.warning(f"Double top/bottom detection failed: {e}")

    try:
        results["head_shoulders"] = detect_head_and_shoulders(df).astype(float)
    except Exception as e:
        log.warning(f"Head & shoulders detection failed: {e}")

    return results


def pattern_score(df: pd.DataFrame) -> pd.Series:
    """
    Aggregate all pattern signals into a single score in [-1, +1].
    Bullish patterns contribute positively, bearish negatively.
    """
    patterns = all_patterns(df)
    # Drop non-numeric columns
    numeric_patterns = patterns.select_dtypes(include=[np.number])
    if numeric_patterns.empty:
        return pd.Series(0.0, index=df.index, name="pattern_score")

    score = numeric_patterns.mean(axis=1).clip(-1, 1)
    return score.rename("pattern_score")
