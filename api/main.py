"""FastAPI application entry point for the trading backend."""

from __future__ import annotations

import signal
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from api.config import (
        ACTIVE_PRESET,
        API_DESCRIPTION,
        API_TITLE,
        API_VERSION,
        BACKTEST as BACKTEST_CFG,
        COMMODITY_SYMBOLS,
        CORS_ORIGINS,
        CRYPTO_SYMBOLS,
        FOREX_PAIRS,
        PRIMARY_TIMEFRAME,
        SCHEDULE,
        STOCK_SYMBOLS,
        TIMEFRAMES,
        TRADING_MODE,
    )
    from api.database import init_db
    from api.routers import admin, alerts, analytics, assistant, auth, automation, audit, alpaca, backtest, billing, brokers, journal, market, notifications, orders, portfolio, risk, status, strategies, streaming, subscriptions, teams, trading, watchlist, webhooks
    from api.utils.logger import get_logger
    from api.utils.helpers import utc_now
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import (
        ACTIVE_PRESET,
        API_DESCRIPTION,
        API_TITLE,
        API_VERSION,
        BACKTEST as BACKTEST_CFG,
        COMMODITY_SYMBOLS,
        CORS_ORIGINS,
        CRYPTO_SYMBOLS,
        FOREX_PAIRS,
        PRIMARY_TIMEFRAME,
        SCHEDULE,
        STOCK_SYMBOLS,
        TIMEFRAMES,
        TRADING_MODE,
    )
    from database import init_db
    from routers import admin, alerts, analytics, assistant, auth, automation, audit, alpaca, backtest, billing, brokers, journal, market, notifications, orders, portfolio, risk, status, strategies, streaming, subscriptions, teams, trading, watchlist, webhooks
    from utils.logger import get_logger
    from utils.helpers import utc_now

try:
    import schedule  # type: ignore
except ImportError:  # pragma: no cover
    schedule = None  # type: ignore

logger = get_logger("main")
_shutdown = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("Backend initialized")
    yield
    logger.info("Backend shutdown")


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(trading.router)
app.include_router(backtest.router)
app.include_router(status.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(portfolio.router)
app.include_router(market.router)
app.include_router(orders.router)
app.include_router(journal.router)
app.include_router(notifications.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(streaming.router)
app.include_router(teams.router)
app.include_router(subscriptions.router)
app.include_router(strategies.router)
app.include_router(analytics.router)
app.include_router(assistant.router)
app.include_router(automation.router)
app.include_router(audit.router)
app.include_router(brokers.router)
app.include_router(billing.router)
app.include_router(risk.router)
app.include_router(alpaca.router)


@app.get("/", tags=["Health"])
async def root() -> dict[str, Any]:
    return {"status": "online", "service": "trading-bot", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health", tags=["Health"])
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "trading-bot", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/dashboard", tags=["Dashboard"])
async def dashboard() -> FileResponse:
    dashboard_path = Path(__file__).resolve().parent / "dashboard.html"
    return FileResponse(dashboard_path)


def _handle_shutdown(signum: int, frame: Any) -> None:
    global _shutdown
    logger.warning("Shutdown signal received — finishing current cycle...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


def fetch_ohlcv_for_symbol(symbol: str, market_type: str, timeframes: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV data for a symbol across configured timeframes."""
    try:
        if market_type == "crypto":
            from api.data.crypto.binance_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        if market_type == "stocks":
            from api.data.stocks.yfinance_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        if market_type == "forex":
            from api.data.forex.oanda_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        if market_type == "commodities":
            from api.data.commodities.commodity_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"OHLCV fetch failed for {symbol}: {exc}")
    return {}


def get_current_price(symbol: str, market_type: str) -> float:
    """Get the latest price for a symbol."""
    try:
        if market_type == "crypto":
            from api.data.crypto.binance_client import fetch_ticker
            return float(fetch_ticker(symbol).get("last", 0.0))
        from api.data.stocks.yfinance_client import fetch_ohlcv
        yf_sym = symbol.replace("/USDT", "-USD").replace("_", "=")
        df = fetch_ohlcv(yf_sym, "1d", 2)
        return float(df["close"].iloc[-1]) if not df.empty else 0.0
    except Exception as exc:  # pragma: no cover
        logger.debug(f"Price fetch failed for {symbol}: {exc}")
        return 0.0


def build_universe() -> list[tuple[str, str]]:
    """Return list of (symbol, market_type) tuples from config."""
    universe: list[tuple[str, str]] = []
    for symbol in CRYPTO_SYMBOLS:
        universe.append((symbol, "crypto"))
    for symbol in STOCK_SYMBOLS:
        universe.append((symbol, "stocks"))
    for symbol in FOREX_PAIRS:
        universe.append((symbol, "forex"))
    for symbol in COMMODITY_SYMBOLS:
        universe.append((symbol, "commodities"))
    return universe


def run_signal_cycle(strategy: Any, universe: list[tuple[str, str]], portfolio_value: float) -> None:
    """Run one full signal evaluation and execution cycle."""
    logger.info(f"=== Signal Cycle @ {utc_now().strftime('%Y-%m-%d %H:%M:%S')} UTC ===")

    current_prices: dict[str, float] = {}
    for symbol, market_type in universe:
        if _shutdown:
            break
        try:
            ohlcv_by_tf = fetch_ohlcv_for_symbol(symbol, market_type, TIMEFRAMES)
            if not ohlcv_by_tf:
                continue

            price = get_current_price(symbol, market_type)
            current_prices[symbol] = price
            signal = strategy.evaluate(symbol=symbol, ohlcv_by_tf=ohlcv_by_tf, market_type=market_type)
            if signal.direction != "hold":
                primary_df = ohlcv_by_tf.get(PRIMARY_TIMEFRAME)
                strategy.execute(signal, portfolio_value, price, primary_df)
        except Exception as exc:
            logger.error(f"Signal cycle error for {symbol}: {exc}")
            logger.debug(traceback.format_exc())

    if current_prices:
        try:
            closed = strategy.check_exits(current_prices)
            if closed:
                logger.info(f"Closed {len(closed)} positions this cycle")
        except Exception as exc:
            logger.error(f"Exit check failed: {exc}")


def run_trading_loop() -> None:
    """Run the trading loop with optional scheduler support."""
    if schedule is None:
        logger.warning("schedule package not available; running one pass only")
        return

    from api.risk.portfolio_risk import PortfolioRiskManager
    from api.execution.order_manager import OrderManager
    from api.strategies.multi_factor_strategy import MultiFactorStrategy

    logger.info(f"Starting trading bot | mode={TRADING_MODE} | preset={ACTIVE_PRESET}")
    portfolio_manager = PortfolioRiskManager(initial_capital=100_000.0)
    order_manager = OrderManager(portfolio_manager)
    strategy = MultiFactorStrategy(portfolio_manager, order_manager, ACTIVE_PRESET)
    universe = build_universe()

    def cycle() -> None:
        if _shutdown:
            return
        try:
            stats = portfolio_manager.get_portfolio_stats({})
            pv = stats.get("portfolio_value", 100_000.0)
            run_signal_cycle(strategy, universe, pv)
        except Exception as exc:
            logger.error(f"Cycle error: {exc}")
            logger.debug(traceback.format_exc())

    interval = SCHEDULE["signal_check_interval"]
    schedule.every(interval).seconds.do(cycle)
    cycle()
    logger.info(f"Bot running — next cycle in {interval}s. Ctrl+C to stop.")
    while not _shutdown:
        schedule.run_pending()
        time.sleep(1)
    logger.info("Trading bot stopped gracefully.")


def run_backtest(symbol: str, start: str, end: str, market_type: str) -> None:
    """Run a single-asset backtest and print results."""
    from api.backtest.backtester import Backtester
    from api.backtest.metrics import print_metrics_table
    from api.analysis.technical.technical_scoring import score_single_timeframe
    import matplotlib.pyplot as plt

    logger.info(f"Running backtest: {symbol} {start} → {end}")
    ohlcv = fetch_ohlcv_for_symbol(symbol, market_type, [PRIMARY_TIMEFRAME])
    df = ohlcv.get(PRIMARY_TIMEFRAME)
    if df is None or df.empty:
        logger.error(f"No data for {symbol}; cannot run backtest")
        return

    def signal_func(df_slice: pd.DataFrame) -> float:
        scores = score_single_timeframe(df_slice)
        return scores.get("technical_score", 0.0)

    bt = Backtester(
        symbol=symbol,
        df=df,
        signal_func=signal_func,
        initial_capital=BACKTEST_CFG["initial_capital"],
        market_type=market_type,
    )
    result = bt.run(start, end)
    print(f"\n{'=' * 60}")
    print(f" BACKTEST RESULTS: {symbol} | {start} → {end}")
    print(f"{'=' * 60}")
    print_metrics_table(result["metrics"])

    equity = result.get("equity_curve")
    if equity is not None and not equity.empty:
        try:
            fig, axes = plt.subplots(2, 1, figsize=(14, 8))
            axes[0].plot(equity.index, equity.values, label="Portfolio Value", color="steelblue")
            axes[0].set_title(f"{symbol} Equity Curve")
            axes[0].set_ylabel("Portfolio Value ($)")
            axes[0].legend()
            axes[0].grid(alpha=0.3)
            rolling_max = equity.cummax()
            drawdown = (equity - rolling_max) / rolling_max * 100
            axes[1].fill_between(drawdown.index, drawdown.values, 0, color="red", alpha=0.4, label="Drawdown")
            axes[1].set_title("Drawdown (%)")
            axes[1].set_ylabel("Drawdown (%)")
            axes[1].legend()
            axes[1].grid(alpha=0.3)
            plt.tight_layout()
            fname = f"backtest_{symbol.replace('/', '_')}_{start}_{end}.png"
            plt.savefig(fname, dpi=150, bbox_inches="tight")
            logger.info(f"Equity curve saved to {fname}")
            plt.show()
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Could not plot equity curve: {exc}")


@click.group()
def cli() -> None:
    """Multi-Market Trading Bot CLI."""


@cli.command()
def trade() -> None:
    """Start the live/paper trading loop."""
    run_trading_loop()


@cli.command()
@click.option("--symbol", default="BTC/USDT", help="Asset symbol to backtest")
@click.option("--start", default=BACKTEST_CFG["start_date"], help="Start date YYYY-MM-DD")
@click.option("--end", default=BACKTEST_CFG["end_date"], help="End date YYYY-MM-DD")
@click.option("--market", default="crypto", type=click.Choice(["crypto", "stocks", "forex", "commodities"]))
def backtest_cli(symbol: str, start: str, end: str, market: str) -> None:
    """Run a backtest for a single symbol."""
    run_backtest(symbol, start, end, market)


@cli.command()
@click.option("--symbol", default="BTC/USDT", help="Asset symbol to optimize")
@click.option("--market", default="crypto", type=click.Choice(["crypto", "stocks", "forex", "commodities"]))
def optimize(symbol: str, market: str) -> None:
    """Run walk-forward optimization for a symbol."""
    from api.backtest.optimization import WalkForwardBacktester
    from api.analysis.technical.technical_scoring import score_single_timeframe

    ohlcv = fetch_ohlcv_for_symbol(symbol, market, [PRIMARY_TIMEFRAME])
    df = ohlcv.get(PRIMARY_TIMEFRAME)
    if df is None or df.empty:
        logger.error(f"No data for {symbol}")
        return

    def signal_factory(_: dict[str, Any]):
        def signal_func(df_slice: pd.DataFrame) -> float:
            scores = score_single_timeframe(df_slice)
            return scores.get("technical_score", 0.0)

        return signal_func

    param_grid = {
        "rsi_period": [10, 14, 21],
        "atr_period": [10, 14, 20],
    }

    wf = WalkForwardBacktester(symbol=symbol, df=df, signal_factory=signal_factory, param_grid=param_grid)
    results = wf.run()
    logger.info(f"Robustness score: {results.get('robustness_score', 0):.2f}")


@cli.command()
def status_cli() -> None:
    """Show current portfolio status (requires running bot state)."""
    click.echo("Portfolio status requires a running bot instance.")
    click.echo("Check logs/trading_bot_YYYY-MM-DD.log for current state.")
    click.echo(f"Trading mode: {TRADING_MODE}")
    click.echo(f"Active preset: {ACTIVE_PRESET}")
    click.echo(
        f"Universe: {len(CRYPTO_SYMBOLS)} crypto + {len(STOCK_SYMBOLS)} stocks + {len(FOREX_PAIRS)} forex + {len(COMMODITY_SYMBOLS)} commodities"
    )


@cli.command()
def list_presets() -> None:
    """List all available strategy presets."""
    from api.strategies.presets import list_presets as _list
    from tabulate import tabulate

    presets = _list()
    rows = [
        (
            preset["name"],
            preset["weights"]["technical"],
            preset["weights"]["fundamental"],
            preset["weights"]["sentiment"],
            preset["risk_profile"],
            preset["holding_period"],
        )
        for preset in presets
    ]
    print(tabulate(rows, headers=["Preset", "TA%", "FA%", "Sent%", "Risk", "Holding"], tablefmt="rounded_outline", floatfmt=".0%"))


if __name__ == "__main__":
    cli()
