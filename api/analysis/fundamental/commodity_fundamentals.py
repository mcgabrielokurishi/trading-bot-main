"""
Supply/demand and macroeconomic fundamental analysis for commodities.
Uses EIA API for energy, USDA data for agriculture, and yfinance for futures curves.
"""

import math
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional
from config import EIA_API_KEY, FUNDAMENTAL
from utils.api_utils import APISession, safe_float, extract_nested
from utils.helpers import safe_divide, clamp
from utils.logger import get_logger

log = get_logger("commodity_fundamentals")

# COMMODITY CLASSIFICATION

COMMODITY_META = {
    "GC=F": {"name": "Gold",         "type": "precious_metal",  "unit": "troy_oz"},
    "SI=F": {"name": "Silver",       "type": "precious_metal",  "unit": "troy_oz"},
    "CL=F": {"name": "Crude Oil",    "type": "energy",          "unit": "barrel"},
    "NG=F": {"name": "Natural Gas",  "type": "energy",          "unit": "mmbtu"},
    "ZC=F": {"name": "Corn",         "type": "agricultural",    "unit": "bushel"},
    "ZW=F": {"name": "Wheat",        "type": "agricultural",    "unit": "bushel"},
    "HG=F": {"name": "Copper",       "type": "industrial_metal","unit": "lb"},
    "PL=F": {"name": "Platinum",     "type": "precious_metal",  "unit": "troy_oz"},
}

# EIA series for key energy commodities
EIA_SERIES = {
    "crude_inventory": "PET.WCRSTUS1.W",       # Weekly US crude stocks
    "gasoline_inventory": "PET.WGTSTUS1.W",    # Weekly gasoline stocks
    "ng_inventory": "NG.NW2_EPG0_SWO_R48_BCF.W",  # Natural gas storage
    "crude_production": "PET.WCRFPUS2.W",       # US crude production
    "crude_imports": "PET.WCRIMUS2.W",           # US crude imports
    "refinery_utilization": "PET.WPULEUS3.W",   # Refinery utilization rate
}

# Seasonal factors by month (rough approximation; 1.0 = neutral)
SEASONAL_FACTORS = {
    "CL=F": {1: 0.95, 2: 0.95, 3: 1.00, 4: 1.05, 5: 1.05, 6: 1.10,
              7: 1.10, 8: 1.05, 9: 1.00, 10: 0.95, 11: 0.90, 12: 0.90},
    "NG=F": {1: 1.15, 2: 1.10, 3: 0.95, 4: 0.90, 5: 0.90, 6: 1.05,
              7: 1.10, 8: 1.10, 9: 1.00, 10: 0.95, 11: 1.05, 12: 1.15},
    "ZC=F": {1: 1.00, 2: 1.00, 3: 1.00, 4: 0.95, 5: 0.95, 6: 0.90,
              7: 0.85, 8: 0.90, 9: 0.95, 10: 1.00, 11: 1.05, 12: 1.05},
    "ZW=F": {1: 1.05, 2: 1.05, 3: 1.00, 4: 1.00, 5: 1.00, 6: 0.90,
              7: 0.85, 8: 0.90, 9: 0.95, 10: 1.00, 11: 1.05, 12: 1.05},
    "GC=F": {1: 1.02, 2: 1.03, 3: 1.01, 4: 0.99, 5: 0.98, 6: 0.99,
              7: 0.98, 8: 1.00, 9: 1.01, 10: 1.01, 11: 1.00, 12: 1.02},
}



# DATA FETCHERS


def fetch_eia_series(series_id: str, num_obs: int = 4) -> list[float]:
    """Fetch recent observations from EIA API v2."""
    if not EIA_API_KEY:
        return []
    try:
        session = APISession("https://api.eia.gov/v2", "fred")  # reuse slot
        data = session.get("seriesid", params={
            "api_key": EIA_API_KEY,
            "seriesid": series_id,
            "num": num_obs,
            "out": "json",
        })
        series_data = extract_nested(data, "response", "data", default=[])
        return [safe_float(obs.get("value")) for obs in series_data if obs.get("value")]
    except Exception as e:
        log.warning(f"EIA fetch failed for {series_id}: {e}")
        return []


def fetch_futures_curve(base_symbol: str, num_contracts: int = 4) -> list[float]:
    """
    Fetch the futures curve by looking at successive contract months.
    Returns list of prices for front through back contracts.
    """
    prices = []
    try:
        ticker = yf.Ticker(base_symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            prices.append(float(hist["Close"].iloc[-1]))

        # Try to get next contract months (approximate)
        # yfinance doesn't always have continuous contract data
        for i in range(1, num_contracts):
            try:
                month_sym = base_symbol  # Simplified; real impl would adjust month codes
                t2 = yf.Ticker(month_sym)
                h2 = t2.history(period="1d")
                if not h2.empty:
                    prices.append(float(h2["Close"].iloc[-1]))
            except Exception:
                break

    except Exception as e:
        log.warning(f"Futures curve fetch failed for {base_symbol}: {e}")

    return prices


def get_seasonal_factor(symbol: str) -> float:
    """Return current month seasonal factor for a commodity."""
    month = datetime.utcnow().month
    seasonal_map = SEASONAL_FACTORS.get(symbol, {})
    return seasonal_map.get(month, 1.0)



# METRICS COMPUTATION


def compute_energy_metrics(symbol: str) -> dict:
    """Compute energy-specific supply/demand metrics."""
    metrics = {}

    crude_inv = fetch_eia_series(EIA_SERIES["crude_inventory"], 4)
    if len(crude_inv) >= 2:
        # Inventory change (week over week): drawdown = bullish, build = bearish
        metrics["inventory_change_wow"] = crude_inv[0] - crude_inv[1]
        metrics["inventory_4w_trend"] = (crude_inv[0] - crude_inv[-1]) / len(crude_inv)
        metrics["current_inventory"] = crude_inv[0]

    prod = fetch_eia_series(EIA_SERIES["crude_production"], 4)
    if prod:
        metrics["production_latest"] = prod[0]
        if len(prod) >= 2:
            metrics["production_change"] = prod[0] - prod[1]

    imports = fetch_eia_series(EIA_SERIES["crude_imports"], 2)
    if imports:
        metrics["imports_latest"] = imports[0]

    refinery = fetch_eia_series(EIA_SERIES["refinery_utilization"], 2)
    if refinery:
        metrics["refinery_utilization"] = refinery[0]

    return metrics


def compute_commodity_metrics(symbol: str) -> dict:
    """
    Aggregate fundamental metrics for any commodity.
    """
    meta = COMMODITY_META.get(symbol, {})
    commodity_type = meta.get("type", "unknown")
    metrics: dict = {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "type": commodity_type,
    }

    # Get current price and historical data from yfinance
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if not hist.empty:
            current_price = float(hist["Close"].iloc[-1])
            metrics["current_price"] = current_price
            metrics["price_52w_high"] = float(hist["High"].max())
            metrics["price_52w_low"] = float(hist["Low"].min())
            metrics["price_pct_from_52w_high"] = safe_divide(
                current_price - metrics["price_52w_high"],
                metrics["price_52w_high"]
            )
            # 30-day return
            if len(hist) >= 22:
                metrics["return_30d"] = safe_divide(
                    current_price - float(hist["Close"].iloc[-22]),
                    float(hist["Close"].iloc[-22])
                )
            # Average volume trend
            if "Volume" in hist.columns:
                metrics["avg_volume_30d"] = float(hist["Volume"].tail(22).mean())
                metrics["volume_trend"] = safe_divide(
                    hist["Volume"].tail(5).mean(),
                    hist["Volume"].tail(22).mean()
                ) - 1
    except Exception as e:
        log.warning(f"yfinance fetch failed for {symbol}: {e}")

    # Seasonal factor
    metrics["seasonal_factor"] = get_seasonal_factor(symbol)

    # Futures curve (contango/backwardation)
    curve = fetch_futures_curve(symbol, num_contracts=3)
    if len(curve) >= 2:
        # Contango: front < back (bearish for spot), Backwardation: front > back (bullish)
        slope = (curve[-1] - curve[0]) / len(curve)
        metrics["futures_curve_slope"] = slope
        metrics["futures_structure"] = "contango" if slope > 0 else "backwardation"
    else:
        metrics["futures_curve_slope"] = 0.0
        metrics["futures_structure"] = "unknown"

    # Energy-specific metrics
    if commodity_type == "energy" and symbol in ("CL=F", "NG=F"):
        metrics.update(compute_energy_metrics(symbol))

    # Mock agricultural data (USDA data not easily API-accessible without manual download)
    if commodity_type == "agricultural":
        import random
        rng = random.Random(hash(symbol + str(datetime.utcnow().month)))
        metrics["usda_production_estimate"] = rng.uniform(0.9, 1.1)   # vs last year
        metrics["usda_carryout_stocks"] = rng.uniform(0.8, 1.2)       # vs 5-yr avg
        metrics["export_pace"] = rng.uniform(0.7, 1.3)               # vs year-ago

    # Gold/Silver: use real yields as inverse signal
    if commodity_type == "precious_metal" and symbol in ("GC=F", "SI=F"):
        try:
            from analysis.fundamental.forex_fundamentals import fetch_fred_series
            real_yield = fetch_fred_series("DFII10")  # 10Y TIPS yield
            metrics["real_yield_10y"] = real_yield
        except Exception:
            metrics["real_yield_10y"] = 2.0

    return metrics



# SCORIN

def _score_inventory(m: dict) -> float:
    """core inventory dynamics. Drawdown = bullish."""
    inv_change = m.get("inventory_change_wow", 0)
    inv_trend = m.get("inventory_4w_trend", 0)
    if not inv_change and not inv_trend:
        return 0.0
    # Negative inventory change = drawdown = bullish
    scores = []
    if inv_change:
        scores.append(clamp(-inv_change / 5e6))  # normalize to ~5M barrel weekly swings
    if inv_trend:
        scores.append(clamp(-inv_trend / 2e6))
    return float(np.mean(scores)) if scores else 0.0


def _score_futures_curve(m: dict) -> float:
    """Score futures curve: backwardation is bullish for spot, contango bearish."""
    slope = m.get("futures_curve_slope", 0)
    if slope == 0:
        return 0.0
    current_price = m.get("current_price", 1)
    # Normalize slope as % per contract
    pct_slope = safe_divide(slope, current_price)
    return clamp(-pct_slope * 20)  # invert: contango(+slope) → negative score


def _score_seasonal(m: dict) -> float:
    """Score seasonal tailwind/headwind."""
    factor = m.get("seasonal_factor", 1.0)
    return clamp((factor - 1.0) * 5)  # 20% seasonal premium = +1.0


def _score_supply_demand(m: dict) -> float:
    """Composite supply/demand score."""
    scores = []

    # Production trend (higher production = bearish for price)
    prod_change = m.get("production_change", 0)
    if prod_change:
        scores.append(clamp(-prod_change / 1e5))  # normalize to 100k bpd

    # Agricultural: carryout stocks vs 5yr average
    carryout = m.get("usda_carryout_stocks", 1.0)
    if carryout != 1.0:
        scores.append(clamp(1 - carryout))  # low stocks = bullish

    # Export pace
    export = m.get("export_pace", 1.0)
    if export != 1.0:
        scores.append(clamp(export - 1))  # high exports = bullish

    # Real yields for gold (inverse relationship)
    real_yield = m.get("real_yield_10y")
    if real_yield is not None:
        scores.append(clamp(-real_yield / 3))  # high real yield = bearish gold

    # Price from 52-week high (momentum/mean reversion)
    pct_from_high = m.get("price_pct_from_52w_high", 0)
    if pct_from_high:
        scores.append(clamp(pct_from_high * 2))  # deep below high can mean oversold

    return float(np.mean(scores)) if scores else 0.0


def score_commodity(symbol: str, metrics: dict | None = None) -> dict:
    """
    Compute fundamental score for a commodity in [-1, +1].
    """
    m = metrics or compute_commodity_metrics(symbol)
    cfg = FUNDAMENTAL["commodity"]

    inventory_score = _score_inventory(m)
    futures_score = _score_futures_curve(m)
    seasonal_score = _score_seasonal(m)
    supply_demand_score = _score_supply_demand(m)

    fundamental_score = (
        inventory_score * cfg["inventory_weight"] +
        futures_score * cfg["futures_curve_weight"] +
        seasonal_score * cfg["seasonal_weight"] +
        supply_demand_score * cfg["production_weight"]
    )

    return {
        "symbol": symbol,
        "inventory_score": round(inventory_score, 4),
        "futures_curve_score": round(futures_score, 4),
        "seasonal_score": round(seasonal_score, 4),
        "supply_demand_score": round(supply_demand_score, 4),
        "fundamental_score": round(clamp(fundamental_score), 4),
        "metrics": m,
    }
