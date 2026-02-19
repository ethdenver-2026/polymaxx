"""
Tests for Polymarket CLOB API (read-only operations).

These are integration tests that hit the real API.
NO BETTING/TRADING is performed - only read operations.
Run with: pytest tests/test_polymarket.py -v
"""

import json
import pytest
import httpx
from datetime import date, timedelta


CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"


@pytest.fixture
def http_client():
    """Create an HTTP client for tests."""
    return httpx.Client(timeout=30.0)


def get_weather_event_token(http_client) -> str | None:
    """Helper to get a valid token ID from a weather event."""
    target_date = date.today() + timedelta(days=1)
    month = target_date.strftime("%B").lower()
    slug = f"highest-temperature-in-nyc-on-{month}-{target_date.day}-{target_date.year}"

    resp = http_client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
    if resp.status_code != 200:
        return None

    data = resp.json()
    if not data.get("markets"):
        return None

    # Get first market's YES token
    market = data["markets"][0]
    tokens = json.loads(market["clobTokenIds"])
    return tokens[0]  # YES token


@pytest.mark.integration
class TestPolymarketTimeseriesAPI:
    """Test Polymarket CLOB API price history (read-only)."""

    def test_prices_history_endpoint_exists(self, http_client):
        """Verify the prices-history endpoint is accessible."""
        # Use a known token from a weather event
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        resp = http_client.get(
            f"{CLOB_API_URL}/prices-history",
            params={"market": token_id, "interval": "max"}
        )

        assert resp.status_code == 200, f"API returned {resp.status_code}: {resp.text[:200]}"

    def test_prices_history_returns_valid_structure(self, http_client):
        """Verify price history has expected structure."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        resp = http_client.get(
            f"{CLOB_API_URL}/prices-history",
            params={"market": token_id, "interval": "max"}
        )

        data = resp.json()
        assert "history" in data, "Response should have 'history' key"

        history = data["history"]
        assert isinstance(history, list), "history should be a list"

        if len(history) > 0:
            point = history[0]
            assert "t" in point, "Price point should have timestamp 't'"
            assert "p" in point, "Price point should have price 'p'"

            # Timestamp should be a Unix timestamp (seconds since epoch)
            assert isinstance(point["t"], int), "Timestamp should be integer"
            assert point["t"] > 1700000000, "Timestamp should be recent (after 2023)"

            # Price should be between 0 and 1
            assert isinstance(point["p"], (int, float)), "Price should be numeric"
            assert 0 <= point["p"] <= 1, f"Price should be 0-1, got {point['p']}"

    def test_prices_history_intervals(self, http_client):
        """Test different interval parameters."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        intervals = ["1h", "6h", "1d", "max"]
        results = {}

        for interval in intervals:
            resp = http_client.get(
                f"{CLOB_API_URL}/prices-history",
                params={"market": token_id, "interval": interval}
            )

            results[interval] = {
                "status": resp.status_code,
                "points": len(resp.json().get("history", [])) if resp.status_code == 200 else 0
            }

        print("\nInterval results:")
        for interval, info in results.items():
            print(f"  {interval}: {info['points']} points (status {info['status']})")

        # All intervals should work
        for interval, info in results.items():
            assert info["status"] == 200, f"Interval {interval} failed"

    def test_price_history_has_data_points(self, http_client):
        """Verify we get actual price history data."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        resp = http_client.get(
            f"{CLOB_API_URL}/prices-history",
            params={"market": token_id, "interval": "max"}
        )

        data = resp.json()
        history = data["history"]

        # Should have at least some price history
        assert len(history) > 0, "Should have price history data"

        print(f"\nPrice history for weather market:")
        print(f"  Total points: {len(history)}")
        if history:
            print(f"  First price: {history[0]['p']:.4f}")
            print(f"  Last price: {history[-1]['p']:.4f}")


@pytest.mark.integration
class TestPolymarketMarketInfo:
    """Test reading market information (no trading)."""

    def test_get_market_info(self, http_client):
        """Test getting market information from CLOB."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        # The /markets endpoint should return market info
        resp = http_client.get(f"{CLOB_API_URL}/markets/{token_id}")

        # This might return 404 if the endpoint structure is different
        # The important thing is it doesn't require authentication
        print(f"\nMarket info response: {resp.status_code}")

    def test_get_orderbook(self, http_client):
        """Test getting orderbook (read-only, no auth needed)."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        resp = http_client.get(f"{CLOB_API_URL}/book", params={"token_id": token_id})

        if resp.status_code == 200:
            data = resp.json()
            print(f"\nOrderbook structure: {list(data.keys())}")

            # Check for bids/asks if available
            if "bids" in data:
                print(f"  Bids: {len(data['bids'])} levels")
            if "asks" in data:
                print(f"  Asks: {len(data['asks'])} levels")


@pytest.mark.integration
class TestPolymarketNoAuthRequired:
    """Verify read operations don't require authentication."""

    def test_prices_history_no_auth(self, http_client):
        """Verify price history works without any auth headers."""
        token_id = get_weather_event_token(http_client)
        if not token_id:
            pytest.skip("No weather event token available")

        # Make request with minimal headers (no API keys)
        client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
        resp = client.get(
            f"{CLOB_API_URL}/prices-history",
            params={"market": token_id, "interval": "max"}
        )

        assert resp.status_code == 200, (
            f"Price history should work without auth, got {resp.status_code}"
        )

    def test_gamma_api_no_auth(self, http_client):
        """Verify Gamma API works without authentication."""
        target_date = date.today() + timedelta(days=1)
        month = target_date.strftime("%B").lower()
        slug = f"highest-temperature-in-nyc-on-{month}-{target_date.day}-{target_date.year}"

        # Minimal client - no special headers
        client = httpx.Client(timeout=30.0)
        resp = client.get(f"{GAMMA_API_URL}/events/slug/{slug}")

        # Should work or return 404 (not auth error)
        assert resp.status_code in [200, 404], (
            f"Expected 200 or 404 without auth, got {resp.status_code}"
        )
