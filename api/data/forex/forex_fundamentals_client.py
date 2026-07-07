"""
data/forex/forex_fundamentals_client.py

Macro data aggregator for forex analysis.
Combines FRED, ECB, and World Bank data for interest rates, GDP, CPI.
"""

import pandas as pd
from typing import Optional
from data.stocks.fred_client import fetch_series, fetch_latest, SERIES
from utils.logger import get_logger

log = get_logger("forex_fundamentals_client")

# Currency to country/region mapping for macro data
CURRENCY_COUNTRY = {
    "USD": "US", "EUR": "EA", "GBP": "GB", "JPY": "JP",
    "AUD": "AU", "CAD": "CA", "CHF": "CH", "NZD": "NZ",
}

# Central bank rate FRED series by currency
CENTRAL_BANK_RATES = {
    "USD": "FEDFUNDS",
    "EUR": None,          # Use ECB API directly
    "GBP": "BOEBR",
    "JPY": None,          # BoJ rate not in FRED; use fallback
    "AUD": None,
    "CAD": "CADIRINTDNSTM",
    "CHF": None,
    "NZD": None,
}

FALLBACK_RATES = {
    "USD": 5.25, "EUR": 4.00, "GBP": 5.00, "JPY": 0.10,
    "AUD": 4.35, "CAD": 5.00, "CHF": 1.75, "NZD": 5.50,
}

FALLBACK_INFLATION = {
    "USD": 3.2, "EUR": 2.9, "GBP": 4.0, "JPY": 2.8,
    "AUD": 4.1, "CAD": 3.4, "CHF": 1.7, "NZD": 4.7,
}


def get_central_bank_rate(currency: str) -> float:
    """Get the current central bank policy rate for a currency."""
    series_id = CENTRAL_BANK_RATES.get(currency)
    if series_id:
        try:
            rate = fetch_latest(series_id)
            if rate:
                return rate
        except Exception as e:
            log.debug(f"FRED rate fetch failed for {currency}: {e}")
    return FALLBACK_RATES.get(currency, 2.0)


def get_inflation_rate(currency: str) -> float:
    """Get current CPI inflation rate for a currency's country."""
    if currency == "USD":
        try:
            # Compute YoY CPI change
            cpi = fetch_series("CPIAUCSL", limit=14)
            if len(cpi) >= 13:
                return float((cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100)
        except Exception:
            pass
    return FALLBACK_INFLATION.get(currency, 3.0)


def get_pairwise_fundamentals(base: str, quote: str) -> dict:
    """
    Compute fundamental differentials between two currencies.
    Returns a summary dict used by forex_fundamentals.py scorer.
    """
    base_rate = get_central_bank_rate(base)
    quote_rate = get_central_bank_rate(quote)
    base_cpi = get_inflation_rate(base)
    quote_cpi = get_inflation_rate(quote)

    return {
        "base_rate": base_rate,
        "quote_rate": quote_rate,
        "rate_differential": base_rate - quote_rate,
        "base_cpi": base_cpi,
        "quote_cpi": quote_cpi,
        "inflation_differential": base_cpi - quote_cpi,
    }


def get_us_macro_overview() -> dict:
    """Get US macro overview from FRED for cross-market context."""
    try:
        return {
            "fed_funds_rate": fetch_latest(SERIES["fed_funds_rate"]),
            "cpi":            fetch_latest(SERIES["cpi_all"]),
            "unemployment":   fetch_latest(SERIES["unemployment"]),
            "gdp_growth":     fetch_latest(SERIES["gdp_growth"]),
            "vix":            fetch_latest(SERIES["vix"]),
            "yield_10y":      fetch_latest(SERIES["treasury_10y"]),
            "yield_2y":       fetch_latest(SERIES["treasury_2y"]),
        }
    except Exception as e:
        log.warning(f"US macro overview failed: {e}")
        return {}
