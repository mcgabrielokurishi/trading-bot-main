"""
analysis/sentiment/social_sentiment.py

Reddit and Twitter/X social sentiment analysis.
Uses PRAW for Reddit and Twitter v2 Bearer token for X.
Falls back to mock data if credentials are unavailable.
"""

import re
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT,
    TWITTER_BEARER_TOKEN, SENTIMENT,
)
from utils.api_utils import APISession, safe_float
from utils.helpers import clamp, utc_now
from utils.logger import get_logger

log = get_logger("social_sentiment")
_analyzer = SentimentIntensityAnalyzer()


# ─────────────────────────────────────────────────────────────────────────────
# REDDIT
# ─────────────────────────────────────────────────────────────────────────────

REDDIT_SUBREDDITS = {
    "crypto":      ["CryptoCurrency", "Bitcoin", "ethereum", "altcoin"],
    "stocks":      ["wallstreetbets", "investing", "stocks", "SecurityAnalysis"],
    "forex":       ["Forex", "algotrading"],
    "commodities": ["investing", "Gold", "energy"],
}

SYMBOL_TO_KEYWORDS = {
    "BTC/USDT": ["bitcoin", "btc", "$btc", "#bitcoin"],
    "ETH/USDT": ["ethereum", "eth", "$eth", "#ethereum"],
    "SOL/USDT": ["solana", "sol", "$sol"],
    "ADA/USDT": ["cardano", "ada", "$ada"],
    "XRP/USDT": ["ripple", "xrp", "$xrp"],
    "DOGE/USDT": ["dogecoin", "doge", "$doge"],
    "AAPL":     ["apple", "aapl", "$aapl"],
    "MSFT":     ["microsoft", "msft", "$msft"],
    "TSLA":     ["tesla", "tsla", "$tsla", "elon"],
    "NVDA":     ["nvidia", "nvda", "$nvda"],
    "GOOGL":    ["google", "alphabet", "googl", "$googl"],
    "AMZN":     ["amazon", "amzn", "$amzn"],
    "EUR_USD":  ["eurusd", "eur/usd", "euro dollar"],
    "GBP_USD":  ["gbpusd", "gbp/usd", "cable"],
    "GC=F":     ["gold", "xau", "#gold"],
    "CL=F":     ["crude oil", "wti", "#oil", "petroleum"],
}


def _praw_client():
    """Create and return a PRAW Reddit client, or None if credentials missing."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return None
    try:
        import praw
        return praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
        )
    except Exception as e:
        log.warning(f"PRAW initialization failed: {e}")
        return None


def fetch_reddit_posts(
    symbol: str,
    market_type: str = "crypto",
    limit: int = 50,
    hours_back: int | None = None,
) -> list[dict]:
    """
    Fetch recent Reddit posts and comments relevant to an asset.
    Returns list of dicts with 'text', 'score', 'timestamp'.
    """
    hours_back = hours_back or SENTIMENT["social_lookback_hours"]
    keywords = SYMBOL_TO_KEYWORDS.get(symbol, [symbol.split("/")[0].lower()])
    subreddits = REDDIT_SUBREDDITS.get(market_type, ["investing"])

    reddit = _praw_client()
    if not reddit:
        log.debug("Reddit credentials not configured; returning mock data")
        return _mock_reddit_posts(symbol)

    posts = []
    cutoff = utc_now() - timedelta(hours=hours_back)

    try:
        for subreddit_name in subreddits[:3]:
            try:
                subreddit = reddit.subreddit(subreddit_name)
                for post in subreddit.search(
                    " OR ".join(keywords[:2]),
                    time_filter="day",
                    limit=limit // len(subreddits),
                    sort="new",
                ):
                    created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                    if created < cutoff:
                        continue

                    text = f"{post.title} {post.selftext or ''}"
                    if not any(kw.lower() in text.lower() for kw in keywords):
                        continue

                    posts.append({
                        "text": text[:500],  # cap length
                        "score": post.score,
                        "upvote_ratio": post.upvote_ratio,
                        "num_comments": post.num_comments,
                        "timestamp": post.created_utc,
                        "source": f"reddit/{subreddit_name}",
                    })

                    # Also grab top comments
                    try:
                        post.comments.replace_more(limit=0)
                        for comment in list(post.comments)[:5]:
                            if hasattr(comment, "body"):
                                posts.append({
                                    "text": comment.body[:300],
                                    "score": comment.score,
                                    "upvote_ratio": 0.5,
                                    "num_comments": 0,
                                    "timestamp": comment.created_utc,
                                    "source": f"reddit/{subreddit_name}/comment",
                                })
                    except Exception:
                        pass

            except Exception as e:
                log.debug(f"Reddit subreddit {subreddit_name} error: {e}")

    except Exception as e:
        log.warning(f"Reddit fetch failed for {symbol}: {e}")

    return posts


def _mock_reddit_posts(symbol: str) -> list[dict]:
    """Generate mock Reddit posts for testing."""
    import random
    rng = random.Random(hash(symbol + str(int(time.time() / 3600))))
    sentiment_pool = [
        (f"{symbol} looking bullish today! Strong support!", 0.7),
        (f"Bought more {symbol}, DCA strategy working", 0.4),
        (f"{symbol} is going to the moon! 🚀", 0.8),
        (f"Concerned about {symbol} fundamentals...", -0.3),
        (f"{symbol} seems range-bound, watching for breakout", 0.1),
        (f"Sold half my {symbol} position, taking profits", -0.1),
        (f"{symbol} bear market not over yet imo", -0.5),
        (f"Long term bullish on {symbol}", 0.6),
    ]
    posts = []
    for _ in range(rng.randint(5, 15)):
        text, _ = rng.choice(sentiment_pool)
        posts.append({
            "text": text,
            "score": rng.randint(1, 5000),
            "upvote_ratio": rng.uniform(0.5, 0.98),
            "num_comments": rng.randint(0, 200),
            "timestamp": time.time() - rng.uniform(0, 43200),
            "source": "reddit/mock",
        })
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# TWITTER / X
# ─────────────────────────────────────────────────────────────────────────────

def fetch_twitter_posts(symbol: str, limit: int = 50) -> list[dict]:
    """
    Fetch recent tweets about an asset using Twitter API v2.
    Returns list of post dicts with 'text', 'score' (likes), 'timestamp'.
    """
    if not TWITTER_BEARER_TOKEN:
        log.debug("TWITTER_BEARER_TOKEN not set; skipping Twitter fetch")
        return []

    keywords = SYMBOL_TO_KEYWORDS.get(symbol, [symbol.split("/")[0]])
    query_parts = [f'"{kw}"' for kw in keywords[:2]]
    query = f"({' OR '.join(query_parts)}) lang:en -is:retweet"

    try:
        session = APISession(
            "https://api.twitter.com/2",
            "newsapi",  # reuse rate limiter slot
            headers={"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"},
        )
        data = session.get("tweets/search/recent", params={
            "query": query,
            "max_results": min(limit, 100),
            "tweet.fields": "created_at,public_metrics",
            "sort_order": "recency",
        })
        tweets = data.get("data", []) if data else []
        posts = []
        for tweet in tweets:
            metrics = tweet.get("public_metrics", {})
            posts.append({
                "text": tweet.get("text", ""),
                "score": safe_float(metrics.get("like_count", 0)),
                "retweet_count": safe_float(metrics.get("retweet_count", 0)),
                "timestamp": time.time(),  # approximate
                "source": "twitter",
            })
        return posts
    except Exception as e:
        log.warning(f"Twitter fetch failed for {symbol}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────

def score_social_post(post: dict) -> float:
    """
    Score a social post.
    VADER score weighted by post engagement (score/upvotes).
    """
    text = post.get("text", "")
    raw_sentiment = float(_analyzer.polarity_scores(text)["compound"])

    # Weight by engagement (log scale)
    raw_score = post.get("score", 1)
    engagement_weight = np.log1p(max(0, raw_score)) / np.log1p(1000)
    engagement_weight = np.clip(engagement_weight, 0.1, 1.0)

    return raw_sentiment * float(engagement_weight)


def aggregate_social_sentiment(posts: list[dict]) -> dict:
    """Aggregate multiple social posts into a single sentiment signal."""
    if not posts:
        return {
            "score": 0.0,
            "post_count": 0,
            "bullish_pct": 0.0,
            "bearish_pct": 0.0,
            "signal_strength": 0.0,
        }

    scored = [score_social_post(p) for p in posts]
    arr = np.array(scored)

    weighted_score = float(np.mean(arr))
    bullish_pct = float((arr > 0.05).sum() / len(arr))
    bearish_pct = float((arr < -0.05).sum() / len(arr))
    signal_strength = min(1.0, len(posts) / 30) * (
        1 - float(np.std(arr.clip(-1, 1)))
    )

    return {
        "score": clamp(weighted_score),
        "post_count": len(posts),
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "neutral_pct": 1 - bullish_pct - bearish_pct,
        "signal_strength": max(0.0, signal_strength),
    }


def get_social_sentiment(symbol: str, market_type: str = "crypto") -> dict:
    """
    Fetch and aggregate social sentiment from Reddit and Twitter.

    Returns:
        dict with 'social_sentiment_score' in [-1, +1] and metadata
    """
    all_posts: list[dict] = []

    reddit_posts = fetch_reddit_posts(symbol, market_type)
    all_posts.extend(reddit_posts)

    twitter_posts = fetch_twitter_posts(symbol)
    all_posts.extend(twitter_posts)

    reddit_agg = aggregate_social_sentiment(reddit_posts)
    twitter_agg = aggregate_social_sentiment(twitter_posts)

    # Weighted combination: Reddit gets slightly more weight (richer text)
    if reddit_posts and twitter_posts:
        combined_score = reddit_agg["score"] * 0.55 + twitter_agg["score"] * 0.45
    elif reddit_posts:
        combined_score = reddit_agg["score"]
    elif twitter_posts:
        combined_score = twitter_agg["score"]
    else:
        combined_score = 0.0

    overall = aggregate_social_sentiment(all_posts)

    return {
        "symbol": symbol,
        "social_sentiment_score": clamp(combined_score),
        "reddit_score": reddit_agg["score"],
        "twitter_score": twitter_agg["score"],
        "reddit_posts": reddit_agg["post_count"],
        "twitter_posts": twitter_agg["post_count"],
        "total_posts": overall["post_count"],
        "bullish_pct": overall["bullish_pct"],
        "bearish_pct": overall["bearish_pct"],
        "signal_strength": overall["signal_strength"],
    }
