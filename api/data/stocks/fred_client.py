"""
data/stocks/fred_client.py

Federal Reserve Economic Data (FRED) client.
Provides macro indicators: interest rates, CPI, GDP, unemployment, VIX, etc.
Free API key from https://fred.stlouisfed.org/docs/api/api_key.html
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from config import FRED_API_KEY
from utils.api_utils import APISession, safe_float
from utils.helpers import utc_now, retry
from utils.logger import get_logger

log = get_logger("fred_client")

FRED_BASE = "https://api.stlouisfed.org/fred"

# Commonly used FRED series IDs
SERIES = {
    # Interest rates
    "fed_funds_rate":        "FEDFUNDS",
    "sofr":                  "SOFR",
    "treasury_10y":          "DGS10",
    "treasury_2y":           "DGS2",
    "treasury_yield_spread": "T10Y2Y",
    "tips_10y":              "DFII10",       # Real yield
    # Inflation
    "cpi_all":               "CPIAUCSL",
    "cpi_core":              "CPILFESL",
    "pce":                   "PCE",
    "pce_core":              "PCEPILFE",
    # Growth
    "gdp":                   "GDP",
    "gdp_growth":            "A191RL1Q225SBEA",
    "industrial_production": "INDPRO",
    # Labor
    "unemployment":          "UNRATE",
    "nonfarm_payrolls":      "PAYEMS",
    "initial_claims":        "ICSA",
    # Sentiment
    "vix":                   "VIXCLS",
    "consumer_sentiment":    "UMCSENT",
    "pmi_manufacturing":     "MANEMP",
    # Credit
    "credit_spread_hy":      "BAMLH0A0HYM2",
    "ted_spread":            "TEDRATE",
    # Housing
    "housing_starts":        "HOUST",
    "case_shiller":          "CSUSHPISA",
    # Money supply
    "m2":                    "M2SL",
    "m2_growth":             "M2",
}


def _session() -> APISession:
    return APISession(FRED_BASE, "fred")


@retry(max_attempts=3, delay=2.0)
def fetch_series(
    series_id: str,
    limit: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    frequency: Optional[str] = None,
) -> pd.Series:
    """
    Fetch a FRED data series.

    Args:
        series_id: FRED series ID (e.g. 'FEDFUNDS')
        limit: Max number of observations
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        frequency: Aggregation frequency ('d','w','m','q','a')

    Returns:
        pandas Series indexed by date
    """
    if not FRED_API_KEY:
        log.debug(f"FRED API key not set; returning empty for {series_id}")
        return pd.Series(dtype=float, name=series_id)

    try:
        session = _session()
        params: dict = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date
        if frequency:
            params["frequency"] = frequency

        data = session.get("series/observations", params=params)
        observations = data.get("observations", [])

        if not observations:
            return pd.Series(dtype=float, name=series_id)

        rows = []
        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str == ".":
                continue
            rows.append({
                "date": pd.Timestamp(obs["date"], tz="UTC"),
                "value": safe_float(val_str),
            })

        if not rows:
            return pd.Series(dtype=float, name=series_id)

        df = pd.DataFrame(rows).set_index("date").sort_index()
        return df["value"].rename(series_id)

    except Exception as e:
        log.warning(f"FRED series {series_id} fetch failed: {e}")
        raise


def fetch_latest(series_id: str) -> float:
    """Fetch only the most recent value of a FRED series."""
    series = fetch_series(series_id, limit=1)
    if series.empty:
        return 0.0
    return float(series.iloc[-1])


def fetch_series_by_name(name: str) -> pd.Series:
    """Fetch a FRED series by its friendly name from SERIES dict."""
    series_id = SERIES.get(name)
    if not series_id:
        log.warning(f"Unknown FRED series name: {name}")
        return pd.Series(dtype=float, name=name)
    return fetch_series(series_id)


def fetch_macro_snapshot() -> dict:
    """
    Fetch a snapshot of key macro indicators.
    Returns dict of indicator_name -> latest value.
    """
    key_series = [
        "fed_funds_rate", "treasury_10y", "treasury_2y",
        "treasury_yield_spread", "tips_10y", "cpi_all",
        "gdp_growth", "unemployment", "vix", "credit_spread_hy",
        "consumer_sentiment", "m2_growth",
    ]
    snapshot = {}
    for name in key_series:
        series_id = SERIES.get(name)
        if series_id:
            try:
                snapshot[name] = fetch_latest(series_id)
            except Exception:
                snapshot[name] = None

    # Derived: yield curve inversion
    if snapshot.get("treasury_10y") and snapshot.get("treasury_2y"):
        snapshot["yield_curve_inverted"] = (
            snapshot["treasury_10y"] < snapshot["treasury_2y"]
        )

    return snapshot


def fetch_series_batch(names: list[str]) -> dict[str, pd.Series]:
    """Fetch multiple FRED series by friendly name."""
    result = {}
    for name in names:
        try:
            result[name] = fetch_series_by_name(name)
        except Exception as e:
            log.warning(f"Batch fetch failed for {name}: {e}")
            result[name] = pd.Series(dtype=float, name=name)
    return result
