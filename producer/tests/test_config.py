"""Tests for configuration."""

from signal_producer.config import CITIES


def test_seoul_in_cities():
    """Verify Seoul was added to cities."""
    assert "seoul" in CITIES
    seoul = CITIES["seoul"]
    assert seoul.name == "Seoul"
    assert seoul.tz == "Asia/Seoul"
    assert seoul.lat == 37.5665
    assert seoul.lon == 126.9780


def test_all_cities_have_required_fields():
    """Verify all cities have required fields."""
    for slug, city in CITIES.items():
        assert city.name, f"{slug} missing name"
        assert city.lat, f"{slug} missing lat"
        assert city.lon, f"{slug} missing lon"
        assert city.tz, f"{slug} missing tz"
        assert city.station, f"{slug} missing station"


def test_expected_cities_exist():
    """Verify all expected cities are configured."""
    expected = ["nyc", "chicago", "london", "miami", "dallas", "seattle", "atlanta", "seoul"]
    for city in expected:
        assert city in CITIES, f"Missing city: {city}"
