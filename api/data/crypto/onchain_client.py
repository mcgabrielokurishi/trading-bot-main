"""
data/crypto/onchain_client.py

On-chain data aggregator: Glassnode, Etherscan, and mock fallbacks.
"""

import time
import pandas as pd
from typing import Optional
from config import GLASSNODE_API_KEY, ETHERSCAN_API_KEY
from utils.api_utils import APISession, safe_float, extract_nested
from utils.logger import get_logger

log = get_logger("onchain_client")

GLASSNODE_BASE = "https://api.glassnode.com/v1/metrics"
ETHERSCAN_BASE = "https://api.etherscan.io/api"

GLASSNODE_METRICS = {
    "active_addresses":    "addresses/active_count",
    "new_addresses":       "addresses/new_non_zero_count",
    "transaction_count":   "transactions/count",
    "transaction_volume":  "transactions/transfers_volume_sum",
    "exchange_inflow":     "transactions/transfers_volume_exchanges_net",
    "mvrv_ratio":          "market/mvrv",
    "nvt_ratio":           "indicators/nvt",
    "sopr":                "indicators/sopr",
    "hash_rate":           "mining/hash_rate_mean",
    "mining_difficulty":   "mining/difficulty_latest",
    "stablecoin_ratio":    "indicators/ssr",
}


def _glassnode_session() -> Optional[APISession]:
    if not GLASSNODE_API_KEY:
        return None
    return APISession(GLASSNODE_BASE, "glassnode")


def fetch_glassnode(asset: str, metric: str, interval: str = "24h") -> pd.Series:
    """
    Fetch a time-series metric from Glassnode.

    Args:
        asset: 'BTC' or 'ETH'
        metric: Metric path key from GLASSNODE_METRICS
        interval: Data interval '1h', '24h', '1w'

    Returns:
        pandas Series indexed by datetime
    """
    metric_path = GLASSNODE_METRICS.get(metric, metric)
    session = _glassnode_session()
    if not session:
        log.debug(f"Glassnode unavailable; returning empty series for {metric}")
        return pd.Series(dtype=float, name=metric)

    try:
        data = session.get(metric_path, params={
            "a": asset.upper(),
            "api_key": GLASSNODE_API_KEY,
            "f": "JSON",
            "i": interval,
        })
        if not data or not isinstance(data, list):
            return pd.Series(dtype=float, name=metric)

        ts = [d["t"] for d in data]
        vals = [safe_float(d.get("v")) for d in data]
        index = pd.to_datetime(ts, unit="s", utc=True)
        return pd.Series(vals, index=index, name=metric)
    except Exception as e:
        log.warning(f"Glassnode {metric} for {asset} failed: {e}")
        return pd.Series(dtype=float, name=metric)


def fetch_all_onchain_metrics(asset: str) -> dict:
    """
    Fetch all configured on-chain metrics for an asset.
    Returns dict of metric_name -> latest value.
    """
    result = {}
    for metric_name in GLASSNODE_METRICS:
        series = fetch_glassnode(asset, metric_name)
        if not series.empty:
            result[metric_name] = float(series.iloc[-1])
        else:
            result[metric_name] = None

    if not any(v is not None for v in result.values()):
        log.debug(f"All Glassnode metrics null for {asset}; using mock")
        return _mock_onchain(asset)

    return result


def _mock_onchain(asset: str) -> dict:
    """Return plausible mock on-chain metrics for testing."""
    import random
    rng = random.Random(hash(asset + str(int(time.time() / 86400))))
    base = {
        "BTC": {
            "active_addresses": rng.randint(800_000, 1_200_000),
            "new_addresses": rng.randint(300_000, 500_000),
            "transaction_count": rng.randint(250_000, 400_000),
            "transaction_volume": rng.uniform(5e9, 20e9),
            "exchange_inflow": rng.uniform(-500, 500),
            "mvrv_ratio": rng.uniform(1.2, 3.5),
            "nvt_ratio": rng.uniform(50, 150),
            "sopr": rng.uniform(0.98, 1.05),
            "hash_rate": rng.uniform(450, 650),
            "mining_difficulty": rng.uniform(70e12, 90e12),
            "stablecoin_ratio": rng.uniform(0.05, 0.15),
        },
        "ETH": {
            "active_addresses": rng.randint(400_000, 800_000),
            "new_addresses": rng.randint(100_000, 300_000),
            "transaction_count": rng.randint(900_000, 1_500_000),
            "transaction_volume": rng.uniform(3e9, 15e9),
            "exchange_inflow": rng.uniform(-200, 200),
            "mvrv_ratio": rng.uniform(0.9, 3.0),
            "nvt_ratio": rng.uniform(40, 120),
            "sopr": rng.uniform(0.97, 1.04),
            "hash_rate": 0,
            "mining_difficulty": 0,
            "stablecoin_ratio": rng.uniform(0.08, 0.20),
        },
    }
    return base.get(asset.upper(), base["BTC"])


# ─────────────────────────────────────────────────────────────────────────────
# ETHERSCAN
# ─────────────────────────────────────────────────────────────────────────────

def fetch_eth_gas_price() -> dict:
    """Fetch current ETH gas price from Etherscan."""
    if not ETHERSCAN_API_KEY:
        return {"safe": 20, "propose": 25, "fast": 35, "base_fee": 15}
    try:
        session = APISession(ETHERSCAN_BASE, "etherscan")
        data = session.get("", params={
            "module": "gastracker",
            "action": "gasoracle",
            "apikey": ETHERSCAN_API_KEY,
        })
        result = data.get("result", {})
        return {
            "safe": safe_float(result.get("SafeGasPrice")),
            "propose": safe_float(result.get("ProposeGasPrice")),
            "fast": safe_float(result.get("FastGasPrice")),
            "base_fee": safe_float(result.get("suggestBaseFee")),
        }
    except Exception as e:
        log.warning(f"Etherscan gas price fetch failed: {e}")
        return {"safe": 20, "propose": 25, "fast": 35, "base_fee": 15}


def fetch_token_supply(contract_address: str) -> float:
    """Fetch ERC-20 token circulating supply."""
    if not ETHERSCAN_API_KEY:
        return 0.0
    try:
        session = APISession(ETHERSCAN_BASE, "etherscan")
        data = session.get("", params={
            "module": "stats",
            "action": "tokensupply",
            "contractaddress": contract_address,
            "apikey": ETHERSCAN_API_KEY,
        })
        return safe_float(data.get("result", 0)) / 1e18
    except Exception as e:
        log.warning(f"Token supply fetch failed for {contract_address}: {e}")
        return 0.0
