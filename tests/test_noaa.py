"""
Tests for NOAA Weather API (observations).

These are integration tests that hit the real API.
Run with: pytest tests/test_noaa.py -v
"""

import pytest
import httpx
from datetime import datetime, timedelta


NOAA_API_URL = "https://api.weather.gov"

# Weather stations for verified cities
STATIONS = {
    "nyc": "KLGA",      # LaGuardia Airport
    "chicago": "KORD",  # O'Hare International
    "miami": "KMIA",    # Miami International
    "dallas": "KDAL",   # Dallas Love Field
    "seattle": "KSEA",  # Seattle-Tacoma
    "atlanta": "KATL",  # Hartsfield-Jackson
    # London uses different system (not NOAA)
}


@pytest.fixture
def http_client():
    """Create an HTTP client with proper User-Agent for NOAA API."""
    return httpx.Client(
        timeout=30.0,
        headers={
            "User-Agent": "(prediction-market-bot, test@example.com)",
            "Accept": "application/geo+json",
        }
    )


@pytest.mark.integration
class TestNOAAObservationsAPI:
    """Test NOAA Weather API observations."""

    def test_get_latest_observation_klga(self, http_client):
        """Verify we can get latest observation from LaGuardia."""
        resp = http_client.get(f"{NOAA_API_URL}/stations/KLGA/observations/latest")

        assert resp.status_code == 200, f"NOAA API returned {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        assert "properties" in data, "Response should have properties"

        props = data["properties"]
        assert "temperature" in props, "Should have temperature data"
        assert "timestamp" in props, "Should have timestamp"

    def test_temperature_is_celsius(self, http_client):
        """Verify NOAA returns temperature in Celsius (needs conversion)."""
        resp = http_client.get(f"{NOAA_API_URL}/stations/KLGA/observations/latest")
        data = resp.json()

        temp_data = data["properties"]["temperature"]
        assert "value" in temp_data, "Temperature should have value"
        assert "unitCode" in temp_data, "Temperature should have unitCode"

        unit = temp_data["unitCode"]
        assert "degC" in unit or "Cel" in unit, f"Expected Celsius, got: {unit}"

        # Convert to Fahrenheit for verification
        celsius = temp_data["value"]
        if celsius is not None:
            fahrenheit = celsius * 9 / 5 + 32
            print(f"\nTemperature: {celsius}°C = {fahrenheit:.1f}°F")

            # Sanity check the value
            assert -50 <= fahrenheit <= 130, f"Unreasonable temp: {fahrenheit}°F"

    def test_all_us_stations_accessible(self, http_client):
        """Verify all US weather stations are accessible."""
        results = {}

        for city, station in STATIONS.items():
            resp = http_client.get(f"{NOAA_API_URL}/stations/{station}/observations/latest")
            results[city] = {
                "station": station,
                "status": resp.status_code,
                "has_temp": False,
            }

            if resp.status_code == 200:
                data = resp.json()
                temp = data.get("properties", {}).get("temperature", {}).get("value")
                results[city]["has_temp"] = temp is not None
                if temp is not None:
                    results[city]["temp_f"] = temp * 9 / 5 + 32

        print("\nStation results:")
        for city, info in results.items():
            status = "✓" if info["status"] == 200 else "✗"
            temp = f"{info.get('temp_f', 'N/A'):.1f}°F" if info.get("temp_f") else "N/A"
            print(f"  {status} {city} ({info['station']}): {temp}")

        # All stations should return 200
        failed = [c for c, r in results.items() if r["status"] != 200]
        assert len(failed) == 0, f"Failed stations: {failed}"

    def test_historical_observations_available(self, http_client):
        """Verify we can get historical observations for a date range."""
        station = "KLGA"
        end = datetime.utcnow()
        start = end - timedelta(hours=24)

        params = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        resp = http_client.get(f"{NOAA_API_URL}/stations/{station}/observations", params=params)

        assert resp.status_code == 200, f"Historical query failed: {resp.status_code}"

        data = resp.json()
        features = data.get("features", [])

        assert len(features) > 0, "Should have at least one observation in 24 hours"
        print(f"\nFound {len(features)} observations in last 24 hours")

        # Verify structure of observations
        for obs in features[:3]:
            props = obs.get("properties", {})
            assert "timestamp" in props, "Observation should have timestamp"
            assert "temperature" in props, "Observation should have temperature"

    def test_extract_daily_high_from_observations(self, http_client):
        """Test extracting daily high temperature from observations."""
        station = "KLGA"
        end = datetime.utcnow()
        start = end - timedelta(hours=24)

        params = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        resp = http_client.get(f"{NOAA_API_URL}/stations/{station}/observations", params=params)
        data = resp.json()
        features = data.get("features", [])

        # Extract all temperature readings
        temps_f = []
        for obs in features:
            temp_c = obs.get("properties", {}).get("temperature", {}).get("value")
            if temp_c is not None:
                temps_f.append(temp_c * 9 / 5 + 32)

        assert len(temps_f) > 0, "Should have temperature readings"

        daily_high = max(temps_f)
        daily_low = min(temps_f)

        print(f"\nLast 24 hours at KLGA:")
        print(f"  High: {daily_high:.1f}°F")
        print(f"  Low: {daily_low:.1f}°F")
        print(f"  Readings: {len(temps_f)}")

        # High should be reasonable
        assert -30 <= daily_high <= 120, f"Unreasonable high: {daily_high}"


@pytest.mark.integration
class TestNOAAPolymarketAlignment:
    """
    Test that NOAA data aligns with Polymarket resolution.

    Polymarket uses Weather Underground, which uses the same ASOS station data.
    This was verified: NOAA 46.9°F = Polymarket 46-47°F bucket.
    """

    def test_temperature_precision(self, http_client):
        """Verify NOAA reports temperature with sufficient precision."""
        resp = http_client.get(f"{NOAA_API_URL}/stations/KLGA/observations/latest")
        data = resp.json()

        temp_c = data["properties"]["temperature"]["value"]
        if temp_c is not None:
            # NOAA typically reports to 0.1°C precision
            # Which gives ~0.2°F precision - enough for 2°F buckets
            temp_str = str(temp_c)
            if "." in temp_str:
                decimals = len(temp_str.split(".")[1])
                assert decimals >= 1, "Should have at least 1 decimal place"

    def test_station_metadata(self, http_client):
        """Verify station metadata is accessible."""
        resp = http_client.get(f"{NOAA_API_URL}/stations/KLGA")

        assert resp.status_code == 200, f"Station metadata failed: {resp.status_code}"

        data = resp.json()
        props = data.get("properties", {})

        assert "name" in props, "Station should have name"
        assert "stationIdentifier" in props, "Station should have identifier"

        print(f"\nStation: {props.get('name')}")
        print(f"ID: {props.get('stationIdentifier')}")
