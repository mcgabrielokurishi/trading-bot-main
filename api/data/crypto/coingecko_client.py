"""
data/crypto/coingecko_client.py

CoinGecko API client for market data, coin lists, and trending assets.
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Optional
from config import COINGECKO_API_KEY, LOOKBACK_BARS
from utils.api_utils import APISession, safe_float
from utils.helpers import ohlcv_to_df, validate_ohlcv
from utils.logger import get_logger

log = get_logger("coingecko_client")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

SYMBOL_TO_ID = {
    "BTC/USDT": "bitcoin", "ETH/USDT": "ethereum",
    "BNB/USDT": "binancecoin", "SOL/USDT": "solana",
    "ADA/USDT": "cardano", "XRP/USDT": "ripple",
    "DOGE/USDT": "dogecoin", "AVAX/USDT": "avalanche-2",
    "DOT/USDT": "polkadot", "LINK/USDT": "chainlink",
    "MATIC/USDT": "matic-network", "LTC/USDT": "litecoin",
}


def _session() -> APISession:
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return APISession(COINGECKO_BASE, "coingecko", headers=headers)


def fetch_ohlcv(
    symbol: str,
    days: int = 90,
    vs_currency: str = "usd",
) -> pd.DataFrame:
    """
    Fetch OHLCV data from CoinGecko.

    Note: CoinGecko returns OHLCV in 4h candles for 1-90 days,
    daily for 91-365 days. No minute-level data on free tier.
    """
    coin_id = SYMBOL_TO_ID.get(symbol, symbol.replace("/USDT", "").lower())
    try:
        session = _session()
        data = session.get(f"coins/{coin_id}/ohlc", params={
            "vs_currency": vs_currency,
            "days": days,
        })
        if not data:
            raise ValueError("Empty response from CoinGecko OHLC")

        # CoinGecko returns [timestamp_ms, open, high, low, close]
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df["volume"] = 0.0  # CoinGecko OHLC doesn't include volume
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.sort_index(inplace=True)
        log.debug(f"CoinGecko: fetched {len(df)} candles for {symbol}")
        return df
    except Exception as e:
        log.warning(f"CoinGecko OHLCV fetch failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_market_chart(
    symbol: str,
    days: int = 90,
    vs_currency: str = "usd",
) -> pd.DataFrame:
    """
    Fetch price/volume/market-cap time series from CoinGecko.
    Returns DataFrame with [price, market_cap, volume] columns.
    """
    coin_id = SYMBOL_TO_ID.get(symbol, symbol.replace("/USDT", "").lower())
    try:
        session = _session()
        data = session.get(f"coins/{coin_id}/market_chart", params={
            "vs_currency": vs_currency,
            "days": days,
        })
        if not data:
            return pd.DataFrame()

        prices = data.get("prices", [])
        volumes = data.get("total_volumes", [])
        market_caps = data.get("market_caps", [])

        df_price = pd.DataFrame(prices, columns=["timestamp", "price"])
        df_vol = pd.DataFrame(volumes, columns=["timestamp", "volume"])
        df_mc = pd.DataFrame(market_caps, columns=["timestamp", "market_cap"])

        df = df_price.merge(df_vol, on="timestamp").merge(df_mc, on="timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        log.warning(f"CoinGecko market chart failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_coin_info(symbol: str) -> dict:
    """Fetch comprehensive coin information."""
    coin_id = SYMBOL_TO_ID.get(symbol, symbol.replace("/USDT", "").lower())
    try:
        session = _session()
        return session.get(f"coins/{coin_id}", params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "true",
        }) or {}
    except Exception as e:
        log.warning(f"CoinGecko coin info failed for {symbol}: {e}")
        return {}


def fetch_global_market_data() -> dict:
    """Fetch global crypto market data (total market cap, dominance, etc.)."""
    try:
        session = _session()
        data = session.get("global") or {}
        return data.get("data", {})
    except Exception as e:
        log.warning(f"CoinGecko global data failed: {e}")
        return {}


def fetch_trending_coins() -> list[dict]:
    """Fetch trending coins from CoinGecko."""
    try:
        session = _session()
        data = session.get("search/trending") or {}
        return data.get("coins", [])
    except Exception as e:
        log.warning(f"CoinGecko trending fetch failed: {e}")
        return []


def fetch_top_coins(limit: int = 50) -> list[dict]:
    """Fetch top coins by market cap."""
    try:
        session = _session()
        return session.get("coins/markets", params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h,7d,30d",
        }) or []
    except Exception as e:
        log.warning(f"CoinGecko top coins fetch failed: {e}")
        return []
