"""On-demand weather signal generator.

Fetches live Gamma API event + Open-Meteo ensemble forecast,
calculates per-bucket probabilities, and returns the best-edge signal.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

NYC = {
    "lat": 40.7128,
    "lon": -74.0060,
    "tz": "America/New_York",
    "slug": "nyc",
}


def _parse_bucket_bounds(question: str) -> tuple[float, float]:
    """Extract (low, high) from a market question string.

    Examples:
      "... 31\u00b0F or below ..."  -> (-inf, 32)
      "... 32-33\u00b0F ..."        -> (32, 34)
      "... 46\u00b0F or higher ..." -> (46, inf)
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
    lat: float, lon: float, target_date: datetime
) -> list[float]:
    """Get daily high temps from all 31 ensemble members for target_date."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "gfs_seamless",
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
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
    if target_date is None:
        target_date = datetime.now(timezone.utc) + timedelta(days=1)

    event = await _fetch_event(city_slug, target_date)
    if event is None:
        return {
            "signal_data": {},
            "response": {
                "action": "error",
                "errors": ["no_event_found"],
            },
        }

    ensemble_highs = await _fetch_ensemble(
        NYC["lat"], NYC["lon"], target_date
    )
    if not ensemble_highs:
        return {
            "signal_data": {},
            "response": {
                "action": "error",
                "errors": ["no_ensemble_data"],
            },
        }

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

    if best_signal is None or best_edge <= 0:
        return {
            "signal_data": {},
            "response": {
                "action": "skipped",
                "errors": ["no_positive_edge"],
            },
        }

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
