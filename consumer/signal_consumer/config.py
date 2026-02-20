"""Configuration for the signal consumer service."""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime
    env: Literal["dev", "prod"] = Field(default="dev")

    # Trading controls
    trading_mode: Literal["paper", "live"] = Field(default="paper")
    weather_edge_threshold: float = Field(default=0.02, ge=0.0, le=1.0)
    max_slippage_abs: float = Field(default=0.05, ge=0.0, le=1.0)
    execution_workers: int = Field(default=16, ge=1)
    execution_queue_maxsize: int = Field(default=1000, ge=1)

    # Polymarket / CLOB
    polymarket_private_key: str = Field(default="")
    polymarket_api_key: str = Field(default="")
    polymarket_api_secret: str = Field(default="")
    polymarket_api_passphrase: str = Field(default="")

    chain_id: int = Field(default=137)
    clob_api_url: str = Field(default="https://clob.polymarket.com")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

