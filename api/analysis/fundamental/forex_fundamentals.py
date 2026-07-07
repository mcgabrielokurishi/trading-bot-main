"""
analysis/fundamental/forex_fundamentals.py

Macroeconomic fundamental analysis for forex pairs.
Uses FRED API for US economic data and ECB API for Eurozone data.
"""

import numpy as np
from typing import Optional
from config import FRED_API_KEY, FUNDAMENTAL
from utils.api_utils import APISession, safe_float
from utils.helpers import safe_divide, clamp
from utils.logger import get_logger

log = get_logger("forex_fundamentals")



# FRED DATA FETCHER


# FRED series IDs for key economic indicators
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "cpi_us": "CPIAUCSL",
    "gdp_us": "GDP",
    "unemployment_us": "UNRATE",
    "current_account_us": "NETFI",
    "govt_debt_gdp_us": "GFDEGDQ188S",
    "pmi_us": "MANEMP",
}

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

COUNTRY_RATE_MAP = {
    "USD": "fed_funds_rate",
    "EUR": "ecb_rate",
    "GBP": "boe_rate",
    "JPY": "boj_rate",
    "AUD": "rba_rate",
    "CAD": "boc_rate",
    "CHF": "snb_rate",
    "NZD": "rbnz_rate",
}

# Approximate interest rates (fallback when FRED unavailable)
_FALLBACK_RATES = {
    "USD": 5.25, "EUR": 4.00, "GBP": 5.00, "JPY": 0.10,
    "AUD": 4.35, "CAD": 5.00, "CHF": 1.75, "NZD": 5.50,
}

_FALLBACK_CPI = {
    "USD": 3.2, "EUR": 2.9, "GBP": 4.0, "JPY": 2.8,
    "AUD": 4.1, "CAD": 3.4, "CHF": 1.7, "NZD": 4.7,
}

_FALLBACK_GDP_GROWTH = {
    "USD": 2.5, "EUR": 0.5, "GBP": 0.3, "JPY": 1.9,
    "AUD": 2.0, "CAD": 1.5, "CHF": 1.0, "NZD": 1.5,
}


def fetch_fred_series(series_id: str, limit: int = 1) -> float:
    """Fetch the latest value of a FRED series."""
    if not FRED_API_KEY:
        return 0.0
    try:
        session = APISession("https://api.stlouisfed.org/fred", "fred")
        data = session.get("series/observations", params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        })
        obs = data.get("observations", [])
        if obs:
            return safe_float(obs[0].get("value", 0))
        return 0.0
    except Exception as e:
        log.warning(f"FRED series {series_id} fetch failed: {e}")
        return 0.0


def fetch_ecb_rate() -> float:
    """Fetch ECB deposit facility rate."""
    try:
        session = APISession(ECB_BASE, "fred")  # reuse rate limiter slot
        data = session.get(
            "FM/B.U2.EUR.4F.KR.DFR.LEV",
            params={"format": "jsondata", "lastNObservations": 1},
        )
        value_sets = data.get("dataSets", [{}])[0].get("series", {})
        if value_sets:
            first_series = list(value_sets.values())[0]
            obs = first_series.get("observations", {})
            if obs:
                last_obs = list(obs.values())[-1]
                return safe_float(last_obs[0] if last_obs else 0)
        return _FALLBACK_RATES["EUR"]
    except Exception as e:
        log.warning(f"ECB rate fetch failed: {e}")
        return _FALLBACK_RATES["EUR"]


def get_interest_rate(currency: str) -> float:
    """Get current central bank rate for a currency."""
    if currency == "USD" and FRED_API_KEY:
        rate = fetch_fred_series("FEDFUNDS")
        return rate if rate else _FALLBACK_RATES.get(currency, 2.0)
    if currency == "EUR":
        return fetch_ecb_rate()
    # For other currencies, use fallback (extend with additional APIs as needed)
    return _FALLBACK_RATES.get(currency, 2.0)


def get_inflation(currency: str) -> float:
    """Get CPI inflation for a currency's country."""
    if currency == "USD" and FRED_API_KEY:
        # YoY CPI change
        cpi_now = fetch_fred_series("CPIAUCSL")
        cpi_yr = fetch_fred_series("CPIAUCSL") if not FRED_API_KEY else 0.0
        # Use fallback for simplicity
        return _FALLBACK_CPI.get(currency, 3.0)
    return _FALLBACK_CPI.get(currency, 3.0)


def get_gdp_growth(currency: str) -> float:
    """Get GDP growth rate for a currency's country (%)."""
    if currency == "USD" and FRED_API_KEY:
        gdp_growth = fetch_fred_series("A191RL1Q225SBEA")  # Real GDP growth %
        return gdp_growth if gdp_growth else _FALLBACK_GDP_GROWTH.get(currency, 2.0)
    return _FALLBACK_GDP_GROWTH.get(currency, 2.0)


def get_current_account(currency: str) -> float:
    """Get current account balance as % of GDP (approx)."""
    defaults = {
        "USD": -2.5, "EUR": 2.5, "GBP": -4.0, "JPY": 3.5,
        "AUD": -2.0, "CAD": -2.0, "CHF": 8.0, "NZD": -5.0,
    }
    if currency == "USD" and FRED_API_KEY:
        val = fetch_fred_series("NETFI")
        if val:
            return val / 1000  # rough normalization
    return defaults.get(currency, 0.0)



# METRICS COMPUTATION


def compute_forex_metrics(pair: str) -> dict:
    """
    Compute macroeconomic metrics for a forex pair.
    pair: e.g. 'EUR_USD', 'GBP_USD', 'USD_JPY'
    """
    try:
        base_ccy, quote_ccy = pair.split("_")
    except ValueError:
        log.error(f"Invalid forex pair format: {pair}")
        return {}

    base_rate = get_interest_rate(base_ccy)
    quote_rate = get_interest_rate(quote_ccy)
    base_cpi = get_inflation(base_ccy)
    quote_cpi = get_inflation(quote_ccy)
    base_gdp = get_gdp_growth(base_ccy)
    quote_gdp = get_gdp_growth(quote_ccy)
    base_ca = get_current_account(base_ccy)
    quote_ca = get_current_account(quote_ccy)

    metrics = {
        "pair": pair,
        "base_currency": base_ccy,
        "quote_currency": quote_ccy,
        "base_rate": base_rate,
        "quote_rate": quote_rate,
        "rate_differential": base_rate - quote_rate,
        "base_cpi": base_cpi,
        "quote_cpi": quote_cpi,
        "inflation_differential": base_cpi - quote_cpi,
        "base_gdp_growth": base_gdp,
        "quote_gdp_growth": quote_gdp,
        "gdp_differential": base_gdp - quote_gdp,
        "base_current_account": base_ca,
        "quote_current_account": quote_ca,
        "current_account_differential": base_ca - quote_ca,
    }
    return metrics



# SCORING


def score_forex(pair: str, metrics: dict | None = None) -> dict:
    """
    Compute a fundamental score for a forex pair in [-1, +1].
    Positive = base currency fundamentally stronger vs quote.
    """
    m = metrics or compute_forex_metrics(pair)
    cfg = FUNDAMENTAL["forex"]

    scores = []

    # Interest rate differential: higher rate → currency demand → bullish base
    rate_diff = m.get("rate_differential", 0)
    # Normalize: 5% differential is very large in forex
    rate_score = clamp(rate_diff / 5.0)
    scores.append(rate_score * cfg["rate_diff_weight"] / cfg["rate_diff_weight"])

    # Inflation differential: lower inflation → stronger currency (purchasing power)
    inf_diff = m.get("inflation_differential", 0)
    inflation_score = clamp(-inf_diff / 5.0)  # negative inflation diff = bullish base

    # GDP differential: stronger growth → stronger currency
    gdp_diff = m.get("gdp_differential", 0)
    gdp_score = clamp(gdp_diff / 3.0)

    # Current account: surplus = more currency demanded → bullish
    ca_diff = m.get("current_account_differential", 0)
    ca_score = clamp(ca_diff / 5.0)

    fundamental_score = (
        rate_score * cfg["rate_diff_weight"] +
        inflation_score * cfg["inflation_diff_weight"] +
        gdp_score * cfg["gdp_diff_weight"] +
        ca_score * cfg["current_account_weight"]
    )

    return {
        "pair": pair,
        "rate_score": round(rate_score, 4),
        "inflation_score": round(inflation_score, 4),
        "gdp_score": round(gdp_score, 4),
        "current_account_score": round(ca_score, 4),
        "fundamental_score": round(clamp(fundamental_score), 4),
        "metrics": m,
    }
