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
    # New cities added Feb 2026
    "paris": CityConfig(
        name="Paris",
        slug="paris",
        lat=48.8566,
        lon=2.3522,
        tz="Europe/Paris",
        station="LFPG",  # Charles de Gaulle
    ),
    "toronto": CityConfig(
        name="Toronto",
        slug="toronto",
        lat=43.6532,
        lon=-79.3832,
        tz="America/Toronto",
        station="CYYZ",  # Pearson
    ),
    "sao_paulo": CityConfig(
        name="Sao Paulo",
        slug="sao-paulo",  # Polymarket uses hyphen
        lat=-23.5505,
        lon=-46.6333,
        tz="America/Sao_Paulo",
        station="SBGR",  # Guarulhos
    ),
    "wellington": CityConfig(
        name="Wellington",
        slug="wellington",
        lat=-41.2866,
        lon=174.7756,
        tz="Pacific/Auckland",
        station="NZWN",
    ),
    "buenos_aires": CityConfig(
        name="Buenos Aires",
        slug="buenos-aires",  # Polymarket uses hyphen
        lat=-34.6037,
        lon=-58.3816,
        tz="America/Argentina/Buenos_Aires",
        station="SAEZ",  # Ezeiza
    ),
    "ankara": CityConfig(
        name="Ankara",
        slug="ankara",
        lat=39.9334,
        lon=32.8597,
        tz="Europe/Istanbul",
        station="LTAC",  # Esenboğa
    ),
}

# Default cities to monitor (can be overridden)
# NOTE: Only US cities are currently validated. International cities (london,
# seoul, paris, wellington, etc.) show systematic bias between Open-Meteo
# GFS ensemble and Weather Underground resolution data. Miami also shows
# ~3-4°F cold bias that needs investigation before live trading.
DEFAULT_CITIES = ["nyc", "chicago"]  # Validated cities only


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
