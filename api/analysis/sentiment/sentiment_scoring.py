"""
analysis/sentiment/sentiment_scoring.py

Combines news, social, and indicator-based sentiment into a single
normalized sentiment score in [-1, +1].
"""

from config import SENTIMENT
from utils.helpers import clamp, weighted_average
from utils.logger import get_logger
from analysis.sentiment.news_sentiment import get_news_sentiment
from analysis.sentiment.social_sentiment import get_social_sentiment
from analysis.sentiment.sentiment_indicators import get_sentiment_indicators

log = get_logger("sentiment_scoring")


def get_sentiment_score(symbol: str, market_type: str = "crypto") -> dict:
    """
    Compute unified sentiment score for an asset.

    Combines:
    - News sentiment (NewsAPI + crypto RSS)
    - Social sentiment (Reddit + Twitter)
    - Market-structure indicators (Fear&Greed, VIX, Put/Call, COT)

    Returns:
        dict with 'sentiment_score' in [-1, +1] and sub-scores
    """
    log.info(f"Computing sentiment for {symbol} ({market_type})")

    # Gather all sentiment sources
    news = get_news_sentiment(symbol, market_type)
    social = get_social_sentiment(symbol, market_type)
    indicators = get_sentiment_indicators(symbol, market_type)

    news_score = news.get("news_sentiment_score", 0.0)
    social_score = social.get("social_sentiment_score", 0.0)
    indicator_score = indicators.get("indicator_sentiment_score", 0.0)

    # Adjust weights by signal strength (weak signals contribute less)
    news_strength = news.get("signal_strength", 0.5)
    social_strength = social.get("signal_strength", 0.5)

    base_news_w = SENTIMENT["news_weight"]
    base_social_w = SENTIMENT["social_weight"]
    base_indicator_w = SENTIMENT["indicators_weight"]

    # Scale weights by signal availability
    eff_news_w = base_news_w * news_strength
    eff_social_w = base_social_w * social_strength
    eff_indicator_w = base_indicator_w  # indicators always available

    total_w = eff_news_w + eff_social_w + eff_indicator_w
    if total_w == 0:
        sentiment_score = 0.0
    else:
        sentiment_score = (
            news_score * eff_news_w +
            social_score * eff_social_w +
            indicator_score * eff_indicator_w
        ) / total_w

    return {
        "symbol": symbol,
        "market_type": market_type,
        "sentiment_score": round(clamp(sentiment_score), 4),
        "news_sentiment_score": round(news_score, 4),
        "social_sentiment_score": round(social_score, 4),
        "indicator_sentiment_score": round(indicator_score, 4),
        "news_articles": news.get("article_count", 0),
        "social_posts": social.get("total_posts", 0),
        "fear_greed_index": indicators.get("fear_greed_index", 50),
        "vix": indicators.get("vix", 20),
        "weights_used": {
            "news": round(eff_news_w / max(total_w, 1e-6), 3),
            "social": round(eff_social_w / max(total_w, 1e-6), 3),
            "indicators": round(eff_indicator_w / max(total_w, 1e-6), 3),
        },
    }
