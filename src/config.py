"""Configuration management using Pydantic settings."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Trading mode
    trading_mode: Literal["paper", "live"] = Field(default="paper")

    # Position sizing
    bankroll_usdc: float = Field(default=50.0)
    max_position_usd: float = Field(default=5.0)
    kelly_fraction: float = Field(default=0.25)
    edge_threshold_pct: float = Field(default=8.0)
    daily_loss_limit_pct: float = Field(default=5.0)

    # API Keys
    venice_api_key: str = Field(default="")
    grid_api_key: str = Field(default="")

    # Polymarket credentials (only needed for live trading)
    polymarket_private_key: str = Field(default="")
    polymarket_wallet_address: str = Field(default="")
    polymarket_api_key: str = Field(default="")
    polymarket_api_secret: str = Field(default="")
    polymarket_api_passphrase: str = Field(default="")

    # Chain config
    chain_id: int = Field(default=137)  # Polygon mainnet
    clob_api_url: str = Field(default="https://clob.polymarket.com")
    gamma_api_url: str = Field(default="https://gamma-api.polymarket.com")

    # Forecast config
    max_forecast_days: int = Field(default=2)  # Only trade within 48hr window

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class CityConfig:
    """Configuration for a city with weather markets."""

    def __init__(
        self,
        name: str,
        slug: str,
        lat: float,
        lon: float,
        tz: str,
        station: str,
    ):
        self.name = name
        self.slug = slug
        self.lat = lat
        self.lon = lon
        self.tz = tz
        self.station = station


# Verified cities with weather markets (Feb 2026)
CITIES: dict[str, CityConfig] = {
    "nyc": CityConfig(
        name="New York",
        slug="nyc",
        lat=40.7128,
        lon=-74.0060,
        tz="America/New_York",
        station="KLGA",
    ),
    "chicago": CityConfig(
        name="Chicago",
        slug="chicago",
        lat=41.8781,
        lon=-87.6298,
        tz="America/Chicago",
        station="KORD",
    ),
    "london": CityConfig(
        name="London",
        slug="london",
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        station="EGLL",
    ),
    "miami": CityConfig(
        name="Miami",
        slug="miami",
        lat=25.7617,
        lon=-80.1918,
        tz="America/New_York",
        station="KMIA",
    ),
    "dallas": CityConfig(
        name="Dallas",
        slug="dallas",
        lat=32.7767,
        lon=-96.7970,
        tz="America/Chicago",
        station="KDAL",
    ),
    "seattle": CityConfig(
        name="Seattle",
        slug="seattle",
        lat=47.6062,
        lon=-122.3321,
        tz="America/Los_Angeles",
        station="KSEA",
    ),
    "atlanta": CityConfig(
        name="Atlanta",
        slug="atlanta",
        lat=33.7490,
        lon=-84.3880,
        tz="America/New_York",
        station="KATL",
    ),
    "seoul": CityConfig(
        name="Seoul",
        slug="seoul",
        lat=37.5665,
        lon=126.9780,
        tz="Asia/Seoul",
        station="RKSS",
    ),
}

# Default cities to monitor (can be overridden)
DEFAULT_CITIES = ["nyc", "chicago", "miami"]


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
