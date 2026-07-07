"""
analysis/sentiment/sentiment_indicators.py

Market-structure sentiment indicators:
- Crypto Fear & Greed Index
- VIX (equity fear gauge)
- Put/Call Ratio
- Long/Short Ratio (crypto exchanges)
- COT Report (Commitment of Traders)
"""

import numpy as np
from typing import Optional
from config import SENTIMENT, FRED_API_KEY
from utils.api_utils import APISession, safe_float, extract_nested
from utils.helpers import clamp, normalize
from utils.logger import get_logger

log = get_logger("sentiment_indicators")


# ─────────────────────────────────────────────────────────────────────────────
# CRYPTO FEAR & GREED INDEX
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fear_greed_index() -> dict:
    """
    Fetch Crypto Fear & Greed Index from alternative.me API.
    Returns index value (0-100) and classification.
    """
    try:
        session = APISession("https://api.alternative.me", "newsapi")
        data = session.get("fng/", params={"limit": 1})
        if data and data.get("data"):
            entry = data["data"][0]
            value = safe_float(entry.get("value", 50))
            classification = entry.get("value_classification", "Neutral")
            return {
                "value": value,
                "classification": classification,
                "score": _normalize_fear_greed(value),
            }
    except Exception as e:
        log.warning(f"Fear & Greed index fetch failed: {e}")

    return {"value": 50.0, "classification": "Neutral", "score": 0.0}


def _normalize_fear_greed(value: float) -> float:
    """
    Normalize Fear & Greed (0-100) to sentiment score [-1, +1].
    Contrarian: extreme fear = bullish opportunity, extreme greed = caution.
    But trend: high greed can continue; use blend of contrarian + momentum.
    """
    overbought = SENTIMENT["fear_greed_overbought"]  # 80
    oversold = SENTIMENT["fear_greed_oversold"]       # 20

    if value >= overbought:
        # Extreme greed: slightly bearish (contrarian)
        return clamp(-(value - overbought) / (100 - overbought) * 0.5)
    elif value <= oversold:
        # Extreme fear: bullish (contrarian)
        return clamp((oversold - value) / oversold * 0.8)
    else:
        # Neutral zone: mild directional signal
        return clamp((value - 50) / 50 * 0.3)


# ─────────────────────────────────────────────────────────────────────────────
# VIX
# ─────────────────────────────────────────────────────────────────────────────

def fetch_vix() -> dict:
    """
    Fetch VIX (CBOE Volatility Index) value.
    High VIX = fear = potential contrarian buy signal.
    Uses FRED API if available, else yfinance.
    """
    vix_value = 20.0

    try:
        if FRED_API_KEY:
            from analysis.fundamental.forex_fundamentals import fetch_fred_series
            vix_value = fetch_fred_series("VIXCLS") or 20.0
        else:
            import yfinance as yf
            ticker = yf.Ticker("^VIX")
            hist = ticker.history(period="1d")
            if not hist.empty:
                vix_value = float(hist["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"VIX fetch failed: {e}")

    vix_high = SENTIMENT["vix_high"]
    vix_low = SENTIMENT["vix_low"]

    if vix_value >= vix_high:
        # High fear: contrarian bullish (for equities)
        vix_score = clamp((vix_value - vix_high) / 20 * 0.7)
    elif vix_value <= vix_low:
        # Complacency: mildly bearish
        vix_score = clamp(-(vix_low - vix_value) / vix_low * 0.3)
    else:
        vix_score = 0.0

    return {
        "vix": vix_value,
        "regime": "fear" if vix_value >= vix_high else ("calm" if vix_value <= vix_low else "normal"),
        "score": vix_score,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUT/CALL RATIO
# ─────────────────────────────────────────────────────────────────────────────

def fetch_put_call_ratio(symbol: str = "market") -> dict:
    """
    Fetch Put/Call ratio.
    High P/C ratio = lots of put buying = bearish sentiment = contrarian bullish.
    Uses yfinance options data.
    """
    pc_ratio = 1.0  # neutral default

    try:
        import yfinance as yf
        # Use SPY as market proxy
        ticker_sym = "SPY" if symbol == "market" else symbol
        ticker = yf.Ticker(ticker_sym)
        options_dates = ticker.options
        if not options_dates:
            raise ValueError("No options data")

        # Use nearest expiry
        opt = ticker.option_chain(options_dates[0])
        total_calls = float(opt.calls["volume"].sum())
        total_puts = float(opt.puts["volume"].sum())

        if total_calls > 0:
            pc_ratio = total_puts / total_calls
    except Exception as e:
        log.warning(f"Put/Call ratio fetch failed for {symbol}: {e}")

    overbought = SENTIMENT["put_call_overbought"]  # 1.5
    oversold = SENTIMENT["put_call_oversold"]       # 0.7

    if pc_ratio >= overbought:
        # Lots of put buying: contrarian bullish
        score = clamp((pc_ratio - overbought) / 0.5 * 0.6)
    elif pc_ratio <= oversold:
        # Too many calls: complacency, contrarian bearish
        score = clamp(-(oversold - pc_ratio) / 0.3 * 0.5)
    else:
        score = 0.0

    return {"put_call_ratio": pc_ratio, "score": score}


# ─────────────────────────────────────────────────────────────────────────────
# CRYPTO LONG/SHORT RATIO
# ─────────────────────────────────────────────────────────────────────────────

def fetch_long_short_ratio(symbol: str) -> dict:
    """
    Fetch long/short ratio from Binance futures.
    High long ratio with rising price = bullish; extreme longs = contrarian risk.
    """
    try:
        base_symbol = symbol.replace("/USDT", "USDT").replace("/", "")
        session = APISession("https://fapi.binance.com/futures/data", "binance")
        data = session.get("globalLongShortAccountRatio", params={
            "symbol": base_symbol,
            "period": "1h",
            "limit": 1,
        })
        if data and isinstance(data, list) and len(data) > 0:
            ratio = safe_float(data[0].get("longShortRatio", 1.0))
            long_pct = safe_float(data[0].get("longAccount", 0.5))
            short_pct = safe_float(data[0].get("shortAccount", 0.5))

            # Extreme positioning: contrarian signal
            if long_pct > 0.70:  # 70%+ longs = crowded trade
                score = clamp(-(long_pct - 0.70) / 0.30)
            elif short_pct > 0.70:  # 70%+ shorts = short squeeze potential
                score = clamp((short_pct - 0.70) / 0.30)
            else:
                score = clamp((long_pct - 0.50) * 0.5)

            return {
                "long_short_ratio": ratio,
                "long_pct": long_pct,
                "short_pct": short_pct,
                "score": score,
            }
    except Exception as e:
        log.debug(f"Long/short ratio fetch failed for {symbol}: {e}")

    return {"long_short_ratio": 1.0, "long_pct": 0.5, "short_pct": 0.5, "score": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# COT REPORT (Commitment of Traders)
# ─────────────────────────────────────────────────────────────────────────────

# COT data is published weekly by CFTC. We use a simplified mock
# since direct CFTC API access requires parsing specific formats.
# In production, integrate CFTC data via: https://www.cftc.gov/dea/newcot/

_COT_MOCK_DATA = {
    "GC=F":  {"commercial_net": 25000,  "noncommercial_net": -15000},
    "CL=F":  {"commercial_net": -80000, "noncommercial_net":  60000},
    "NG=F":  {"commercial_net": -20000, "noncommercial_net":  15000},
    "EUR_USD": {"commercial_net": 15000, "noncommercial_net": -10000},
    "GBP_USD": {"commercial_net": -8000, "noncommercial_net":  6000},
}

def fetch_cot_data(symbol: str) -> dict:
    """
    Fetch Commitment of Traders data.
    Commercial positions are considered 'smart money'.
    Returns a score based on commercial vs non-commercial positioning.
    """
    # In production: parse CFTC weekly files from cftc.gov
    # For now: use mock data and allow override via config
    cot = _COT_MOCK_DATA.get(symbol, {"commercial_net": 0, "noncommercial_net": 0})

    commercial_net = cot["commercial_net"]
    noncommercial_net = cot["noncommercial_net"]

    # Normalize (max typical values differ by asset)
    max_pos = max(abs(commercial_net), abs(noncommercial_net), 1)
    commercial_score = clamp(commercial_net / (max_pos * 2))
    noncommercial_score = clamp(noncommercial_net / (max_pos * 2))

    # Commercial (hedger) positioning is often contrarian;
    # large commercial long = bullish underlying demand
    cot_weight = SENTIMENT["cot_commercial_weight"]
    combined = (
        commercial_score * cot_weight +
        noncommercial_score * (1 - cot_weight)
    )

    return {
        "commercial_net": commercial_net,
        "noncommercial_net": noncommercial_net,
        "commercial_score": commercial_score,
        "noncommercial_score": noncommercial_score,
        "score": clamp(combined),
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGGREGATOR
# ─────────────────────────────────────────────────────────────────────────────

def get_sentiment_indicators(symbol: str, market_type: str = "crypto") -> dict:
    """
    Fetch and aggregate all market-structure sentiment indicators.

    Returns:
        dict with 'indicator_sentiment_score' in [-1, +1] and sub-scores
    """
    scores = {}

    # Fear & Greed (crypto-relevant)
    if market_type == "crypto":
        fg = fetch_fear_greed_index()
        scores["fear_greed"] = fg["score"]
        fg_value = fg["value"]
        fg_class = fg["classification"]
    else:
        fg_value = 50.0
        fg_class = "N/A"
        scores["fear_greed"] = 0.0

    # VIX (equity / macro)
    vix_data = fetch_vix()
    scores["vix"] = vix_data["score"] if market_type in ("stocks", "crypto") else 0.0

    # Put/Call ratio (stocks and crypto with options)
    if market_type in ("stocks", "crypto"):
        pc_data = fetch_put_call_ratio(
            "SPY" if market_type == "stocks" else "market"
        )
        scores["put_call"] = pc_data["score"]
    else:
        scores["put_call"] = 0.0

    # Long/Short ratio (crypto)
    if market_type == "crypto" and "/" in symbol:
        ls_data = fetch_long_short_ratio(symbol)
        scores["long_short"] = ls_data["score"]
    else:
        scores["long_short"] = 0.0

    # COT report (forex and commodities)
    if market_type in ("forex", "commodities"):
        cot_data = fetch_cot_data(symbol)
        scores["cot"] = cot_data["score"]
    else:
        scores["cot"] = 0.0

    # Weighted aggregate
    weights = {
        "crypto":      {"fear_greed": 0.40, "vix": 0.15, "put_call": 0.10, "long_short": 0.35, "cot": 0.00},
        "stocks":      {"fear_greed": 0.10, "vix": 0.40, "put_call": 0.35, "long_short": 0.00, "cot": 0.15},
        "forex":       {"fear_greed": 0.05, "vix": 0.20, "put_call": 0.05, "long_short": 0.00, "cot": 0.70},
        "commodities": {"fear_greed": 0.05, "vix": 0.15, "put_call": 0.05, "long_short": 0.00, "cot": 0.75},
    }
    wts = weights.get(market_type, weights["stocks"])

    final_score = sum(scores.get(k, 0.0) * wts.get(k, 0.0) for k in wts)

    return {
        "symbol": symbol,
        "indicator_sentiment_score": clamp(final_score),
        "fear_greed_index": fg_value,
        "fear_greed_class": fg_class,
        "vix": vix_data.get("vix", 20.0),
        "sub_scores": scores,
    }
