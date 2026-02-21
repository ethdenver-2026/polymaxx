"""
Tests for Open-Meteo Ensemble API.

These are integration tests that hit the real API.
Run with: pytest tests/test_open_meteo.py -v
"""

import pytest
import httpx
from datetime import date, timedelta


# City configurations for testing
CITIES = {
    "nyc": {"lat": 40.7128, "lon": -74.0060, "tz": "America/New_York"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "tz": "America/Chicago"},
    "london": {"lat": 51.5074, "lon": -0.1278, "tz": "Europe/London"},
}

ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


@pytest.fixture
def http_client():
    """Create an HTTP client for tests."""
    return httpx.Client(timeout=30.0)


@pytest.mark.integration
class TestOpenMeteoEnsembleAPI:
    """Test Open-Meteo Ensemble API responses."""

    def test_ensemble_returns_31_members(self, http_client):
        """Verify ensemble API returns exactly 31 temperature members."""
        params = {
            "latitude": CITIES["nyc"]["lat"],
            "longitude": CITIES["nyc"]["lon"],
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": CITIES["nyc"]["tz"],
            "forecast_days": 1,
        }

        resp = http_client.get(ENSEMBLE_API_URL, params=params)
        assert resp.status_code == 200, f"API returned {resp.status_code}: {resp.text}"

        data = resp.json()
        hourly = data.get("hourly", {})

        # Check that we have the control run and 30 ensemble members
        member_keys = [k for k in hourly.keys() if k.startswith("temperature_2m")]
        assert len(member_keys) == 31, f"Expected 31 members, got {len(member_keys)}: {member_keys}"

        # Verify the key naming pattern
        assert "temperature_2m" in hourly, "Missing control run (temperature_2m)"
        for i in range(1, 31):
            key = f"temperature_2m_member{i:02d}"
            assert key in hourly, f"Missing ensemble member: {key}"

    def test_ensemble_members_are_separate_keys(self, http_client):
        """
        CRITICAL: Verify members are separate keys, NOT a nested array.
        This was a major bug in the original plan.
        """
        params = {
            "latitude": CITIES["nyc"]["lat"],
            "longitude": CITIES["nyc"]["lon"],
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "forecast_days": 1,
        }

        resp = http_client.get(ENSEMBLE_API_URL, params=params)
        data = resp.json()
        hourly = data["hourly"]

        # Each member should be a list of floats, not a nested structure
        control_temps = hourly["temperature_2m"]
        assert isinstance(control_temps, list), "temperature_2m should be a list"
        assert all(isinstance(t, (int, float)) for t in control_temps[:5]), (
            "temperature_2m values should be numbers"
        )

        member01_temps = hourly["temperature_2m_member01"]
        assert isinstance(member01_temps, list), "member01 should be a list"
        assert len(member01_temps) == len(control_temps), "All members should have same length"

    def test_ensemble_values_are_reasonable(self, http_client):
        """Verify temperature values are in a reasonable range."""
        params = {
            "latitude": CITIES["nyc"]["lat"],
            "longitude": CITIES["nyc"]["lon"],
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "forecast_days": 1,
        }

        resp = http_client.get(ENSEMBLE_API_URL, params=params)
        data = resp.json()
        temps = data["hourly"]["temperature_2m"]

        # NYC temperatures should be between -30°F and 120°F
        for temp in temps:
            assert -30 <= temp <= 120, f"Unreasonable temperature: {temp}°F"

    def test_ensemble_with_past_days(self, http_client):
        """Verify past_days parameter returns historical hindcast data."""
        params = {
            "latitude": CITIES["nyc"]["lat"],
            "longitude": CITIES["nyc"]["lon"],
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "past_days": 7,
            "forecast_days": 1,
        }

        resp = http_client.get(ENSEMBLE_API_URL, params=params)
        assert resp.status_code == 200

        data = resp.json()
        times = data["hourly"]["time"]

        # Should have 8 days worth of hourly data (7 past + 1 forecast)
        # At 24 hours per day, that's at least 168 hours
        assert len(times) >= 168, f"Expected at least 168 hours, got {len(times)}"

        # First timestamp should be 7 days ago
        first_date = times[0].split("T")[0]
        expected_start = (date.today() - timedelta(days=7)).isoformat()
        assert first_date == expected_start, f"Expected start {expected_start}, got {first_date}"

    def test_all_cities_return_data(self, http_client):
        """Verify all configured cities return valid ensemble data."""
        for city_name, city_config in CITIES.items():
            params = {
                "latitude": city_config["lat"],
                "longitude": city_config["lon"],
                "models": "gfs_seamless",
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "timezone": city_config["tz"],
                "forecast_days": 1,
            }

            resp = http_client.get(ENSEMBLE_API_URL, params=params)
            assert resp.status_code == 200, f"Failed for {city_name}: {resp.status_code}"

            data = resp.json()
            assert "hourly" in data, f"No hourly data for {city_name}"
            assert "temperature_2m" in data["hourly"], f"No temp data for {city_name}"

    def test_forecast_days_parameter(self, http_client):
        """Verify forecast_days controls the forecast horizon."""
        for days in [1, 3, 7]:
            params = {
                "latitude": CITIES["nyc"]["lat"],
                "longitude": CITIES["nyc"]["lon"],
                "models": "gfs_seamless",
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "forecast_days": days,
            }

            resp = http_client.get(ENSEMBLE_API_URL, params=params)
            data = resp.json()
            times = data["hourly"]["time"]

            # Should have approximately days * 24 hours of data
            expected_hours = days * 24
            assert len(times) >= expected_hours - 1, (
                f"Expected ~{expected_hours} hours for {days} days, got {len(times)}"
            )


@pytest.mark.integration
class TestEnsembleParsing:
    """Test parsing ensemble data for trading signals."""

    def test_extract_daily_high_per_member(self, http_client):
        """Test extracting daily high temperature for each ensemble member."""
        target_date = date.today() + timedelta(days=1)

        params = {
            "latitude": CITIES["nyc"]["lat"],
            "longitude": CITIES["nyc"]["lon"],
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": CITIES["nyc"]["tz"],
            "forecast_days": 3,
        }

        resp = http_client.get(ENSEMBLE_API_URL, params=params)
        data = resp.json()
        hourly = data["hourly"]
        times = hourly["time"]

        # Find indices for target date
        target_str = str(target_date)
        target_indices = [i for i, t in enumerate(times) if t.startswith(target_str)]
        assert len(target_indices) > 0, f"No data for {target_date}"

        # Extract daily max for each member
        member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 31)]
        daily_highs = []

        for key in member_keys:
            temps_for_day = [hourly[key][i] for i in target_indices]
            daily_high = max(temps_for_day)
            daily_highs.append(daily_high)

        assert len(daily_highs) == 31, f"Expected 31 daily highs, got {len(daily_highs)}"

        # Verify spread is reasonable (ensemble members should differ)
        spread = max(daily_highs) - min(daily_highs)
        assert spread > 0, "Ensemble members should have some variation"
        assert spread < 30, f"Spread too large ({spread}°F), possible data issue"

        print(f"\nEnsemble daily highs for {target_date}:")
        print(f"  Min: {min(daily_highs):.1f}°F")
        print(f"  Max: {max(daily_highs):.1f}°F")
        print(f"  Mean: {sum(daily_highs)/len(daily_highs):.1f}°F")
        print(f"  Spread: {spread:.1f}°F")


@pytest.mark.integration
class TestOpenMeteoClient:
    """Test the OpenMeteoClient class."""

    @pytest.mark.asyncio
    async def test_get_ensemble_forecast_returns_31_members(self):
        """Verify client returns 31 ensemble members."""
        from signal_producer.clients.weather.open_meteo import OpenMeteoClient

        client = OpenMeteoClient()
        target = date.today() + timedelta(days=1)

        forecast = await client.get_ensemble_forecast(
            lat=40.7128,
            lon=-74.0060,
            target_date=target,
            timezone="America/New_York",
            city="nyc",
        )

        assert len(forecast.member_highs) == 31
        assert forecast.city == "nyc"
        assert forecast.target_date == target

    @pytest.mark.asyncio
    async def test_get_ensemble_forecast_temps_in_reasonable_range(self):
        """Verify temperatures are in a reasonable range."""
        from signal_producer.clients.weather.open_meteo import OpenMeteoClient

        client = OpenMeteoClient()
        target = date.today() + timedelta(days=1)

        forecast = await client.get_ensemble_forecast(
            lat=40.7128,
            lon=-74.0060,
            target_date=target,
            timezone="America/New_York",
            city="nyc",
        )

        # Temps should be between -50°F and 150°F
        for temp in forecast.member_highs:
            assert -50 < temp < 150

    @pytest.mark.asyncio
    async def test_ensemble_forecast_statistics(self):
        """Verify forecast statistics properties work."""
        from signal_producer.clients.weather.open_meteo import OpenMeteoClient

        client = OpenMeteoClient()
        target = date.today() + timedelta(days=1)

        forecast = await client.get_ensemble_forecast(
            lat=40.7128,
            lon=-74.0060,
            target_date=target,
            timezone="America/New_York",
            city="nyc",
        )

        # Test statistics
        assert forecast.mean > 0 or forecast.mean <= 0  # Just test it doesn't crash
        assert forecast.std >= 0
        assert forecast.min <= forecast.max
