import sys
import time
import signal
from fastapi import FastAPI
from routers import trading, backtest, status
import traceback
import schedule
import click
import pandas as pd



app = FastAPI(
    title="Multi Market Trading Bot",
    version="1.0.0"
)

app.include_router(trading.router)
app.include_router(backtest.router)
app.include_router(status.router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "trading-bot"
    }
    n 
from config import (
    TRADING_MODE, TIMEFRAMES, PRIMARY_TIMEFRAME,
    CRYPTO_SYMBOLS, STOCK_SYMBOLS, FOREX_PAIRS, COMMODITY_SYMBOLS,
    SCHEDULE, BACKTEST as BACKTEST_CFG, ACTIVE_PRESET,
)
from utils.logger import get_logger, log
from utils.helpers import utc_now

logger = get_logger("main")

# Global stop event
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.warning("Shutdown signal received — finishing current cycle...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)

# DATA FETCHER

def fetch_ohlcv_for_symbol(
    symbol: str, market_type: str, timeframes: list[str]
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV data for a symbol across all configured timeframes."""
    try:
        if market_type == "crypto":
            from data.crypto.binance_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        elif market_type == "stocks":
            from data.stocks.yfinance_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        elif market_type == "forex":
            from data.forex.oanda_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
        elif market_type == "commodities":
            from data.commodities.commodity_client import fetch_ohlcv_multi_timeframe
            return fetch_ohlcv_multi_timeframe(symbol, timeframes)
    except Exception as e:
        logger.warning(f"OHLCV fetch failed for {symbol}: {e}")
    return {}


def get_current_price(symbol: str, market_type: str) -> float:
    """Get the latest price for a symbol."""
    try:
        if market_type == "crypto":
            from data.crypto.binance_client import fetch_ticker
            return fetch_ticker(symbol).get("last", 0.0)
        else:
            from data.stocks.yfinance_client import fetch_ohlcv
            import re
            yf_sym = symbol.replace("/USDT", "-USD").replace("_", "=")
            df = fetch_ohlcv(yf_sym, "1d", 2)
            return float(df["close"].iloc[-1]) if not df.empty else 0.0
    except Exception as e:
        logger.debug(f"Price fetch failed for {symbol}: {e}")
        return 0.0


# TRADING LOOP

def build_universe() -> list[tuple[str, str]]:
    """Return list of (symbol, market_type) tuples from config."""
    universe = []
    for sym in CRYPTO_SYMBOLS:
        universe.append((sym, "crypto"))
    for sym in STOCK_SYMBOLS:
        universe.append((sym, "stocks"))
    for sym in FOREX_PAIRS:
        universe.append((sym, "forex"))
    for sym in COMMODITY_SYMBOLS:
        universe.append((sym, "commodities"))
    return universe


def run_signal_cycle(strategy, universe: list[tuple[str, str]], portfolio_value: float) -> None:
    """Run one full signal evaluation and execution cycle."""
    logger.info(f"=== Signal Cycle @ {utc_now().strftime('%Y-%m-%d %H:%M:%S')} UTC ===")

    current_prices: dict[str, float] = {}

    for symbol, market_type in universe:
        if _shutdown:
            break
        try:
            # Fetch data
            ohlcv_by_tf = fetch_ohlcv_for_symbol(symbol, market_type, TIMEFRAMES)
            if not ohlcv_by_tf:
                continue

            price = get_current_price(symbol, market_type)
            current_prices[symbol] = price

            # Evaluate signal
            signal = strategy.evaluate(
                symbol=symbol,
                ohlcv_by_tf=ohlcv_by_tf,
                market_type=market_type,
            )

            # Execute if actionable
            if signal.direction != "hold":
                primary_df = ohlcv_by_tf.get(PRIMARY_TIMEFRAME)
                strategy.execute(signal, portfolio_value, price, primary_df)

        except Exception as e:
            logger.error(f"Signal cycle error for {symbol}: {e}")
            logger.debug(traceback.format_exc())

    # Check exits for all open positions
    if current_prices:
        try:
            closed = strategy.check_exits(current_prices)
            if closed:
                logger.info(f"Closed {len(closed)} positions this cycle")
        except Exception as e:
            logger.error(f"Exit check failed: {e}")


def run_trading_loop() -> None:
    """Main trading loop."""
    from risk.portfolio_risk import PortfolioRiskManager
    from execution.order_manager import OrderManager
    from strategies.multi_factor_strategy import MultiFactorStrategy

    logger.info(f"Starting trading bot | mode={TRADING_MODE} | preset={ACTIVE_PRESET}")

    # Initialize components
    portfolio_manager = PortfolioRiskManager(initial_capital=100_000.0)
    order_manager = OrderManager(portfolio_manager)
    strategy = MultiFactorStrategy(portfolio_manager, order_manager, ACTIVE_PRESET)

    universe = build_universe()
    logger.info(f"Universe: {len(universe)} assets across all markets")

    def cycle():
        if _shutdown:
            return
        try:
            stats = portfolio_manager.get_portfolio_stats({})
            pv = stats.get("portfolio_value", 100_000.0)
            run_signal_cycle(strategy, universe, pv)
        except Exception as e:
            logger.error(f"Cycle error: {e}")
            logger.debug(traceback.format_exc())

    # Schedule recurring cycles
    interval = SCHEDULE["signal_check_interval"]
    schedule.every(interval).seconds.do(cycle)

    # Run first cycle immediately
    cycle()

    logger.info(f"Bot running — next cycle in {interval}s. Ctrl+C to stop.")
    while not _shutdown:
        schedule.run_pending()
        time.sleep(1)

    logger.info("Trading bot stopped gracefully.")

# BACKTEST RUNNER


def run_backtest(symbol: str, start: str, end: str, market_type: str) -> None:
    """Run a single-asset backtest and print results."""
    from backtest.backtester import Backtester
    from backtest.metrics import print_metrics_table
    from analysis.technical.technical_scoring import score_single_timeframe
    import matplotlib.pyplot as plt

    logger.info(f"Running backtest: {symbol} {start} → {end}")

    # Fetch data
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

    print(f"\n{'='*60}")
    print(f" BACKTEST RESULTS: {symbol} | {start} → {end}")
    print(f"{'='*60}")
    print_metrics_table(result["metrics"])

    # Plot equity curve
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
        except Exception as e:
            logger.warning(f"Could not plot equity curve: {e}")



# CL

@click.group()
def cli():
    """Multi-Market Trading Bot CLI."""
    pass


@cli.command()
def trade():
    """Start the live/paper trading loop."""
    run_trading_loop()


@cli.command()
@click.option("--symbol", default="BTC/USDT", help="Asset symbol to backtest")
@click.option("--start", default=BACKTEST_CFG["start_date"], help="Start date YYYY-MM-DD")
@click.option("--end", default=BACKTEST_CFG["end_date"], help="End date YYYY-MM-DD")
@click.option("--market", default="crypto", type=click.Choice(["crypto", "stocks", "forex", "commodities"]))
def backtest(symbol, start, end, market):
    """Run a backtest for a single symbol."""
    run_backtest(symbol, start, end, market)


@cli.command()
@click.option("--symbol", default="BTC/USDT", help="Asset symbol to optimize")
@click.option("--market", default="crypto", type=click.Choice(["crypto", "stocks", "forex", "commodities"]))
def optimize(symbol, market):
    """Run walk-forward optimization for a symbol."""
    from backtest.optimization import WalkForwardBacktester
    from analysis.technical.technical_scoring import score_single_timeframe
    from config import INDICATORS

    ohlcv = fetch_ohlcv_for_symbol(symbol, market, [PRIMARY_TIMEFRAME])
    df = ohlcv.get(PRIMARY_TIMEFRAME)
    if df is None or df.empty:
        logger.error(f"No data for {symbol}")
        return

    def signal_factory(params: dict):
        def signal_func(df_slice: pd.DataFrame) -> float:
            scores = score_single_timeframe(df_slice)
            return scores.get("technical_score", 0.0)
        return signal_func

    param_grid = {
        "rsi_period": [10, 14, 21],
        "atr_period": [10, 14, 20],
    }

    wf = WalkForwardBacktester(
        symbol=symbol,
        df=df,
        signal_factory=signal_factory,
        param_grid=param_grid,
    )
    results = wf.run()
    logger.info(f"Robustness score: {results.get('robustness_score', 0):.2f}")


@cli.command()
def status():
    """Show current portfolio status (requires running bot state)."""
    click.echo("Portfolio status requires a running bot instance.")
    click.echo("Check logs/trading_bot_YYYY-MM-DD.log for current state.")
    click.echo(f"Trading mode: {TRADING_MODE}")
    click.echo(f"Active preset: {ACTIVE_PRESET}")
    click.echo(f"Universe: {len(CRYPTO_SYMBOLS)} crypto + {len(STOCK_SYMBOLS)} stocks + "
               f"{len(FOREX_PAIRS)} forex + {len(COMMODITY_SYMBOLS)} commodities")


@cli.command()
def list_presets():
    """List all available strategy presets."""
    from strategies.presets import list_presets as _list
    from tabulate import tabulate
    presets = _list()
    rows = [(p["name"], p["weights"]["technical"], p["weights"]["fundamental"],
             p["weights"]["sentiment"], p["risk_profile"], p["holding_period"]) for p in presets]
    print(tabulate(rows, headers=["Preset", "TA%", "FA%", "Sent%", "Risk", "Holding"],
                   tablefmt="rounded_outline", floatfmt=".0%"))


if __name__ == "__main__":
    cli()
