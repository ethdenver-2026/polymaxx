"""
End-to-end test: Producer generates signals → sends over WebSocket → Consumer processes.

Usage:
    python test_e2e.py
    python test_e2e.py --cities nyc --ws-url ws://localhost:8765
"""

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import date

import websockets
from dotenv import load_dotenv

load_dotenv()

# Import producer components directly (bypass main.py's TradeExecutor import)
from producer.signal_producer.config import get_settings, CITIES
from producer.signal_producer.clients.gamma import GammaClient
from producer.signal_producer.strategies.weather.open_meteo import OpenMeteoClient
from producer.signal_producer.strategies.weather.signals import calculate_weather_signals


async def generate_signals(cities: list[str]) -> list[dict]:
    """Run the weather strategy and return signals as dicts."""
    settings = get_settings()
    gamma = GammaClient()
    open_meteo = OpenMeteoClient()

    events = await gamma.discover_weather_events(
        cities=cities,
        days_ahead=settings.max_forecast_days,
    )

    all_signals = []
    for event in events:
        city_config = CITIES.get(event.city)
        if not city_config:
            continue

        days_out = (event.target_date - date.today()).days
        if days_out > settings.max_forecast_days:
            continue

        forecast = await open_meteo.get_ensemble_forecast(
            lat=city_config.lat,
            lon=city_config.lon,
            target_date=event.target_date,
            timezone=city_config.tz,
            city=event.city,
        )

        signals = calculate_weather_signals(
            ensemble=forecast,
            event=event,
            bankroll=settings.bankroll_usdc,
            kelly_fraction=settings.kelly_fraction,
            max_position=settings.max_position_usd,
            edge_threshold=settings.edge_threshold_pct / 100,
        )

        all_signals.extend(signals)

    # Convert Signal dataclasses to JSON-serializable dicts
    result = []
    for s in all_signals:
        d = asdict(s)
        d["target_date"] = str(d["target_date"])
        d["side"] = "buy"  # Weather signals are always buy YES
        result.append(d)

    return result


async def send_to_consumer(signals: list[dict], ws_url: str):
    """Send each signal to the consumer WebSocket and print responses."""
    async with websockets.connect(ws_url) as ws:
        for signal in signals:
            print(f"\n{'='*60}")
            print(f"  SENDING: {signal['description'][:60]}")
            print(f"  Model: {signal['model_probability']*100:.1f}% | Signal Price: {signal['market_price']*100:.1f}%")
            print(f"  Edge: {signal['edge']*100:.1f}% | Position: ${signal['position_size_usd']:.2f}")
            print(f"{'='*60}")

            await ws.send(json.dumps(signal))
            response = json.loads(await ws.recv())

            action = response["action"].upper()
            print(f"\n  CONSUMER RESPONSE: {action}")

            if response.get("live_price") is not None:
                print(f"  Live Price:  {response['live_price']*100:.1f}%")
            if response.get("live_edge") is not None:
                print(f"  Live Edge:   {response['live_edge']*100:.1f}%")
            if response.get("order_id"):
                print(f"  Order ID:    {response['order_id']}")
                print(f"  Status:      {response['status']}")
            if response.get("errors"):
                for err in response["errors"]:
                    print(f"  Error: {err}")

            print()


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E: Producer → WebSocket → Consumer")
    parser.add_argument("--cities", default="nyc", help="Comma-separated cities (default: nyc)")
    parser.add_argument("--ws-url", default="ws://localhost:8765", help="Consumer WebSocket URL")
    args = parser.parse_args()

    cities = [c.strip() for c in args.cities.split(",")]

    print("=" * 60)
    print("  STEP 1: Generating signals from producer")
    print("=" * 60)

    signals = await generate_signals(cities)

    if not signals:
        print("\nNo signals found above edge threshold. Nothing to send.")
        return

    print(f"\nFound {len(signals)} signal(s)")

    print("\n" + "=" * 60)
    print("  STEP 2: Sending signals to consumer via WebSocket")
    print("=" * 60)

    await send_to_consumer(signals, args.ws_url)

    print("=" * 60)
    print("  E2E TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
