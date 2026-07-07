"""
analysis/fundamental/crypto_fundamentals.py

On-chain metrics and project fundamentals for cryptocurrency assets.
Uses Glassnode, CoinGecko, and Etherscan APIs with mock fallbacks.
"""

import numpy as np
from typing import Optional
from config import (
    GLASSNODE_API_KEY, COINGECKO_API_KEY,
    ETHERSCAN_API_KEY, FUNDAMENTAL,
)
from utils.api_utils import APISession, safe_float, extract_nested
from utils.helpers import safe_divide, clamp, normalize
from utils.logger import get_logger

log = get_logger("crypto_fundamentals")



# DATA FETCHERS


def fetch_coingecko_data(coin_id: str) -> dict:
    """
    Fetch market data and project info from CoinGecko.
    coin_id: e.g. 'bitcoin', 'ethereum', 'solana'
    """
    try:
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
        session = APISession("https://api.coingecko.com/api/v3", "coingecko", headers=headers)
        data = session.get(f"coins/{coin_id}", params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "true",
        })
        return data or {}
    except Exception as e:
        log.warning(f"CoinGecko fetch failed for {coin_id}: {e}")
        return {}


def fetch_glassnode_metric(asset: str, metric_path: str) -> float:
    """
    Fetch a single on-chain metric from Glassnode.
    Returns the latest value or 0.0 on failure.
    """
    if not GLASSNODE_API_KEY:
        return 0.0
    try:
        session = APISession("https://api.glassnode.com/v1/metrics", "glassnode")
        data = session.get(metric_path, params={
            "a": asset.upper(),
            "api_key": GLASSNODE_API_KEY,
            "f": "JSON",
            "i": "24h",
        })
        if data and isinstance(data, list) and len(data) > 0:
            return safe_float(data[-1].get("v", 0))
        return 0.0
    except Exception as e:
        log.warning(f"Glassnode metric {metric_path} failed for {asset}: {e}")
        return 0.0


def fetch_etherscan_metrics(contract: str | None = None) -> dict:
    """Fetch ETH/ERC-20 token metrics from Etherscan."""
    if not ETHERSCAN_API_KEY:
        return {}
    try:
        session = APISession("https://api.etherscan.io/api", "etherscan")
        # ETH supply
        supply_data = session.get("", params={
            "module": "stats",
            "action": "ethsupply",
            "apikey": ETHERSCAN_API_KEY,
        })
        supply = safe_float(extract_nested(supply_data, "result")) / 1e18

        # Total transactions
        tx_data = session.get("", params={
            "module": "stats",
            "action": "dailytx",
            "apikey": ETHERSCAN_API_KEY,
        })
        return {
            "eth_supply": supply,
            "tx_count": safe_float(extract_nested(tx_data, "result", default=0)),
        }
    except Exception as e:
        log.warning(f"Etherscan fetch failed: {e}")
        return {}


def _mock_onchain_metrics(symbol: str) -> dict:
    """
    Generate plausible mock on-chain metrics when APIs are unavailable.
    Used for testing and development.
    """
    import random
    rng = random.Random(hash(symbol))
    return {
        "active_addresses": rng.randint(300_000, 1_200_000),
        "transaction_count": rng.randint(200_000, 800_000),
        "hash_rate": rng.uniform(400, 650) if "BTC" in symbol else 0,
        "exchange_inflow": rng.uniform(5000, 30000),
        "exchange_outflow": rng.uniform(5000, 30000),
        "nvt_ratio": rng.uniform(40, 200),
        "mvrv_ratio": rng.uniform(0.8, 4.0),
        "stablecoin_ratio": rng.uniform(0.05, 0.20),
        "tvl": rng.uniform(1e9, 50e9) if symbol not in ["BTC/USDT"] else 0,
    }



# METRICS COMPUTATION


_SYMBOL_TO_COINGECKO = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "BNB/USDT": "binancecoin",
    "SOL/USDT": "solana",
    "ADA/USDT": "cardano",
    "XRP/USDT": "ripple",
    "DOGE/USDT": "dogecoin",
    "AVAX/USDT": "avalanche-2",
}

_SYMBOL_TO_GLASSNODE = {
    "BTC/USDT": "BTC",
    "ETH/USDT": "ETH",
}


def compute_crypto_metrics(symbol: str) -> dict:
    """
    Aggregate on-chain and project metrics for a crypto asset.
    """
    metrics: dict = {"symbol": symbol}
    coin_id = _SYMBOL_TO_COINGECKO.get(symbol, symbol.replace("/USDT", "").lower())
    gl_asset = _SYMBOL_TO_GLASSNODE.get(symbol)

    # CoinGecko data
    cg_data = fetch_coingecko_data(coin_id)
    market_data = cg_data.get("market_data", {})
    dev_data = cg_data.get("developer_data", {})
    community_data = cg_data.get("community_data", {})

    # Market cap and volume
    metrics["market_cap"] = safe_float(extract_nested(market_data, "market_cap", "usd"))
    metrics["volume_24h"] = safe_float(extract_nested(market_data, "total_volume", "usd"))
    metrics["circulating_supply"] = safe_float(market_data.get("circulating_supply"))
    metrics["max_supply"] = safe_float(market_data.get("max_supply")) or None
    metrics["total_supply"] = safe_float(market_data.get("total_supply"))

    # Supply ratio (circulating / max)
    if metrics["max_supply"]:
        metrics["supply_ratio"] = safe_divide(
            metrics["circulating_supply"], metrics["max_supply"]
        )
    else:
        metrics["supply_ratio"] = None

    # Price changes
    metrics["price_change_24h"] = safe_float(
        extract_nested(market_data, "price_change_percentage_24h")
    ) / 100
    metrics["price_change_7d"] = safe_float(
        extract_nested(market_data, "price_change_percentage_7d")
    ) / 100
    metrics["price_change_30d"] = safe_float(
        extract_nested(market_data, "price_change_percentage_30d")
    ) / 100

    # ATH drawdown
    ath = safe_float(extract_nested(market_data, "ath", "usd"))
    current = safe_float(extract_nested(market_data, "current_price", "usd"))
    if ath > 0 and current > 0:
        metrics["ath_drawdown"] = (current - ath) / ath  # negative = below ATH

    # Developer activity
    metrics["github_stars"] = safe_float(dev_data.get("stars"))
    metrics["github_forks"] = safe_float(dev_data.get("forks"))
    metrics["github_commits_4w"] = safe_float(dev_data.get("commit_count_4_weeks"))
    metrics["github_contributors"] = safe_float(dev_data.get("pull_request_contributors"))

    # Community
    metrics["twitter_followers"] = safe_float(community_data.get("twitter_followers"))
    metrics["reddit_subscribers"] = safe_float(community_data.get("reddit_subscribers"))

    # On-chain metrics (Glassnode if available, else mock)
    if gl_asset and GLASSNODE_API_KEY:
        metrics["active_addresses"] = fetch_glassnode_metric(gl_asset, "addresses/active_count")
        metrics["transaction_count"] = fetch_glassnode_metric(gl_asset, "transactions/count")
        metrics["exchange_inflow"] = fetch_glassnode_metric(gl_asset, "transactions/transfers_volume_exchanges_net")
        metrics["mvrv_ratio"] = fetch_glassnode_metric(gl_asset, "market/mvrv")
        metrics["nvt_ratio"] = fetch_glassnode_metric(gl_asset, "indicators/nvt")
        if "BTC" in symbol:
            metrics["hash_rate"] = fetch_glassnode_metric(gl_asset, "mining/hash_rate_mean")
    else:
        log.debug(f"Using mock on-chain data for {symbol}")
        on_chain = _mock_onchain_metrics(symbol)
        metrics.update(on_chain)

    return metrics



# SCORING


def _score_network_value(m: dict) -> float:
    """Score NVT and MVRV ratios."""
    cfg = FUNDAMENTAL["crypto"]
    scores = []

    nvt = m.get("nvt_ratio", 0)
    if nvt > 0:
        if nvt > cfg["nvt_overbought"]:
            scores.append(-1.0)
        elif nvt < cfg["nvt_oversold"]:
            scores.append(1.0)
        else:
            scores.append(clamp((cfg["nvt_oversold"] - nvt) / cfg["nvt_oversold"]))

    mvrv = m.get("mvrv_ratio", 0)
    if mvrv > 0:
        if mvrv > cfg["mvrv_overbought"]:
            scores.append(-1.0)
        elif mvrv < cfg["mvrv_oversold"]:
            scores.append(1.0)
        else:
            # Between oversold and overbought: score linearly
            mid = (cfg["mvrv_overbought"] + cfg["mvrv_oversold"]) / 2
            scores.append(clamp((mid - mvrv) / mid))

    return float(np.mean(scores)) if scores else 0.0


def _score_onchain_activity(m: dict) -> float:
    """Score network activity (active addresses, tx count)."""
    scores = []

    # Exchange flow: net outflow = bullish (leaving exchanges)
    inflow = m.get("exchange_inflow", 0)
    outflow = m.get("exchange_outflow", 0)
    if inflow and outflow:
        net_flow = outflow - inflow
        scores.append(clamp(net_flow / max(inflow, outflow, 1)))

    # Price momentum over 30d
    p30d = m.get("price_change_30d", 0)
    if p30d:
        scores.append(clamp(p30d * 2))  # 50% gain → +1 score

    return float(np.mean(scores)) if scores else 0.0


def _score_developer_activity(m: dict) -> float:
    """Score GitHub / developer activity."""
    cfg = FUNDAMENTAL["crypto"]
    scores = []

    commits = m.get("github_commits_4w", 0)
    if commits:
        # Normalize: 200+ commits in 4 weeks is very active
        scores.append(clamp(commits / 200))

    contributors = m.get("github_contributors", 0)
    if contributors:
        scores.append(clamp(contributors / 50))

    stars = m.get("github_stars", 0)
    if stars:
        scores.append(clamp(stars / 10000))

    return float(np.mean(scores)) if scores else 0.0


def _score_tokenomics(m: dict) -> float:
    """Score tokenomics: supply ratio, inflation, etc."""
    scores = []

    supply_ratio = m.get("supply_ratio")
    if supply_ratio is not None:
        # Fully circulating = neutral; below 50% = potentially inflationary (bearish)
        scores.append(clamp(supply_ratio - 0.5) * 2)

    ath_drawdown = m.get("ath_drawdown", 0)
    if ath_drawdown:
        # Deep drawdown could mean value opportunity (contrarian)
        scores.append(clamp(ath_drawdown))  # already negative

    return float(np.mean(scores)) if scores else 0.0


def score_crypto(symbol: str, metrics: dict | None = None) -> dict:
    """
    Compute fundamental score for a crypto asset in [-1, +1].
    """
    m = metrics or compute_crypto_metrics(symbol)

    nv_score = _score_network_value(m)
    activity_score = _score_onchain_activity(m)
    dev_score = _score_developer_activity(m)
    tokenomics_score = _score_tokenomics(m)

    fundamental_score = (
        nv_score * 0.35 +
        activity_score * 0.30 +
        dev_score * 0.20 +
        tokenomics_score * 0.15
    )

    return {
        "symbol": symbol,
        "network_value_score": round(nv_score, 4),
        "onchain_activity_score": round(activity_score, 4),
        "developer_score": round(dev_score, 4),
        "tokenomics_score": round(tokenomics_score, 4),
        "fundamental_score": round(clamp(fundamental_score), 4),
        "metrics": m,
    }
