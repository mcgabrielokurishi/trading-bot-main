"""
utils/logger.py — Centralized logging configuration using loguru.

All modules import get_logger() from here for consistent structured logging.
"""

import sys
import json
from pathlib import Path
from loguru import logger as _logger
from config import LOG_LEVEL, LOG_DIR


def setup_logger() -> None:
    """Configure loguru with file rotation, JSON logging, and console output."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    _logger.remove()  # Remove default handler

    # Console — human-readable with color
    _logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Rotating file — plain text
    _logger.add(
        LOG_DIR / "trading_bot_{time:YYYY-MM-DD}.log",
        rotation="00:00",       # new file each day
        retention="30 days",
        compression="gz",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
        backtrace=True,
        diagnose=False,
    )

    # JSON file — machine-parseable for monitoring
    _logger.add(
        LOG_DIR / "trading_bot_json_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="90 days",
        compression="gz",
        level="INFO",
        format="{message}",
        serialize=True,         # loguru serialize=True emits JSON
    )

    # Trade-specific log
    _logger.add(
        LOG_DIR / "trades.log",
        rotation="1 week",
        retention="1 year",
        compression="gz",
        level="INFO",
        filter=lambda record: record["extra"].get("trade_log", False),
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    )


def get_logger(name: str):
    """Return a logger bound with the module name."""
    return _logger.bind(name=name)


def log_trade(
    timestamp: str,
    asset: str,
    market: str,
    side: str,
    price: float,
    size: float,
    value_usd: float,
    reason: str,
    signal_score: float,
    strategy: str,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    order_id: str | None = None,
) -> None:
    """Log a trade event to both main log and trade log."""
    trade_record = {
        "event": "TRADE",
        "timestamp": timestamp,
        "asset": asset,
        "market": market,
        "side": side,
        "price": price,
        "size": size,
        "value_usd": value_usd,
        "reason": reason,
        "signal_score": signal_score,
        "strategy": strategy,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "order_id": order_id,
    }
    _logger.bind(trade_log=True).info(json.dumps(trade_record))
    _logger.info(
        f"TRADE | {side.upper():4s} {asset} | price={price:.6f} | "
        f"size={size:.6f} | value=${value_usd:.2f} | score={signal_score:.3f} | "
        f"reason={reason}"
    )


# Initialize on import
setup_logger()
log = get_logger("main")
