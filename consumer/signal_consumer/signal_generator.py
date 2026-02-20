"""On-demand weather signal generator (fallback when producer is offline).

Fetches live Gamma API event + Open-Meteo ensemble forecast,
calculates per-bucket probabilities, and returns the best-edge signal.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from .config import get_settings
from .db import get_executed_notional_usd

CITY_COORDS: dict[str, dict] = {
    "nyc": {"lat": 40.7128, "lon": -74.0060, "tz": "America/New_York", "name": "New York"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "tz": "America/Chicago", "name": "Chicago"},
    "london": {"lat": 51.5074, "lon": -0.1278, "tz": "Europe/London", "name": "London"},
    "miami": {"lat": 25.7617, "lon": -80.1918, "tz": "America/New_York", "name": "Miami"},
    "dallas": {"lat": 32.7767, "lon": -96.7970, "tz": "America/Chicago", "name": "Dallas"},
    "seattle": {"lat": 47.6062, "lon": -122.3321, "tz": "America/Los_Angeles", "name": "Seattle"},
    "atlanta": {"lat": 33.7490, "lon": -84.3880, "tz": "America/New_York", "name": "Atlanta"},
    "seoul": {"lat": 37.5665, "lon": 126.9780, "tz": "Asia/Seoul", "name": "Seoul"},
    "paris": {"lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris", "name": "Paris"},
    "toronto": {"lat": 43.6532, "lon": -79.3832, "tz": "America/Toronto", "name": "Toronto"},
    "sao_paulo": {"lat": -23.5505, "lon": -46.6333, "tz": "America/Sao_Paulo", "name": "Sao Paulo"},
    "wellington": {"lat": -41.2866, "lon": 174.7756, "tz": "Pacific/Auckland", "name": "Wellington"},
    "buenos_aires": {"lat": -34.6037, "lon": -58.3816, "tz": "America/Argentina/Buenos_Aires", "name": "Buenos Aires"},
    "ankara": {"lat": 39.9334, "lon": 32.8597, "tz": "Europe/Istanbul", "name": "Ankara"},
}

# Slug overrides for cities whose Polymarket slug differs from the key
SLUG_OVERRIDES: dict[str, str] = {
    "sao_paulo": "sao-paulo",
    "buenos_aires": "buenos-aires",
}


def _parse_bucket_bounds(question: str) -> tuple[float, float]:
    """Extract (low, high) from a market question string.

    Examples:
      "... 31°F or below ..."  -> (-inf, 32)
      "... 32-33°F ..."        -> (32, 34)
      "... 46°F or higher ..." -> (46, inf)
    """
    m = re.search(r"(\d+)\s*\u00b0F or below", question)
    if m:
        return float("-inf"), float(m.group(1)) + 1

    m = re.search(r"(\d+)\s*\u00b0F or higher", question)
    if m:
        return float(m.group(1)), float("inf")

    m = re.search(r"(\d+)\s*[\u2013-]\s*(\d+)\s*\u00b0F", question)
    if m:
        return float(m.group(1)), float(m.group(2)) + 1

    raise ValueError(f"Cannot parse bucket from: {question}")


async def _fetch_event(city_slug: str, target_date: datetime) -> dict | None:
    month = target_date.strftime("%B").lower()
    day = target_date.day
    year = target_date.year
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://gamma-api.polymarket.com/events/slug/{slug}"
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def _fetch_ensemble(
    lat: float, lon: float, tz: str, target_date: datetime
) -> list[float]:
    """Get daily high temps from all 31 ensemble members for target_date."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "gfs_seamless",
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": tz,
        "forecast_days": 7,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble", params=params
        )
        resp.raise_for_status()
        data = resp.json()

    hourly = data["hourly"]
    times = hourly["time"]
    target_str = target_date.strftime("%Y-%m-%d")

    indices = [i for i, t in enumerate(times) if t.startswith(target_str)]
    if not indices:
        raise ValueError(f"No forecast data for {target_str}")

    member_keys = ["temperature_2m"] + [
        f"temperature_2m_member{i:02d}" for i in range(1, 31)
    ]

    highs = []
    for key in member_keys:
        if key not in hourly:
            continue
        vals = [hourly[key][i] for i in indices if hourly[key][i] is not None]
        if vals:
            highs.append(max(vals))
    return highs


async def generate_signal(
    city_slug: str = "nyc",
    target_date: datetime | None = None,
) -> dict:
    """Generate a weather signal from live APIs.

    Returns dict with keys: signal_data, response (ready for db.log_signal).
    """
    city = CITY_COORDS.get(city_slug)
    if city is None:
        return {
            "signal_data": {"description": f"Unknown city: {city_slug}", "token_id": "", "side": "buy"},
            "response": {"action": "error", "errors": [f"unknown_city:{city_slug}"]},
        }

    # Use slug override if the Polymarket slug differs from our key
    pm_slug = SLUG_OVERRIDES.get(city_slug, city_slug)

    if target_date is None:
        target_date = datetime.now(timezone.utc) + timedelta(days=1)

    city_label = f"{city['name']} ({target_date.strftime('%b %d')})"

    event = await _fetch_event(pm_slug, target_date)
    if event is None:
        return {
            "signal_data": {"description": f"No event found: {city_label}", "token_id": "", "side": "buy"},
            "response": {"action": "error", "errors": ["no_event_found"]},
        }

    ensemble_highs = await _fetch_ensemble(
        city["lat"], city["lon"], city["tz"], target_date
    )
    if not ensemble_highs:
        return {
            "signal_data": {"description": f"No forecast data: {city_label}", "token_id": "", "side": "buy"},
            "response": {"action": "error", "errors": ["no_ensemble_data"]},
        }

    settings = get_settings()
    edge_threshold = settings.edge_threshold_pct / 100.0
    bankroll = settings.bankroll_usdc
    max_pos = settings.max_position_usd
    min_pos = settings.min_position_usd
    executed_notional = get_executed_notional_usd()
    available_balance = max(0.0, bankroll - executed_notional)

    n = len(ensemble_highs)
    best_edge = -999.0
    best_signal: dict | None = None

    for market in event.get("markets", []):
        if not market.get("active") or market.get("closed"):
            continue

        question = market["question"]
        prices = json.loads(market["outcomePrices"])
        tokens = json.loads(market["clobTokenIds"])
        yes_price = float(prices[0])

        try:
            low, high = _parse_bucket_bounds(question)
        except ValueError:
            continue

        count = sum(1 for t in ensemble_highs if low <= t < high)
        model_prob = count / n
        edge = model_prob - yes_price

        if edge > best_edge:
            best_edge = edge
            best_signal = {
                "token_id": tokens[0],
                "side": "buy",
                "model_probability": round(model_prob, 4),
                "market_price": yes_price,
                "edge": round(edge, 4),
                "description": question,
                "position_size_usd": None,
                "metadata": {
                    "city": city_slug,
                    "target_date": target_date.strftime("%Y-%m-%d"),
                    "ensemble_members": n,
                    "bucket": f"{low}-{high}",
                    "event_id": event.get("id"),
                },
            }

    # --- Strategy checks (mirrors consumer_engine / signal_pipeline logic) ---

    if best_signal is None:
        return {
            "signal_data": {"description": f"No parseable buckets: {city_label}", "token_id": "", "side": "buy"},
            "response": {
                "action": "error",
                "signal_price": None,
                "live_price": None,
                "signal_edge": None,
                "live_edge": None,
                "order_id": None,
                "errors": ["no_parseable_buckets"],
            },
        }

    if best_edge <= 0:
        return {
            "signal_data": best_signal,
            "response": {
                "action": "skipped",
                "signal_price": best_signal["market_price"],
                "live_price": best_signal["market_price"],
                "signal_edge": best_signal["edge"],
                "live_edge": best_signal["edge"],
                "order_id": None,
                "errors": ["no_positive_edge"],
            },
        }

    if best_edge < edge_threshold:
        return {
            "signal_data": best_signal,
            "response": {
                "action": "skipped",
                "signal_price": best_signal["market_price"],
                "live_price": best_signal["market_price"],
                "signal_edge": best_signal["edge"],
                "live_edge": best_signal["edge"],
                "order_id": None,
                "errors": ["edge_below_threshold"],
            },
        }

    if available_balance <= 0:
        return {
            "signal_data": best_signal,
            "response": {
                "action": "skipped",
                "signal_price": best_signal["market_price"],
                "live_price": best_signal["market_price"],
                "signal_edge": best_signal["edge"],
                "live_edge": best_signal["edge"],
                "order_id": None,
                "errors": ["insufficient_balance"],
            },
        }

    # Position sizing (edge-scaled, capped)
    edge_fraction = min(max(best_edge, 0.0), 0.20)
    position_usd = min(available_balance * edge_fraction, max_pos, available_balance)
    if position_usd < min_pos:
        return {
            "signal_data": best_signal,
            "response": {
                "action": "skipped",
                "signal_price": best_signal["market_price"],
                "live_price": best_signal["market_price"],
                "signal_edge": best_signal["edge"],
                "live_edge": best_signal["edge"],
                "order_id": None,
                "errors": ["position_below_minimum"],
            },
        }

    best_signal["position_size_usd"] = round(position_usd, 2)

    return {
        "signal_data": best_signal,
        "response": {
            "action": "simulated",
            "signal_price": best_signal["market_price"],
            "live_price": best_signal["market_price"],
            "signal_edge": best_signal["edge"],
            "live_edge": best_signal["edge"],
            "order_id": None,
            "errors": [],
        },
    }
