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
def run():
    """Run a single trading cycle (DEPRECATED).

    Use 'serve' command with --producer flag for continuous signal generation.
    """
    typer.echo("⚠️  The 'run' command is deprecated.")
    typer.echo("")
    typer.echo("Use --producer mode for continuous signal generation:")
    typer.echo("  python -m signal_producer --producer")
    typer.echo("")
    typer.echo("Or use the 'serve' command for the websocket server:")
    typer.echo("  polymarket-bot serve")
    raise typer.Exit(1)


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
    from .clients.open_meteo import OpenMeteoClient

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
    from .models.collector import ForecastCollector

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
    from .models.collector import ForecastCollector

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
    """Run FastAPI websocket server for signals (no pipeline)."""
    from .ws_server import run_signal_server

    typer.echo(f"Starting websocket server on {host}:{port}")
    run_signal_server(host=host, port=port)


@app.command()
def producer(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    cities_opt: str = typer.Option(None, "--cities", "-c", help="Comma-separated cities"),
    db_path: str = typer.Option("data/producer.db", "--db-path", help="SQLite DB path"),
):
    """Run full producer pipeline + WebSocket server."""
    import os
    from .tasks.orchestrator import ProducerOrchestrator
    from .ws_server import app as ws_app

    os.makedirs("data", exist_ok=True)
    cities = [c.strip() for c in cities_opt.split(",")] if cities_opt else None
    settings = get_settings()

    logger = structlog.get_logger()
    logger.info(
        "Starting producer",
        trading_mode=settings.trading_mode,
        edge_threshold=f"{settings.paper_edge_threshold_pct}%" if settings.trading_mode == "paper" else f"{settings.edge_threshold_pct}%",
        cities=cities or "all",
    )

    async def _run() -> None:
        orchestrator = ProducerOrchestrator(db_path=db_path, cities=cities)
        await orchestrator.run_with_server(ws_app, host=host, port=port)

    asyncio.run(_run())


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
