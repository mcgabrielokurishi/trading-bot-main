"""
analysis/fundamental/stock_fundamentals.py

Fetches and analyzes fundamental data for US and global stocks.
Data sourced from Alpha Vantage and Yahoo Finance (yfinance).
"""

import math
import numpy as np
import yfinance as yf
from typing import Optional
from config import FUNDAMENTAL, ALPHA_VANTAGE_API_KEY
from utils.api_utils import APISession, safe_float, extract_nested
from utils.helpers import safe_divide, clamp
from utils.logger import get_logger

log = get_logger("stock_fundamentals")

AV_BASE = "https://www.alphavantage.co/query"



# DATA FETCHERS


def fetch_overview_av(symbol: str) -> dict:
    """Fetch company overview from Alpha Vantage."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = APISession(AV_BASE, "alpha_vantage")
        data = session.get("", params={
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        })
        return data or {}
    except Exception as e:
        log.warning(f"AV overview fetch failed for {symbol}: {e}")
        return {}


def fetch_income_statement_av(symbol: str) -> dict:
    """Fetch annual income statement from Alpha Vantage."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = APISession(AV_BASE, "alpha_vantage")
        return session.get("", params={
            "function": "INCOME_STATEMENT",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }) or {}
    except Exception as e:
        log.warning(f"AV income stmt fetch failed for {symbol}: {e}")
        return {}


def fetch_balance_sheet_av(symbol: str) -> dict:
    """Fetch annual balance sheet from Alpha Vantage."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = APISession(AV_BASE, "alpha_vantage")
        return session.get("", params={
            "function": "BALANCE_SHEET",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }) or {}
    except Exception as e:
        log.warning(f"AV balance sheet fetch failed for {symbol}: {e}")
        return {}


def fetch_cash_flow_av(symbol: str) -> dict:
    """Fetch annual cash flow statement from Alpha Vantage."""
    if not ALPHA_VANTAGE_API_KEY:
        return {}
    try:
        session = APISession(AV_BASE, "alpha_vantage")
        return session.get("", params={
            "function": "CASH_FLOW",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }) or {}
    except Exception as e:
        log.warning(f"AV cash flow fetch failed for {symbol}: {e}")
        return {}


def fetch_yfinance_info(symbol: str) -> dict:
    """Fetch comprehensive info dict from yfinance (fallback/supplement)."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return info
    except Exception as e:
        log.warning(f"yfinance info fetch failed for {symbol}: {e}")
        return {}



# METRICS COMPUTATION


def compute_stock_metrics(symbol: str) -> dict:
    """
    Compute a comprehensive set of fundamental metrics for a stock.
    Tries Alpha Vantage first, falls back to yfinance.
    """
    metrics: dict = {"symbol": symbol}

    # Primary: yfinance (broader availability, no rate limit for small usage)
    yf_info = fetch_yfinance_info(symbol)

    # Valuation ratios
    metrics["pe_ratio"] = safe_float(yf_info.get("trailingPE"))
    metrics["forward_pe"] = safe_float(yf_info.get("forwardPE"))
    metrics["pb_ratio"] = safe_float(yf_info.get("priceToBook"))
    metrics["ps_ratio"] = safe_float(yf_info.get("priceToSalesTrailing12Months"))
    metrics["ev_ebitda"] = safe_float(yf_info.get("enterpriseToEbitda"))
    metrics["peg_ratio"] = safe_float(yf_info.get("pegRatio"))

    # Profitability
    metrics["roe"] = safe_float(yf_info.get("returnOnEquity"))
    metrics["roa"] = safe_float(yf_info.get("returnOnAssets"))
    metrics["gross_margin"] = safe_float(yf_info.get("grossMargins"))
    metrics["operating_margin"] = safe_float(yf_info.get("operatingMargins"))
    metrics["net_margin"] = safe_float(yf_info.get("profitMargins"))

    # Leverage
    metrics["debt_to_equity"] = safe_float(yf_info.get("debtToEquity"))
    metrics["current_ratio"] = safe_float(yf_info.get("currentRatio"))
    metrics["quick_ratio"] = safe_float(yf_info.get("quickRatio"))

    # Growth
    metrics["revenue_growth"] = safe_float(yf_info.get("revenueGrowth"))
    metrics["earnings_growth"] = safe_float(yf_info.get("earningsGrowth"))
    metrics["earnings_quarterly_growth"] = safe_float(yf_info.get("earningsQuarterlyGrowth"))

    # Cash flow
    market_cap = safe_float(yf_info.get("marketCap"))
    free_cf = safe_float(yf_info.get("freeCashflow"))
    metrics["market_cap"] = market_cap
    metrics["free_cashflow"] = free_cf
    metrics["fcf_yield"] = safe_divide(free_cf, market_cap)

    # Dividend
    metrics["dividend_yield"] = safe_float(yf_info.get("dividendYield"))
    metrics["payout_ratio"] = safe_float(yf_info.get("payoutRatio"))

    # Per share
    metrics["eps_ttm"] = safe_float(yf_info.get("trailingEps"))
    metrics["book_value_per_share"] = safe_float(yf_info.get("bookValue"))

    # Supplementary from Alpha Vantage overview
    av_overview = fetch_overview_av(symbol)
    if av_overview:
        # Fill gaps or override with AV data
        if not metrics["pe_ratio"]:
            metrics["pe_ratio"] = safe_float(av_overview.get("PERatio"))
        metrics["roic"] = safe_float(av_overview.get("ReturnOnInvestedCapital"))
        metrics["analyst_target"] = safe_float(av_overview.get("AnalystTargetPrice"))
        metrics["52w_high"] = safe_float(av_overview.get("52WeekHigh"))
        metrics["52w_low"] = safe_float(av_overview.get("52WeekLow"))
        metrics["sector"] = av_overview.get("Sector", "")
        metrics["industry"] = av_overview.get("Industry", "")

    # Income statement growth (YoY)
    income_data = fetch_income_statement_av(symbol)
    reports = income_data.get("annualReports", [])
    if len(reports) >= 2:
        try:
            rev_curr = safe_float(reports[0].get("totalRevenue"))
            rev_prev = safe_float(reports[1].get("totalRevenue"))
            ni_curr = safe_float(reports[0].get("netIncome"))
            ni_prev = safe_float(reports[1].get("netIncome"))
            metrics["revenue_growth_yoy"] = safe_divide(rev_curr - rev_prev, abs(rev_prev))
            metrics["net_income_growth_yoy"] = safe_divide(ni_curr - ni_prev, abs(ni_prev))
            metrics["gross_profit"] = safe_float(reports[0].get("grossProfit"))
            metrics["operating_income"] = safe_float(reports[0].get("operatingIncome"))
        except Exception:
            pass

    # Cash flow data
    cf_data = fetch_cash_flow_av(symbol)
    cf_reports = cf_data.get("annualReports", [])
    if cf_reports:
        try:
            operating_cf = safe_float(cf_reports[0].get("operatingCashflow"))
            capex = safe_float(cf_reports[0].get("capitalExpenditures"))
            metrics["operating_cashflow"] = operating_cf
            metrics["capex"] = capex
            if not metrics.get("free_cashflow"):
                metrics["free_cashflow"] = operating_cf - abs(capex)
                metrics["fcf_yield"] = safe_divide(metrics["free_cashflow"], market_cap)
        except Exception:
            pass

    return metrics



# SCORING


def _score_valuation(m: dict) -> float:
    """Score valuation attractiveness. Cheap = positive, expensive = negative."""
    cfg = FUNDAMENTAL["stock"]
    scores = []

    pe = m.get("pe_ratio", 0)
    if pe and pe > 0:
        # Lower P/E than fair value is better
        scores.append(clamp((cfg["pe_fair_value"] - pe) / cfg["pe_fair_value"]))

    pb = m.get("pb_ratio", 0)
    if pb and pb > 0:
        scores.append(clamp((cfg["pb_fair_value"] - pb) / cfg["pb_fair_value"]))

    ev_ebitda = m.get("ev_ebitda", 0)
    if ev_ebitda and ev_ebitda > 0:
        # Below 15 is attractive, above 25 is expensive
        scores.append(clamp((15 - ev_ebitda) / 15))

    fcf_yield = m.get("fcf_yield", 0)
    if fcf_yield:
        # Higher FCF yield is better
        scores.append(clamp(fcf_yield / 0.10))  # 10% yield = max score

    return float(np.mean(scores)) if scores else 0.0


def _score_profitability(m: dict) -> float:
    """Score company profitability."""
    cfg = FUNDAMENTAL["stock"]
    scores = []

    roe = m.get("roe", 0)
    if roe:
        scores.append(clamp(roe / (cfg["roe_threshold"] * 2)))

    roa = m.get("roa", 0)
    if roa:
        scores.append(clamp(roa / 0.10))  # 10% ROA = good

    gm = m.get("gross_margin", 0)
    if gm:
        scores.append(clamp(gm / 0.50))  # 50%+ gross margin = excellent

    om = m.get("operating_margin", 0)
    if om:
        scores.append(clamp(om / 0.20))

    nm = m.get("net_margin", 0)
    if nm:
        scores.append(clamp(nm / 0.15))

    return float(np.mean(scores)) if scores else 0.0


def _score_growth(m: dict) -> float:
    """Score revenue and earnings growth."""
    cfg = FUNDAMENTAL["stock"]
    scores = []

    rev_g = m.get("revenue_growth") or m.get("revenue_growth_yoy", 0)
    if rev_g:
        scores.append(clamp(rev_g / 0.20))  # 20% growth = great

    earn_g = m.get("earnings_growth", 0)
    if earn_g:
        scores.append(clamp(earn_g / 0.20))

    return float(np.mean(scores)) if scores else 0.0


def _score_financial_health(m: dict) -> float:
    """Score balance sheet strength."""
    cfg = FUNDAMENTAL["stock"]
    scores = []

    de = m.get("debt_to_equity", 0)
    if de is not None and de >= 0:
        # Lower D/E is better
        scores.append(clamp(1 - de / cfg["debt_equity_max"]))

    cr = m.get("current_ratio", 0)
    if cr:
        # Above 1.5 is healthy
        scores.append(clamp((cr - 1.0) / 1.0))

    qr = m.get("quick_ratio", 0)
    if qr:
        scores.append(clamp((qr - 1.0) / 1.0))

    fcf = m.get("free_cashflow", 0)
    scores.append(1.0 if fcf and fcf > 0 else -0.5)

    return float(np.mean(scores)) if scores else 0.0


def score_stock(symbol: str, metrics: dict | None = None) -> dict:
    """
    Compute a fundamental score for a stock in [-1, +1].

    Args:
        symbol: Stock ticker symbol
        metrics: Pre-computed metrics dict (optional, fetches if not provided)

    Returns:
        dict with sub-scores and final 'fundamental_score'
    """
    m = metrics or compute_stock_metrics(symbol)

    val_score = _score_valuation(m)
    prof_score = _score_profitability(m)
    growth_score = _score_growth(m)
    health_score = _score_financial_health(m)

    # Weighted combination
    fundamental_score = (
        val_score * 0.30 +
        prof_score * 0.30 +
        growth_score * 0.25 +
        health_score * 0.15
    )

    return {
        "symbol": symbol,
        "valuation_score": round(val_score, 4),
        "profitability_score": round(prof_score, 4),
        "growth_score": round(growth_score, 4),
        "health_score": round(health_score, 4),
        "fundamental_score": round(clamp(fundamental_score), 4),
        "metrics": m,
    }
