"""
Tests for Polymarket Gamma API (weather events).

These are integration tests that hit the real API.
Run with: pytest tests/test_gamma_api.py -v
"""

import json
import re
import pytest
import httpx
from datetime import date, timedelta


GAMMA_API_URL = "https://gamma-api.polymarket.com"

# Verified cities with weather markets (Feb 2026)
VERIFIED_CITIES = ["nyc", "chicago", "london", "miami", "dallas", "seattle", "atlanta"]
CITIES_WITHOUT_MARKETS = ["la", "phoenix", "boston", "denver"]


@pytest.fixture
def http_client():
    """Create an HTTP client for tests."""
    return httpx.Client(timeout=30.0)


def build_weather_slug(city: str, target_date: date) -> str:
    """Build the weather event slug."""
    month = target_date.strftime("%B").lower()
    day = target_date.day
    year = target_date.year
    return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"


@pytest.mark.integration
class TestGammaAPIWeatherEvents:
    """Test Gamma API weather event structure."""

    def test_weather_event_exists_for_nyc(self, http_client):
        """Verify NYC weather event exists and has expected structure."""
        # Use a date a few days in the future
        target_date = date.today() + timedelta(days=2)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")

        # Event might not exist yet if too far out - try tomorrow
        if resp.status_code == 404:
            target_date = date.today() + timedelta(days=1)
            slug = build_weather_slug("nyc", target_date)
            resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")

        assert resp.status_code == 200, f"No weather event found for NYC: {slug}"

        data = resp.json()
        assert "id" in data, "Event should have an ID"
        assert "title" in data, "Event should have a title"
        assert "markets" in data, "Event should have markets"
        assert len(data["markets"]) > 0, "Event should have at least one market"

    def test_weather_event_has_temperature_buckets(self, http_client):
        """Verify weather event contains multiple temperature bucket markets."""
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available for tomorrow")

        data = resp.json()
        markets = data["markets"]

        # Should have multiple buckets (typically 8-10)
        assert len(markets) >= 5, f"Expected at least 5 buckets, got {len(markets)}"

        # Each market should have temperature-related question
        for market in markets:
            question = market.get("question", "")
            assert "temperature" in question.lower() or "°F" in question or "°C" in question, (
                f"Market question should mention temperature: {question}"
            )

    def test_market_fields_are_json_strings(self, http_client):
        """
        CRITICAL: Verify outcomes, outcomePrices, clobTokenIds are JSON strings.
        This was a critical discovery - they need json.loads() to parse.
        """
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available")

        data = resp.json()
        market = data["markets"][0]

        # These fields should be strings that need JSON parsing
        outcomes_raw = market.get("outcomes")
        prices_raw = market.get("outcomePrices")
        tokens_raw = market.get("clobTokenIds")

        assert isinstance(outcomes_raw, str), f"outcomes should be string, got {type(outcomes_raw)}"
        assert isinstance(prices_raw, str), f"outcomePrices should be string, got {type(prices_raw)}"
        assert isinstance(tokens_raw, str), f"clobTokenIds should be string, got {type(tokens_raw)}"

        # Should be valid JSON
        outcomes = json.loads(outcomes_raw)
        prices = json.loads(prices_raw)
        tokens = json.loads(tokens_raw)

        assert isinstance(outcomes, list), "outcomes should parse to list"
        assert isinstance(prices, list), "prices should parse to list"
        assert isinstance(tokens, list), "tokens should parse to list"

        # Should have Yes/No outcomes
        assert len(outcomes) == 2, "Should have exactly 2 outcomes"
        assert "Yes" in outcomes or "yes" in [o.lower() for o in outcomes]

    def test_token_ids_are_valid(self, http_client):
        """Verify CLOB token IDs are valid long integers."""
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available")

        data = resp.json()
        market = data["markets"][0]

        tokens = json.loads(market["clobTokenIds"])
        assert len(tokens) == 2, "Should have YES and NO token IDs"

        for token in tokens:
            # Token IDs are very long integers as strings
            assert isinstance(token, str), f"Token should be string, got {type(token)}"
            assert len(token) > 50, f"Token ID seems too short: {token}"
            assert token.isdigit(), f"Token ID should be numeric: {token}"

    def test_resolution_source_is_wunderground(self, http_client):
        """Verify resolution source points to Weather Underground."""
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available")

        data = resp.json()
        resolution_source = data.get("resolutionSource", "")

        assert "wunderground.com" in resolution_source.lower(), (
            f"Expected Weather Underground, got: {resolution_source}"
        )

    def test_all_verified_cities_have_events(self, http_client):
        """Verify all cities in our verified list have weather events."""
        target_date = date.today() + timedelta(days=2)
        found_cities = []
        missing_cities = []

        for city in VERIFIED_CITIES:
            slug = build_weather_slug(city, target_date)
            resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")

            if resp.status_code == 200:
                found_cities.append(city)
            else:
                # Try tomorrow instead
                target_tomorrow = date.today() + timedelta(days=1)
                slug = build_weather_slug(city, target_tomorrow)
                resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
                if resp.status_code == 200:
                    found_cities.append(city)
                else:
                    missing_cities.append(city)

        print(f"\nFound events for: {found_cities}")
        if missing_cities:
            print(f"Missing events for: {missing_cities}")

        # At least 4 cities should have events
        assert len(found_cities) >= 4, (
            f"Expected at least 4 cities with events, found {len(found_cities)}: {found_cities}"
        )

    def test_la_does_not_have_events(self, http_client):
        """Verify LA (and other excluded cities) don't have weather events."""
        target_date = date.today() + timedelta(days=2)

        for city in CITIES_WITHOUT_MARKETS[:2]:  # Test LA and Phoenix
            slug = build_weather_slug(city, target_date)
            resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")

            assert resp.status_code == 404, (
                f"Expected {city} to NOT have weather market, but got {resp.status_code}"
            )


@pytest.mark.integration
class TestTemperatureRangeParsing:
    """Test parsing temperature ranges from market questions."""

    def parse_temp_range(self, question: str) -> tuple:
        """Extract temperature range from market question."""
        # "between 34-35°F" → (34, 36)
        match = re.search(r"between (\d+)-(\d+)", question)
        if match:
            return float(match.group(1)), float(match.group(2)) + 1

        # "31°F or below" → (None, 32)
        match = re.search(r"(\d+)°F or below", question)
        if match:
            return None, float(match.group(1)) + 1

        # "46°F or higher" / "or above"
        match = re.search(r"(\d+)°F or (?:higher|above)", question)
        if match:
            return float(match.group(1)), None

        return None, None

    def test_parse_all_bucket_types(self, http_client):
        """Test parsing all types of temperature buckets."""
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available")

        data = resp.json()
        markets = data["markets"]

        parsed_buckets = []
        for market in markets:
            question = market["question"]
            low, high = self.parse_temp_range(question)
            parsed_buckets.append((question[:50], low, high))

        print("\nParsed temperature buckets:")
        for q, low, high in parsed_buckets:
            print(f"  {q}... → ({low}, {high})")

        # Should have at least one "or below", several "between", and one "or above"
        has_below = any(b[1] is None for b in parsed_buckets)
        has_above = any(b[2] is None for b in parsed_buckets)
        has_between = any(b[1] is not None and b[2] is not None for b in parsed_buckets)

        assert has_below, "Should have an 'or below' bucket"
        assert has_above, "Should have an 'or above' bucket"
        assert has_between, "Should have 'between' buckets"

    def test_buckets_cover_continuous_range(self, http_client):
        """Verify temperature buckets form a continuous range."""
        target_date = date.today() + timedelta(days=1)
        slug = build_weather_slug("nyc", target_date)

        resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
        if resp.status_code == 404:
            pytest.skip("No NYC weather event available")

        data = resp.json()
        markets = data["markets"]

        # Extract all bucket boundaries
        boundaries = set()
        for market in markets:
            low, high = self.parse_temp_range(market["question"])
            if low is not None:
                boundaries.add(low)
            if high is not None:
                boundaries.add(high)

        boundaries = sorted(boundaries)
        print(f"\nBucket boundaries: {boundaries}")

        # Check for gaps (adjacent boundaries should differ by 2°F typically)
        for i in range(len(boundaries) - 1):
            gap = boundaries[i + 1] - boundaries[i]
            assert gap <= 3, f"Gap between buckets too large: {boundaries[i]} to {boundaries[i+1]}"


class TestParseTempRange:
    """Test the parse_temp_range function."""

    def test_parse_temp_range_between(self):
        from signal_producer.clients.polymarket.markets import parse_temp_range

        low, high = parse_temp_range("between 34-35°F")
        assert low == 34
        assert high == 36  # Exclusive upper bound

    def test_parse_temp_range_or_below(self):
        from signal_producer.clients.polymarket.markets import parse_temp_range

        low, high = parse_temp_range("31°F or below")
        assert low is None
        assert high == 32

    def test_parse_temp_range_or_higher(self):
        from signal_producer.clients.polymarket.markets import parse_temp_range

        low, high = parse_temp_range("46°F or higher")
        assert low == 46
        assert high is None


@pytest.mark.integration
class TestGammaClient:
    """Test the GammaClient class."""

    @pytest.mark.asyncio
    async def test_fetch_weather_event_returns_buckets(self):
        """Verify client returns weather event with buckets."""
        from signal_producer.clients.polymarket.gamma import GammaClient

        client = GammaClient()
        tomorrow = date.today() + timedelta(days=1)

        event = await client.fetch_weather_event("nyc", tomorrow)

        # May be None if no market exists
        if event:
            assert event.city == "nyc"
            assert event.target_date == tomorrow
            assert len(event.buckets) > 0

    @pytest.mark.asyncio
    async def test_fetch_weather_event_returns_none_for_invalid_city(self):
        """Verify client returns None for cities without markets."""
        from signal_producer.clients.polymarket.gamma import GammaClient

        client = GammaClient()
        tomorrow = date.today() + timedelta(days=1)

        event = await client.fetch_weather_event("nonexistent-city-xyz", tomorrow)
        assert event is None

    @pytest.mark.asyncio
    async def test_discover_weather_events(self):
        """Verify discover returns list of events."""
        from signal_producer.clients.polymarket.gamma import GammaClient

        client = GammaClient()

        events = await client.discover_weather_events(
            cities=["nyc", "chicago"],
            days_ahead=3,
        )

        # Should find at least some events
        assert isinstance(events, list)
        # Events should have buckets
        for event in events:
            assert hasattr(event, "buckets")
            assert hasattr(event, "city")
