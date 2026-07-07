"""
data/commodities/eia_client.py

Energy Information Administration (EIA) API v2 client.
Provides weekly inventory, production, and consumption data for energy commodities.
Free API key: https://www.eia.gov/opendata/
"""

import pandas as pd
from typing import Optional
from config import EIA_API_KEY
from utils.api_utils import APISession, safe_float, extract_nested
from utils.helpers import retry
from utils.logger import get_logger

log = get_logger("eia_client")

EIA_BASE = "https://api.eia.gov/v2"

# Key EIA series IDs
EIA_SERIES = {
    # Crude oil
    "crude_us_stocks":        "PET.WCRSTUS1.W",
    "crude_production":       "PET.WCRFPUS2.W",
    "crude_imports":          "PET.WCRIMUS2.W",
    "crude_refinery_input":   "PET.WCRRIUS2.W",
    "refinery_utilization":   "PET.WPULEUS3.W",
    # Petroleum products
    "gasoline_stocks":        "PET.WGTSTUS1.W",
    "distillate_stocks":      "PET.WDISTUS1.W",
    # Natural gas
    "ng_storage":             "NG.NW2_EPG0_SWO_R48_BCF.W",
    "ng_production":          "NG.N9070US2.M",
    "ng_consumption":         "NG.N3020US2.M",
    # Prices
    "wti_spot":               "PET.RWTC.D",
    "brent_spot":             "PET.RBRTE.D",
    "henry_hub_spot":         "NG.RNGWHHD.D",
    "gasoline_retail":        "PET.EMM_EPM0_PTE_NUS_DPG.W",
}


def _session() -> Optional[APISession]:
    if not EIA_API_KEY:
        return None
    return APISession(EIA_BASE, "fred")  # reuse rate limiter


@retry(max_attempts=3, delay=2.0)
def fetch_series(series_id: str, num_obs: int = 52) -> pd.Series:
    """
    Fetch a time-series from EIA API v2.

    Args:
        series_id: EIA series ID e.g. 'PET.WCRSTUS1.W'
        num_obs: Number of most recent observations

    Returns:
        pandas Series indexed by date
    """
    session = _session()
    if not session:
        log.debug(f"No EIA API key; returning empty for {series_id}")
        return pd.Series(dtype=float, name=series_id)

    try:
        # EIA v2 uses different endpoint structure
        data = session.get("seriesid", params={
            "api_key": EIA_API_KEY,
            "seriesid": series_id,
        })

        # Try v1 fallback format
        if not data or "response" not in data:
            session_v1 = APISession("https://api.eia.gov/series", "fred")
            data = session_v1.get("", params={
                "api_key": EIA_API_KEY,
                "series_id": series_id,
                "out": "json",
                "num": num_obs,
            })
            series_data = extract_nested(data, "series", 0, "data", default=[])
        else:
            series_data = extract_nested(data, "response", "data", default=[])

        if not series_data:
            return pd.Series(dtype=float, name=series_id)

        rows = []
        for obs in series_data[:num_obs]:
            if isinstance(obs, list) and len(obs) >= 2:
                date_str, value = obs[0], obs[1]
            elif isinstance(obs, dict):
                date_str = obs.get("period") or obs.get("date", "")
                value = obs.get("value")
            else:
                continue

            if value is None or value == "":
                continue
            try:
                rows.append({"date": pd.Timestamp(str(date_str), tz="UTC"), "value": safe_float(value)})
            except Exception:
                continue

        if not rows:
            return pd.Series(dtype=float, name=series_id)

        df = pd.DataFrame(rows).set_index("date").sort_index()
        return df["value"].rename(series_id)

    except Exception as e:
        log.warning(f"EIA series {series_id} fetch failed: {e}")
        raise


def fetch_series_by_name(name: str, num_obs: int = 52) -> pd.Series:
    """Fetch EIA series by friendly name."""
    series_id = EIA_SERIES.get(name)
    if not series_id:
        log.warning(f"Unknown EIA series name: {name}")
        return pd.Series(dtype=float, name=name)
    return fetch_series(series_id, num_obs)


def fetch_latest(series_id: str) -> float:
    """Fetch only the most recent value of a series."""
    s = fetch_series(series_id, num_obs=1)
    return float(s.iloc[-1]) if not s.empty else 0.0


def fetch_crude_inventory_report() -> dict:
    """
    Fetch the weekly EIA crude oil inventory report (most important energy data release).
    Returns current stocks, change WoW, and 5-year average.
    """
    stocks = fetch_series(EIA_SERIES["crude_us_stocks"], num_obs=8)
    prod = fetch_series(EIA_SERIES["crude_production"], num_obs=4)
    imports = fetch_series(EIA_SERIES["crude_imports"], num_obs=4)
    refinery = fetch_series(EIA_SERIES["refinery_utilization"], num_obs=4)

    report = {}

    if not stocks.empty:
        report["current_stocks_mb"] = float(stocks.iloc[-1])
        if len(stocks) >= 2:
            report["wow_change_mb"] = float(stocks.iloc[-1] - stocks.iloc[-2])
        if len(stocks) >= 5:
            report["five_week_avg"] = float(stocks.tail(5).mean())

    if not prod.empty:
        report["production_kbpd"] = float(prod.iloc[-1])

    if not imports.empty:
        report["imports_kbpd"] = float(imports.iloc[-1])

    if not refinery.empty:
        report["refinery_utilization_pct"] = float(refinery.iloc[-1])

    # Market interpretation
    wow = report.get("wow_change_mb", 0)
    if wow < -3:
        report["interpretation"] = "Large draw - strongly bullish for oil"
    elif wow < 0:
        report["interpretation"] = "Draw - mildly bullish for oil"
    elif wow < 3:
        report["interpretation"] = "Build - mildly bearish for oil"
    else:
        report["interpretation"] = "Large build - strongly bearish for oil"

    return report


def fetch_natural_gas_storage() -> dict:
    """Fetch weekly EIA natural gas storage report."""
    storage = fetch_series(EIA_SERIES["ng_storage"], num_obs=8)
    report = {}

    if not storage.empty:
        report["current_storage_bcf"] = float(storage.iloc[-1])
        if len(storage) >= 2:
            report["wow_change_bcf"] = float(storage.iloc[-1] - storage.iloc[-2])
        if len(storage) >= 5:
            report["five_week_avg"] = float(storage.tail(5).mean())

    return report


def fetch_energy_prices() -> dict:
    """Fetch spot prices for major energy commodities."""
    prices = {}
    for name in ["wti_spot", "brent_spot", "henry_hub_spot", "gasoline_retail"]:
        try:
            prices[name] = fetch_latest(EIA_SERIES[name])
        except Exception:
            prices[name] = 0.0

    if prices.get("wti_spot") and prices.get("brent_spot"):
        prices["brent_wti_spread"] = prices["brent_spot"] - prices["wti_spot"]

    return prices
