"""
analysis/sentiment/news_sentiment.py

Fetches news from NewsAPI and crypto-specific sources,
performs NLP sentiment analysis, and returns per-asset news sentiment scores.
"""

import re
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import NEWS_API_KEY, SENTIMENT
from utils.api_utils import APISession, safe_float
from utils.helpers import clamp, utc_now
from utils.logger import get_logger

log = get_logger("news_sentiment")

_analyzer = SentimentIntensityAnalyzer()

# NewsAPI base
NEWSAPI_BASE = "https://newsapi.org/v2"

# Crypto news sources
CRYPTO_NEWS_SOURCES = [
    "coindesk.com",
    "cointelegraph.com",
    "decrypt.co",
    "theblock.co",
    "cryptonews.com",
]

# Keyword maps for assets
KEYWORD_MAP = {
    "BTC/USDT": ["bitcoin", "btc", "satoshi", "crypto", "digital gold"],
    "ETH/USDT": ["ethereum", "eth", "ether", "defi", "smart contract"],
    "SOL/USDT": ["solana", "sol"],
    "ADA/USDT": ["cardano", "ada"],
    "XRP/USDT": ["ripple", "xrp"],
    "AAPL":     ["apple", "aapl", "iphone", "mac", "tim cook"],
    "MSFT":     ["microsoft", "msft", "azure", "windows", "satya nadella"],
    "GOOGL":    ["google", "alphabet", "googl", "search", "youtube"],
    "TSLA":     ["tesla", "tsla", "elon musk", "electric vehicle", "ev"],
    "NVDA":     ["nvidia", "nvda", "gpu", "ai chip", "jensen huang"],
    "EUR_USD":  ["euro", "eur/usd", "ecb", "eurozone", "european central bank"],
    "GBP_USD":  ["pound", "gbp/usd", "bank of england", "boe", "brexit"],
    "USD_JPY":  ["yen", "usd/jpy", "bank of japan", "boj"],
    "GC=F":     ["gold", "xau", "precious metal", "safe haven"],
    "CL=F":     ["oil", "crude", "opec", "wti", "brent", "petroleum"],
    "NG=F":     ["natural gas", "lng", "gas prices"],
}


# ─────────────────────────────────────────────────────────────────────────────
# FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_newsapi_articles(query: str, hours_back: int | None = None) -> list[dict]:
    """
    Fetch articles from NewsAPI matching a query.
    Returns list of article dicts with title, description, publishedAt.
    """
    if not NEWS_API_KEY:
        log.debug("NEWS_API_KEY not set; skipping NewsAPI fetch")
        return []

    hours_back = hours_back or SENTIMENT["news_lookback_hours"]
    from_dt = (utc_now() - timedelta(hours=hours_back)).isoformat()

    try:
        session = APISession(NEWSAPI_BASE, "newsapi",
                             headers={"Authorization": f"Bearer {NEWS_API_KEY}"})
        data = session.get("everything", params={
            "q": query,
            "from": from_dt,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 50,
        })
        return data.get("articles", []) if data else []
    except Exception as e:
        log.warning(f"NewsAPI fetch failed for '{query}': {e}")
        return []


def fetch_crypto_news(symbol: str) -> list[dict]:
    """
    Fetch crypto-specific news from CoinDesk and CoinTelegraph RSS feeds.
    Uses a simplified HTTP fetch since they don't require API keys.
    """
    import feedparser
    articles = []
    feeds = {
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
    }
    base_symbol = symbol.split("/")[0].lower()

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
                if base_symbol in text or "crypto" in text or "bitcoin" in text:
                    articles.append({
                        "title": entry.get("title", ""),
                        "description": entry.get("summary", ""),
                        "source": source,
                        "publishedAt": entry.get("published", ""),
                    })
        except Exception as e:
            log.debug(f"RSS feed {source} failed: {e}")

    return articles


# ─────────────────────────────────────────────────────────────────────────────
# SENTIMENT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def score_text(text: str) -> float:
    """
    Score a piece of text in [-1, +1] using VADER.
    VADER is fast, no GPU needed, and well-calibrated for financial headlines.
    """
    if not text or not text.strip():
        return 0.0
    scores = _analyzer.polarity_scores(text)
    return float(scores["compound"])  # already in [-1, +1]


def is_relevant(text: str, keywords: list[str]) -> bool:
    """Check if text is relevant to the given keywords."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def score_article(article: dict) -> float:
    """Score a news article by analyzing title + description."""
    title = article.get("title", "") or ""
    description = article.get("description", "") or article.get("summary", "") or ""
    # Title gets 2x weight
    combined_score = (score_text(title) * 2 + score_text(description)) / 3
    return combined_score


def aggregate_news_sentiment(articles: list[dict], decay_half_life_hours: float = 12) -> dict:
    """
    Aggregate article sentiments with time-decay weighting.
    More recent articles get higher weight.

    Returns:
        dict with 'score', 'article_count', 'avg_score', 'std_score'
    """
    if not articles:
        return {
            "score": 0.0,
            "article_count": 0,
            "avg_score": 0.0,
            "std_score": 0.0,
            "signal_strength": 0.0,
        }

    now = utc_now()
    scores = []
    weights = []

    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}"
        sentiment = score_article(article)

        # Time-decay weight
        pub_str = article.get("publishedAt") or article.get("published", "")
        try:
            if pub_str:
                pub_dt = datetime.fromisoformat(
                    pub_str.replace("Z", "+00:00")
                ).replace(tzinfo=timezone.utc)
                age_hours = (now - pub_dt).total_seconds() / 3600
                weight = 2 ** (-age_hours / decay_half_life_hours)
            else:
                weight = 0.5
        except Exception:
            weight = 0.5

        scores.append(sentiment)
        weights.append(weight)

    weights_arr = np.array(weights)
    scores_arr = np.array(scores)

    weighted_score = float(np.average(scores_arr, weights=weights_arr))
    avg_score = float(np.mean(scores_arr))
    std_score = float(np.std(scores_arr))
    # Signal strength: more articles + stronger agreement = higher strength
    agreement = 1 - std_score  # low std = high agreement
    signal_strength = min(1.0, len(articles) / 20) * max(0, agreement)

    return {
        "score": clamp(weighted_score),
        "article_count": len(articles),
        "avg_score": clamp(avg_score),
        "std_score": std_score,
        "signal_strength": signal_strength,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def get_news_sentiment(symbol: str, market_type: str = "crypto") -> dict:
    """
    Fetch and analyze news sentiment for a given asset.

    Returns:
        dict with 'news_sentiment_score' in [-1, +1] and metadata
    """
    keywords = KEYWORD_MAP.get(symbol, [symbol.split("/")[0].lower()])
    query = " OR ".join(f'"{kw}"' for kw in keywords[:3])

    articles: list[dict] = []

    # Fetch from NewsAPI
    newsapi_articles = fetch_newsapi_articles(query)
    relevant_newsapi = [
        a for a in newsapi_articles
        if is_relevant(
            f"{a.get('title', '')} {a.get('description', '')}",
            keywords
        )
    ]
    articles.extend(relevant_newsapi)

    # Fetch crypto-specific news
    if market_type == "crypto":
        crypto_articles = fetch_crypto_news(symbol)
        articles.extend(crypto_articles)

    min_articles = SENTIMENT["min_articles_for_signal"]
    if len(articles) < min_articles:
        log.debug(
            f"Only {len(articles)} articles for {symbol} (min {min_articles}); "
            "returning neutral sentiment"
        )
        return {
            "symbol": symbol,
            "news_sentiment_score": 0.0,
            "article_count": len(articles),
            "signal_strength": 0.0,
        }

    agg = aggregate_news_sentiment(articles)

    return {
        "symbol": symbol,
        "news_sentiment_score": agg["score"],
        "article_count": agg["article_count"],
        "avg_score": agg["avg_score"],
        "std_score": agg["std_score"],
        "signal_strength": agg["signal_strength"],
    }
