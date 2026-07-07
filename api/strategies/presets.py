"""


Strategy preset definitions and per-market customizations.
Each preset tunes: factor weights, signal thresholds, indicator emphasis,
risk parameters, and timeframe focus.
"""

from config import STRATEGY_PRESETS, SIGNAL_THRESHOLDS



# PRESET METADATA


PRESET_DESCRIPTIONS = {
    "balanced": {
        "description": "Equal emphasis on technical, fundamental, and sentiment analysis.",
        "best_for": ["stocks", "crypto"],
        "timeframe_focus": ["1h", "4h", "1d"],
        "risk_profile": "moderate",
        "holding_period": "days to weeks",
    },
    "momentum": {
        "description": "Trend-following strategy driven primarily by technical momentum indicators.",
        "best_for": ["crypto", "commodities"],
        "timeframe_focus": ["15m", "1h", "4h"],
        "risk_profile": "high",
        "holding_period": "hours to days",
        "indicator_emphasis": ["RSI", "MACD", "ADX", "SuperTrend", "AO"],
    },
    "value": {
        "description": "Fundamental-driven strategy seeking undervalued assets.",
        "best_for": ["stocks"],
        "timeframe_focus": ["1d", "1w"],
        "risk_profile": "low",
        "holding_period": "weeks to months",
        "indicator_emphasis": ["SMA200", "Bollinger", "Pivot Points"],
    },
    "sentiment_driven": {
        "description": "Social and news sentiment-driven contrarian strategy.",
        "best_for": ["crypto", "stocks"],
        "timeframe_focus": ["1h", "4h"],
        "risk_profile": "high",
        "holding_period": "hours to days",
    },
    "technical_only": {
        "description": "Pure technical analysis with no fundamental or sentiment overlay.",
        "best_for": ["forex", "commodities", "crypto"],
        "timeframe_focus": ["15m", "1h", "4h"],
        "risk_profile": "moderate",
        "holding_period": "minutes to days",
    },
}

# Per-preset signal threshold overrides (optional; falls back to config defaults)
PRESET_THRESHOLDS = {
    "momentum": {
        "strong_buy":   0.50,   # more sensitive for trend-following
        "buy":          0.15,
        "hold_upper":   0.15,
        "hold_lower":  -0.15,
        "sell":        -0.15,
        "strong_sell": -0.50,
    },
    "value": {
        "strong_buy":   0.70,   # stricter for fundamental conviction
        "buy":          0.30,
        "hold_upper":   0.30,
        "hold_lower":  -0.30,
        "sell":        -0.30,
        "strong_sell": -0.70,
    },
    "sentiment_driven": {
        "strong_buy":   0.55,
        "buy":          0.20,
        "hold_upper":   0.20,
        "hold_lower":  -0.20,
        "sell":        -0.20,
        "strong_sell": -0.55,
    },
}

# Per-market-type override for signal sensitivity
MARKET_SIGNAL_ADJUSTMENTS = {
    "crypto": {"sensitivity_multiplier": 1.1},    # crypto moves fast, be more sensitive
    "forex":  {"sensitivity_multiplier": 0.9},    # forex needs stronger conviction
    "stocks": {"sensitivity_multiplier": 1.0},
    "commodities": {"sensitivity_multiplier": 0.95},
}

# Risk parameter overrides per preset
PRESET_RISK_OVERRIDES = {
    "momentum": {
        "position_sizing_method": "atr_based",
        "atr_risk_multiplier": 1.2,       # tighter stops for momentum
        "take_profit_rr": 2.5,
        "trailing_stop_pct": 0.015,
    },
    "value": {
        "position_sizing_method": "fixed_fractional",
        "fixed_stop_pct": 0.08,           # wider stops for value (avoid noise)
        "take_profit_rr": 3.0,
        "atr_stop_multiplier": 3.0,
    },
    "sentiment_driven": {
        "position_sizing_method": "fixed_fractional",
        "fixed_risk_pct": 0.015,          # smaller positions (sentiment is volatile)
        "take_profit_rr": 1.8,
    },
    "technical_only": {
        "position_sizing_method": "atr_based",
        "atr_risk_multiplier": 1.5,
        "take_profit_rr": 2.0,
    },
}



# HELPER FUNCTIONS


def get_preset_weights(preset: str, market_type: str) -> dict:
    """
    Get factor weights for a preset + market_type combination.
    Falls back to STRATEGY_PRESETS config values.
    """
    from config import STRATEGY_PRESETS, FACTOR_WEIGHTS
    if preset in STRATEGY_PRESETS:
        return STRATEGY_PRESETS[preset]
    return FACTOR_WEIGHTS.get(market_type, FACTOR_WEIGHTS["default"])


def get_preset_thresholds(preset: str) -> dict:
    """Get signal thresholds for a preset, falling back to global defaults."""
    return PRESET_THRESHOLDS.get(preset, SIGNAL_THRESHOLDS)


def get_preset_risk(preset: str) -> dict:
    """Get risk parameter overrides for a preset."""
    return PRESET_RISK_OVERRIDES.get(preset, {})


def list_presets() -> list[dict]:
    """Return a list of all available strategy presets with metadata."""
    from config import STRATEGY_PRESETS
    result = []
    for name, weights in STRATEGY_PRESETS.items():
        meta = PRESET_DESCRIPTIONS.get(name, {})
        result.append({
            "name": name,
            "weights": weights,
            "description": meta.get("description", ""),
            "best_for": meta.get("best_for", []),
            "risk_profile": meta.get("risk_profile", "moderate"),
            "holding_period": meta.get("holding_period", "variable"),
        })
    return result


def apply_market_sensitivity(score: float, market_type: str) -> float:
    """Scale a signal score by market-specific sensitivity multiplier."""
    mult = MARKET_SIGNAL_ADJUSTMENTS.get(market_type, {}).get("sensitivity_multiplier", 1.0)
    from utils.helpers import clamp
    return clamp(score * mult)
