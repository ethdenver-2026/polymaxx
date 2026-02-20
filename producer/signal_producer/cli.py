"""CLI for the prediction market trading bot."""

import asyncio
from datetime import date, timedelta

import typer
import structlog

from .config import get_settings, CITIES, DEFAULT_CITIES


# Configure logging for CLI
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

app = typer.Typer(
    name="polymarket-bot",
    help="Polymarket weather prediction trading bot",
    add_completion=False,
)


@app.command()
def run(
    cities: str = typer.Option(
        None,
        "--cities", "-c",
        help="Comma-separated list of cities (e.g., nyc,chicago,miami)",
    ),
    all_cities: bool = typer.Option(
        False,
        "--all",
        help="Run all configured cities",
    ),
    show_signals: bool = typer.Option(
        False,
        "--show-signals", "-s",
        help="Show detailed signal information",
    ),
):
    """Run a single trading cycle."""
    from .main import run_once

    # Determine which cities to run
    if all_cities:
        city_list = list(CITIES.keys())
    elif cities:
        city_list = [c.strip() for c in cities.split(",")]
    else:
        city_list = DEFAULT_CITIES

    typer.echo(f"Running trading cycle for: {', '.join(city_list)}")

    signals = asyncio.run(run_once(cities=city_list))

    if show_signals and signals:
        typer.echo("\n" + "=" * 60)
        typer.echo("SIGNALS FOUND")
        typer.echo("=" * 60)
        for s in signals:
            typer.echo(f"\n{s.metadata.get('city', 'unknown').upper()} - {s.target_date}")
            typer.echo(f"  {s.description}")
            typer.echo(f"  Model: {s.model_probability*100:.1f}% | Market: {s.market_price*100:.1f}%")
            typer.echo(f"  Edge: {s.edge_pct:.1f}% | Position: ${s.position_size_usd:.2f}")
            typer.echo(f"  EV: ${s.expected_value:.2f}")


@app.command()
def resolve():
    """Check and resolve pending trades."""
    from .services.resolver import ResolutionService
    from .data.models import init_db, get_session

    typer.echo("Checking for trades to resolve...")

    engine = init_db()
    session = get_session(engine)
    resolver = ResolutionService()

    try:
        resolved, pending = asyncio.run(
            resolver.resolve_pending_trades(session)
        )

        typer.echo(f"Resolved: {resolved} trades")
        typer.echo(f"Still pending: {pending} trades")
    finally:
        session.close()


@app.command()
def trades(
    strategy: str = typer.Option(
        None,
        "--strategy",
        help="Filter by strategy (weather, esports)",
    ),
    status: str = typer.Option(
        None,
        "--status",
        help="Filter by status (filled, resolved)",
    ),
    limit: int = typer.Option(
        20,
        "--limit", "-n",
        help="Number of trades to show",
    ),
):
    """Show trade history."""
    from .data.models import Trade, init_db, get_session

    engine = init_db()
    session = get_session(engine)

    try:
        query = session.query(Trade).order_by(Trade.created_at.desc())

        if strategy:
            query = query.filter(Trade.strategy == strategy)
        if status:
            query = query.filter(Trade.status == status)

        trades_list = query.limit(limit).all()

        if not trades_list:
            typer.echo("No trades found.")
            return

        typer.echo(f"\n{'ID':>5} {'Created':<20} {'Target':<12} {'City':<8} {'Edge':>6} {'P&L':>8} {'Status':<10}")
        typer.echo("-" * 75)

        for t in trades_list:
            pnl_str = f"${t.pnl:.2f}" if t.pnl is not None else "-"
            created = t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else "-"
            typer.echo(
                f"{t.id:>5} {created:<20} {str(t.target_date):<12} {t.city:<8} "
                f"{t.edge*100:>5.1f}% {pnl_str:>8} {t.status:<10}"
            )

        # Summary
        resolved = [t for t in trades_list if t.pnl is not None]
        if resolved:
            total_pnl = sum(t.pnl for t in resolved)
            wins = sum(1 for t in resolved if t.pnl > 0)
            typer.echo("-" * 60)
            typer.echo(f"Total P&L: ${total_pnl:.2f} | Win rate: {wins}/{len(resolved)}")
    finally:
        session.close()


@app.command()
def stats():
    """Show trading statistics."""
    from .data.models import Trade, init_db, get_session
    from sqlalchemy import func

    engine = init_db()
    session = get_session(engine)

    try:
        # Overall stats
        total = session.query(func.count(Trade.id)).scalar()
        resolved = session.query(func.count(Trade.id)).filter(Trade.status == "resolved").scalar()
        total_pnl = session.query(func.sum(Trade.pnl)).filter(Trade.pnl.isnot(None)).scalar() or 0
        wins = session.query(func.count(Trade.id)).filter(Trade.pnl > 0).scalar()

        typer.echo("\n=== TRADING STATISTICS ===\n")
        typer.echo(f"Total trades: {total}")
        typer.echo(f"Resolved: {resolved}")
        typer.echo(f"Total P&L: ${total_pnl:.2f}")
        if resolved > 0:
            typer.echo(f"Win rate: {wins}/{resolved} ({100*wins/resolved:.1f}%)")

        # By strategy
        typer.echo("\n--- By Strategy ---")
        strategies = session.query(
            Trade.strategy,
            func.count(Trade.id),
            func.sum(Trade.pnl),
        ).group_by(Trade.strategy).all()

        for strat, count, pnl in strategies:
            pnl_str = f"${pnl:.2f}" if pnl else "$0.00"
            typer.echo(f"  {strat}: {count} trades, {pnl_str}")

        # By city
        typer.echo("\n--- By City ---")
        cities = session.query(
            Trade.city,
            func.count(Trade.id),
            func.sum(Trade.pnl),
        ).group_by(Trade.city).all()

        for city, count, pnl in cities:
            pnl_str = f"${pnl:.2f}" if pnl else "$0.00"
            typer.echo(f"  {city}: {count} trades, {pnl_str}")

    finally:
        session.close()


@app.command()
def scan_cities():
    """Scan for new weather markets on Polymarket."""
    from datetime import timedelta
    from .clients.gamma import GammaClient

    # Cities to check that we don't already have
    potential_cities = [
        "la", "denver", "phoenix", "boston", "houston",
        "tokyo", "paris", "sydney", "toronto", "berlin",
    ]

    # Filter out cities we already have
    to_check = [c for c in potential_cities if c not in CITIES]

    if not to_check:
        typer.echo("No new cities to scan.")
        return

    typer.echo(f"Scanning {len(to_check)} potential cities...")

    client = GammaClient()
    tomorrow = date.today() + timedelta(days=1)

    async def check_cities():
        found = []
        for city in to_check:
            event = await client.fetch_weather_event(city, tomorrow)
            if event and not event.closed:
                found.append(city)
        return found

    found = asyncio.run(check_cities())

    if found:
        typer.echo(f"\n✓ Found new cities with weather markets: {', '.join(found)}")
        typer.echo("  Add these to src/config.py CITIES dict")
    else:
        typer.echo("\nNo new cities found with weather markets.")


@app.command()
def check(
    city: str = typer.Argument(..., help="City slug (e.g., nyc)"),
    target_date: str = typer.Argument(
        None,
        help="Target date (YYYY-MM-DD), defaults to tomorrow",
    ),
):
    """Check a specific weather market."""
    from datetime import timedelta
    from .clients.gamma import GammaClient
    from .strategies.weather.open_meteo import OpenMeteoClient

    # Parse date
    if target_date:
        check_date = date.fromisoformat(target_date)
    else:
        check_date = date.today() + timedelta(days=1)

    if city not in CITIES:
        typer.echo(f"Unknown city: {city}")
        typer.echo(f"Available: {', '.join(CITIES.keys())}")
        raise typer.Exit(1)

    city_config = CITIES[city]
    gamma = GammaClient()
    meteo = OpenMeteoClient()

    async def fetch_data():
        event = await gamma.fetch_weather_event(city, check_date)
        forecast = await meteo.get_ensemble_forecast(
            lat=city_config.lat,
            lon=city_config.lon,
            target_date=check_date,
            timezone=city_config.tz,
            city=city,
        )
        return event, forecast

    event, forecast = asyncio.run(fetch_data())

    typer.echo(f"\n=== {city.upper()} - {check_date} ===\n")

    # Forecast info
    typer.echo("ENSEMBLE FORECAST:")
    typer.echo(f"  Mean: {forecast.mean:.1f}°F")
    typer.echo(f"  Range: {forecast.min:.1f}°F - {forecast.max:.1f}°F")
    typer.echo(f"  Std Dev: {forecast.std:.1f}°F")

    if not event:
        typer.echo("\nNo market found for this date.")
        return

    typer.echo(f"\nMARKET: {event.title}")
    typer.echo(f"Closed: {event.closed}")
    typer.echo(f"\nBUCKETS ({len(event.active_buckets)} active):")

    for bucket in event.active_buckets:
        # Calculate model probability
        count = sum(1 for t in forecast.member_highs if bucket.contains_temp(t))
        model_prob = count / len(forecast.member_highs)
        edge = model_prob - bucket.yes_price

        edge_indicator = "📈" if edge > 0.08 else "📉" if edge < -0.08 else "➖"

        typer.echo(
            f"  {bucket.question[:45]:<45} "
            f"Market: {bucket.yes_price*100:>5.1f}% | "
            f"Model: {model_prob*100:>5.1f}% | "
            f"Edge: {edge*100:>+5.1f}% {edge_indicator}"
        )


@app.command()
def backtest(
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD), defaults to 6 months ago",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD), defaults to yesterday",
    ),
    cities_opt: str = typer.Option(
        None,
        "--cities", "-c",
        help="Comma-separated list of cities (defaults to all)",
    ),
    output: str = typer.Option(
        None,
        "--output", "-o",
        help="Output CSV file path",
    ),
):
    """Run historical backtest using GEFS forecasts."""
    from datetime import timedelta
    from .backtest import BacktestEngine

    # Parse dates
    if end:
        end_date = date.fromisoformat(end)
    else:
        end_date = date.today() - timedelta(days=1)

    if start:
        start_date = date.fromisoformat(start)
    else:
        start_date = end_date - timedelta(days=180)

    # Parse cities
    city_list = None
    if cities_opt:
        city_list = [c.strip() for c in cities_opt.split(",")]

    typer.echo(f"Running backtest: {start_date} to {end_date}")
    if city_list:
        typer.echo(f"Cities: {', '.join(city_list)}")
    else:
        typer.echo(f"Cities: all ({len(CITIES)})")

    engine = BacktestEngine()
    result = asyncio.run(engine.run(start_date, end_date, city_list))

    # Print summary
    typer.echo("\n" + "=" * 60)
    typer.echo("BACKTEST RESULTS")
    typer.echo("=" * 60)
    typer.echo(result.summary())

    if result.trades:
        typer.echo("\n--- Sample Trades ---")
        for trade in result.trades[:10]:
            won_str = "WIN" if trade.won else "LOSS" if trade.won is not None else "PENDING"
            pnl_str = f"${trade.pnl:.2f}" if trade.pnl is not None else "-"
            typer.echo(
                f"{trade.city:>8} {trade.target_date} | "
                f"Edge: {trade.edge*100:>5.1f}% | "
                f"Position: ${trade.position_usd:.2f} | "
                f"{won_str:>7} {pnl_str:>8}"
            )

    # Output to CSV if requested
    if output and result.trades:
        import csv
        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "city", "target_date", "bucket", "forecast_temp", "actual_temp",
                "model_prob", "market_price", "edge", "position_usd", "won", "pnl"
            ])
            for t in result.trades:
                writer.writerow([
                    t.city, t.target_date, t.bucket_question, t.forecast_temp,
                    t.actual_temp, t.model_prob, t.market_price, t.edge,
                    t.position_usd, t.won, t.pnl
                ])
        typer.echo(f"\nResults written to: {output}")


@app.command()
def collect(
    cities_opt: str = typer.Option(
        None,
        "--cities", "-c",
        help="Comma-separated list of cities (defaults to all)",
    ),
    days: int = typer.Option(
        1,
        "--days", "-d",
        help="Days ahead to forecast (1 = tomorrow). Use --max-days to collect multiple.",
    ),
    max_days: int = typer.Option(
        None,
        "--max-days", "-m",
        help="Collect forecasts for days 1 through max_days (e.g., -m 4 collects 1-4 day forecasts)",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite existing forecasts",
    ),
):
    """Collect and store ensemble forecasts for backtesting.

    Examples:
        collect                    # Collect 1-day forecasts for all cities
        collect --days 2           # Collect 2-day forecasts only
        collect --max-days 4       # Collect 1, 2, 3, and 4-day forecasts
        collect -c nyc,chicago -m 4  # Collect 1-4 day for specific cities
    """
    from .data.collector import ForecastCollector

    city_list = None
    if cities_opt:
        city_list = [c.strip() for c in cities_opt.split(",")]

    # Determine which days to collect
    if max_days:
        days_to_collect = list(range(1, max_days + 1))
    else:
        days_to_collect = [days]

    collector = ForecastCollector()
    total_collected = 0

    for d in days_to_collect:
        target_date = date.today() + timedelta(days=d)
        typer.echo(f"\n{'='*50}")
        typer.echo(f"Collecting {d}-day forecasts for {target_date}")
        if city_list:
            typer.echo(f"Cities: {', '.join(city_list)}")
        else:
            typer.echo(f"Cities: all ({len(CITIES)})")

        results = asyncio.run(collector.collect_all(city_list, d, force))
        total_collected += len(results)

        typer.echo(f"Collected {len(results)} forecasts:")
        for city, forecast in results.items():
            typer.echo(
                f"  {city}: mean={forecast.mean:.1f}F, "
                f"range={forecast.min_temp:.1f}-{forecast.max_temp:.1f}F, "
                f"std={forecast.std:.1f}F"
            )

    typer.echo(f"\n{'='*50}")
    typer.echo(f"Total: {total_collected} forecasts collected")


@app.command()
def list_forecasts():
    """List all stored ensemble forecasts."""
    from .data.collector import ForecastCollector

    collector = ForecastCollector()
    forecasts = collector.list_forecasts()

    if not forecasts:
        typer.echo("No stored forecasts found.")
        return

    typer.echo(f"Found {len(forecasts)} stored forecasts:\n")
    current_date = None
    for city, target_date in forecasts:
        if target_date != current_date:
            if current_date is not None:
                typer.echo()
            typer.echo(f"{target_date}:")
            current_date = target_date
        typer.echo(f"  - {city}")


@app.command()
def signals(
    cities_opt: str = typer.Option(
        None,
        "--cities", "-c",
        help="Comma-separated list of cities (defaults to all)",
    ),
    verify: bool = typer.Option(
        False,
        "--verify", "-v",
        help="Show detailed verification of each signal",
    ),
    min_edge: float = typer.Option(
        8.0,
        "--min-edge",
        help="Minimum edge percentage to show",
    ),
    filter_mode: str = typer.Option(
        "moderate",
        "--filter",
        help="Confidence filter: conservative, moderate, aggressive, disabled",
    ),
):
    """Show current trading signals with optional verification.

    Examples:
        signals                    # All signals, moderate filter
        signals --verify           # With detailed verification
        signals -c miami,nyc       # Specific cities only
        signals --filter disabled  # No probability filter
    """
    from .strategies.weather import WeatherStrategy, ConfidenceFilter

    settings = get_settings()

    # Parse cities
    if cities_opt:
        city_list = [c.strip() for c in cities_opt.split(",")]
    else:
        city_list = list(CITIES.keys())

    # Get filter
    filter_map = {
        "conservative": ConfidenceFilter.conservative,
        "moderate": ConfidenceFilter.moderate,
        "aggressive": ConfidenceFilter.aggressive,
        "disabled": ConfidenceFilter.disabled,
    }
    confidence_filter = filter_map.get(filter_mode, ConfidenceFilter.moderate)()

    strategy = WeatherStrategy(
        settings=settings,
        cities=city_list,
        confidence_filter=confidence_filter,
    )

    typer.echo("=" * 70)
    typer.echo("CURRENT TRADING SIGNALS")
    typer.echo("=" * 70)
    typer.echo(f"Filter: {filter_mode} (min_bucket_prob >= {confidence_filter.min_bucket_probability:.0%})")
    typer.echo(f"Edge threshold: {settings.edge_threshold_pct}%")
    typer.echo(f"Cities: {len(city_list)}")
    typer.echo("=" * 70)

    result = asyncio.run(strategy.generate_signals())

    if result.errors:
        typer.echo(f"\nWarnings: {len(result.errors)} errors encountered")

    if not result.signals:
        typer.echo("\nNO SIGNALS - No trades meet criteria")
        return

    typer.echo(f"\n{len(result.signals)} SIGNALS FOUND:\n")

    for s in result.signals:
        city = s.metadata.get("city", "unknown").upper()
        bucket_low = s.metadata.get("bucket_low")
        bucket_high = s.metadata.get("bucket_high")

        if bucket_low is None:
            bucket_str = f"<={bucket_high}°F" if bucket_high else "?"
        elif bucket_high is None:
            bucket_str = f">={bucket_low}°F"
        else:
            bucket_str = f"{bucket_low}-{bucket_high}°F"

        typer.echo(f"  {city} {s.target_date} | {bucket_str}")
        typer.echo(f"    Model: {s.model_probability:.0%} | Market: {s.market_price:.1%} | Edge: {s.edge:.1%}")
        typer.echo(f"    Position: ${s.position_size_usd:.2f} | EV: ${s.expected_value:.2f}")

        if verify:
            # Show ensemble stats
            std = s.metadata.get("ensemble_std", 0)
            typer.echo(f"    Ensemble std: {std:.1f}°F | Confidence: {s.confidence:.2f}")
            typer.echo(f"    Token: {s.token_id[:30]}...")

        typer.echo()

    # Summary
    total_position = sum(s.position_size_usd for s in result.signals)
    total_ev = sum(s.expected_value for s in result.signals)
    typer.echo("-" * 70)
    typer.echo(f"TOTAL: ${total_position:.2f} position | ${total_ev:.2f} expected value")


@app.command()
def outcomes(
    target_date: str = typer.Argument(
        None,
        help="Date to check (YYYY-MM-DD), defaults to today",
    ),
    cities_opt: str = typer.Option(
        None,
        "--cities", "-c",
        help="Comma-separated list of cities (defaults to all)",
    ),
):
    """Check resolution outcomes for a date.

    Examples:
        outcomes                  # Check today's outcomes
        outcomes 2026-02-19       # Check specific date
        outcomes -c miami,nyc     # Specific cities
    """
    from .clients.gamma import GammaClient
    import json as json_module
    import httpx

    if target_date:
        check_date = date.fromisoformat(target_date)
    else:
        check_date = date.today()

    city_list = None
    if cities_opt:
        city_list = [c.strip() for c in cities_opt.split(",")]
    else:
        city_list = list(CITIES.keys())

    typer.echo(f"\n=== OUTCOMES FOR {check_date} ===\n")

    async def check_outcomes():
        async with httpx.AsyncClient(timeout=30) as client:
            for city in city_list:
                month_name = check_date.strftime("%B").lower()
                slug = f"highest-temperature-in-{city}-on-{month_name}-{check_date.day}-{check_date.year}"

                resp = await client.get(f"https://gamma-api.polymarket.com/events/slug/{slug}")
                if resp.status_code == 404:
                    continue

                data = resp.json()

                # Find resolved bucket
                resolved_bucket = None
                for m in data.get("markets", []):
                    prices = json_module.loads(m.get("outcomePrices", "[]"))
                    if len(prices) >= 2 and prices[0] == "1":
                        resolved_bucket = m.get("question", "")
                        break

                if resolved_bucket:
                    typer.echo(f"{city.upper():>12}: {resolved_bucket[:50]}")
                else:
                    typer.echo(f"{city.upper():>12}: Not yet resolved")

    asyncio.run(check_outcomes())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host for websocket server"),
    port: int = typer.Option(8000, "--port", help="Bind port for websocket server"),
):
    """Run FastAPI websocket server for signals."""
    import uvicorn

    typer.echo(f"Starting websocket server on {host}:{port}")
    uvicorn.run("signal_producer.ws_server:app", host=host, port=port, log_level="info")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
