"""
config.py — Central configuration for the Multi-Market Trading Bot.

All parameters are documented with type hints and clear comments.
Override any value via environment variables or .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).parent

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT
# ─────────────────────────────────────────────────────────────────────────────
TRADING_MODE: str = os.getenv("TRADING_MODE", "paper")   # "paper" | "live"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR: Path = BASE_DIR / "logs"
DB_URL: str = os.getenv("DB_URL", f"sqlite:///{BASE_DIR}/trading_bot.db")

# ─────────────────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────────────────
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY: str = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET: bool = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")
GLASSNODE_API_KEY: str = os.getenv("GLASSNODE_API_KEY", "")
ETHERSCAN_API_KEY: str = os.getenv("ETHERSCAN_API_KEY", "")
LUNARCRUSH_API_KEY: str = os.getenv("LUNARCRUSH_API_KEY", "")

ALPHA_VANTAGE_API_KEY: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")
IEX_CLOUD_API_KEY: str = os.getenv("IEX_CLOUD_API_KEY", "")
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")

ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

OANDA_API_KEY: str = os.getenv("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID: str = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT: str = os.getenv("OANDA_ENVIRONMENT", "practice")  # "practice" | "live"

EIA_API_KEY: str = os.getenv("EIA_API_KEY", "")
NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")
TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "trading_bot/1.0")

# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE — Assets to trade
# ─────────────────────────────────────────────────────────────────────────────
CRYPTO_SYMBOLS: list[str] = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
    "ADA/USDT", "XRP/USDT", "DOGE/USDT", "AVAX/USDT",
]

STOCK_SYMBOLS: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
    "NVDA", "META", "JPM", "JNJ", "XOM",
]

FOREX_PAIRS: list[str] = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD",
    "USD_CAD", "USD_CHF", "NZD_USD", "EUR_GBP",
]

COMMODITY_SYMBOLS: list[str] = [
    "GC=F",   # Gold
    "SI=F",   # Silver
    "CL=F",   # Crude Oil (WTI)
    "NG=F",   # Natural Gas
    "ZC=F",   # Corn
    "ZW=F",   # Wheat
    "HG=F",   # Copper
    "PL=F",   # Platinum
]

# ─────────────────────────────────────────────────────────────────────────────
# TIMEFRAMES
# ─────────────────────────────────────────────────────────────────────────────
TIMEFRAMES: list[str] = ["15m", "1h", "4h", "1d"]
PRIMARY_TIMEFRAME: str = "1h"
LOOKBACK_BARS: int = 500  # bars of history to fetch per timeframe

# ─────────────────────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS — all configurable
# ─────────────────────────────────────────────────────────────────────────────
INDICATORS = {
    # Moving Averages
    "SMA_PERIODS": [10, 20, 50, 100, 200],
    "EMA_PERIODS": [9, 21, 55, 100, 200],
    "WMA_PERIOD": 20,
    "HMA_PERIOD": 20,

    # Ichimoku
    "ICHIMOKU_TENKAN": 9,
    "ICHIMOKU_KIJUN": 26,
    "ICHIMOKU_SENKOU_B": 52,
    "ICHIMOKU_DISPLACEMENT": 26,

    # MACD
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,

    # RSI
    "RSI_PERIOD": 14,
    "RSI_OVERBOUGHT": 70,
    "RSI_OVERSOLD": 30,

    # Stochastic
    "STOCH_K": 14,
    "STOCH_D": 3,
    "STOCH_SMOOTH": 3,
    "STOCH_OVERBOUGHT": 80,
    "STOCH_OVERSOLD": 20,

    # Bollinger Bands
    "BB_PERIOD": 20,
    "BB_STD": 2.0,
    "BB_SQUEEZE_THRESHOLD": 0.02,  # bandwidth threshold for squeeze

    # Keltner Channels
    "KC_PERIOD": 20,
    "KC_MULTIPLIER": 1.5,

    # Donchian Channels
    "DC_PERIOD": 20,

    # ATR
    "ATR_PERIOD": 14,

    # ADX
    "ADX_PERIOD": 14,
    "ADX_TREND_THRESHOLD": 25,

    # CCI
    "CCI_PERIOD": 20,

    # Williams %R
    "WILLIAMS_PERIOD": 14,

    # ROC
    "ROC_PERIOD": 12,

    # Momentum
    "MOM_PERIOD": 10,

    # Awesome Oscillator
    "AO_FAST": 5,
    "AO_SLOW": 34,

    # OBV, MFI, CMF
    "MFI_PERIOD": 14,
    "CMF_PERIOD": 20,

    # VWAP
    "VWAP_SESSION": "1d",

    # Parabolic SAR
    "PSAR_START": 0.02,
    "PSAR_INCREMENT": 0.02,
    "PSAR_MAX": 0.2,

    # SuperTrend
    "SUPERTREND_PERIOD": 10,
    "SUPERTREND_MULTIPLIER": 3.0,

    # Pivot Points
    "PIVOT_TYPE": "classic",  # classic | fibonacci | woodie | camarilla

    # Linear Regression Channel
    "LRC_PERIOD": 50,
    "LRC_STD_MULTIPLIER": 2.0,

    # Divergence detection
    "DIVERGENCE_LOOKBACK": 20,
    "DIVERGENCE_MIN_BARS": 5,

    # Historical Volatility
    "HV_PERIOD": 20,
    "HV_ANNUALIZE": 252,
}

# ─────────────────────────────────────────────────────────────────────────────
# MULTI-FACTOR WEIGHTS (must sum to 1.0 per market type)
# ─────────────────────────────────────────────────────────────────────────────
FACTOR_WEIGHTS = {
    "crypto": {
        "technical": 0.45,
        "fundamental": 0.25,
        "sentiment": 0.30,
    },
    "stocks": {
        "technical": 0.40,
        "fundamental": 0.45,
        "sentiment": 0.15,
    },
    "forex": {
        "technical": 0.50,
        "fundamental": 0.40,
        "sentiment": 0.10,
    },
    "commodities": {
        "technical": 0.50,
        "fundamental": 0.35,
        "sentiment": 0.15,
    },
    "default": {
        "technical": 0.50,
        "fundamental": 0.30,
        "sentiment": 0.20,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY PRESETS
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_PRESETS = {
    "balanced": {
        "technical": 0.50, "fundamental": 0.30, "sentiment": 0.20
    },
    "momentum": {
        "technical": 0.70, "fundamental": 0.10, "sentiment": 0.20
    },
    "value": {
        "technical": 0.20, "fundamental": 0.70, "sentiment": 0.10
    },
    "sentiment_driven": {
        "technical": 0.20, "fundamental": 0.20, "sentiment": 0.60
    },
    "technical_only": {
        "technical": 1.00, "fundamental": 0.00, "sentiment": 0.00
    },
}

ACTIVE_PRESET: str = os.getenv("STRATEGY_PRESET", "balanced")

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────
SIGNAL_THRESHOLDS = {
    "strong_buy":  0.60,
    "buy":         0.20,
    "hold_upper":  0.20,
    "hold_lower": -0.20,
    "sell":       -0.20,
    "strong_sell": -0.60,
}

# ─────────────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────
RISK = {
    # Position sizing method: "fixed_fractional" | "kelly" | "atr_based"
    "position_sizing_method": "atr_based",

    # Fixed fractional risk per trade (% of portfolio)
    "fixed_risk_pct": 0.02,           # 2% per trade

    # Kelly criterion fraction (fractional Kelly)
    "kelly_fraction": 0.25,            # quarter-Kelly for conservatism

    # ATR-based: risk in ATR multiples
    "atr_risk_multiplier": 1.5,        # stop at 1.5 * ATR from entry

    # Stop-loss settings
    "stop_loss_method": "atr",         # "fixed_pct" | "atr" | "trailing"
    "fixed_stop_pct": 0.02,            # 2% fixed stop
    "atr_stop_multiplier": 2.0,        # stop at 2 * ATR
    "trailing_stop_pct": 0.015,        # 1.5% trailing

    # Take-profit
    "take_profit_rr": 2.0,             # risk:reward ratio for TP
    "use_dynamic_tp": True,            # use resistance/Fib levels

    # Portfolio level
    "max_position_pct": 0.10,          # max 10% of portfolio in one asset
    "max_portfolio_exposure": 0.80,    # max 80% of capital deployed
    "max_drawdown_pct": 0.15,          # halt if drawdown exceeds 15%
    "daily_loss_limit_pct": 0.05,      # halt trading day if -5%
    "max_correlated_positions": 3,     # max positions with correlation > threshold
    "correlation_threshold": 0.70,     # correlation threshold
    "max_open_trades": 20,             # absolute cap on simultaneous positions
}

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION
# ─────────────────────────────────────────────────────────────────────────────
EXECUTION = {
    "default_order_type": "limit",     # "market" | "limit"
    "limit_slippage_pct": 0.001,       # 0.1% slippage for limit order pricing
    "order_retry_attempts": 3,
    "order_retry_delay": 2,            # seconds between retries
    "enable_partial_fills": True,
    "min_order_usdt": 10.0,            # minimum order value in USDT
}

# ─────────────────────────────────────────────────────────────────────────────
# BACKTESTING
# ─────────────────────────────────────────────────────────────────────────────
BACKTEST = {
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "initial_capital": 100_000,        # USD
    "commission_pct": 0.001,           # 0.1% per trade
    "slippage_pct": 0.0005,            # 0.05% slippage
    "use_walk_forward": True,
    "walk_forward_periods": 4,         # number of walk-forward windows
    "out_of_sample_pct": 0.20,         # 20% held out for OOS testing
    "optimization_metric": "sharpe",   # metric to optimize
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA SOURCE TOGGLES
# ─────────────────────────────────────────────────────────────────────────────
DATA_SOURCES = {
    "crypto_price": "binance",          # "binance" | "coingecko" | "cryptocompare"
    "crypto_onchain": "glassnode",      # "glassnode" | "mock"
    "stock_price": "yfinance",          # "yfinance" | "alpha_vantage" | "polygon"
    "stock_fundamentals": "alpha_vantage",
    "macro": "fred",
    "forex_price": "oanda",             # "oanda" | "yfinance"
    "commodity_price": "yfinance",
    "energy_data": "eia",
    "news": "newsapi",
    "social": "reddit",                 # "reddit" | "twitter" | "mock"
}

# ─────────────────────────────────────────────────────────────────────────────
# API RATE LIMITING (requests per minute)
# ─────────────────────────────────────────────────────────────────────────────
RATE_LIMITS = {
    "binance": 1200,
    "coingecko": 50,
    "alpha_vantage": 5,
    "yfinance": 2000,
    "fred": 120,
    "newsapi": 100,
    "oanda": 120,
    "glassnode": 10,
    "etherscan": 5,
    "polygon": 100,
}

# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULING
# ─────────────────────────────────────────────────────────────────────────────
SCHEDULE = {
    "signal_check_interval": 300,      # seconds (5 min)
    "data_refresh_interval": 60,       # seconds (1 min)
    "fundamental_refresh_hours": 24,   # hours
    "sentiment_refresh_interval": 900, # seconds (15 min)
    "risk_check_interval": 60,         # seconds
}

# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS (optional)
# ─────────────────────────────────────────────────────────────────────────────
NOTIFICATIONS = {
    "enable_telegram": os.getenv("ENABLE_TELEGRAM", "false").lower() == "true",
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "enable_email": False,
    "notify_on": ["strong_buy", "strong_sell", "stop_loss", "max_drawdown"],
}

# ─────────────────────────────────────────────────────────────────────────────
# FUNDAMENTAL ANALYSIS SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
FUNDAMENTAL = {
    "stock": {
        "pe_fair_value": 20,           # P/E considered fair
        "pb_fair_value": 3,
        "roe_threshold": 0.15,         # 15% ROE as good threshold
        "debt_equity_max": 2.0,
        "revenue_growth_min": 0.05,    # 5% min revenue growth
        "fcf_yield_min": 0.03,         # 3% min FCF yield
    },
    "crypto": {
        "nvt_overbought": 150,
        "nvt_oversold": 50,
        "mvrv_overbought": 3.0,
        "mvrv_oversold": 1.0,
        "github_activity_weight": 0.2,
    },
    "forex": {
        "rate_diff_weight": 0.40,
        "inflation_diff_weight": 0.25,
        "gdp_diff_weight": 0.20,
        "current_account_weight": 0.15,
    },
    "commodity": {
        "inventory_weight": 0.35,
        "seasonal_weight": 0.25,
        "production_weight": 0.20,
        "futures_curve_weight": 0.20,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SENTIMENT SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
SENTIMENT = {
    "news_weight": 0.35,
    "social_weight": 0.30,
    "indicators_weight": 0.35,         # VIX, Fear&Greed, COT, etc.
    "news_lookback_hours": 24,
    "social_lookback_hours": 12,
    "min_articles_for_signal": 3,
    "fear_greed_overbought": 80,
    "fear_greed_oversold": 20,
    "vix_high": 30,                    # high VIX = fear
    "vix_low": 15,                     # low VIX = complacency
    "cot_commercial_weight": 0.6,      # weight for commercial positions in COT
    "put_call_overbought": 1.5,
    "put_call_oversold": 0.7,
}
