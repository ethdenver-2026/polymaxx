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
    edge_threshold_pct: float = Field(default=8.0, ge=0.0, le=100.0)
    paper_edge_threshold_pct: float = Field(default=2.0, ge=0.0, le=100.0)
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    max_slippage_abs: float = Field(default=0.05, ge=0.0, le=1.0)
    bankroll_usdc: float = Field(default=50.0, gt=0.0)
    max_position_usd: float = Field(default=5.0, gt=0.0)
    min_position_usd: float = Field(default=1.0, gt=0.0)
    execution_workers: int = Field(default=16, ge=1)
    execution_queue_maxsize: int = Field(default=1000, ge=1)
    consumer_did: str = Field(default="did:kite:consumer/default")
    consumer_wallet_address: str = Field(default="0x0000000000000000000000000000000000000000")
    consumer_default_bid_amount: float = Field(default=1.0, gt=0.0)
    consumer_bid_timeout_seconds: float = Field(default=25.0, ge=1.0)
    consumer_payment_auto_succeeds: bool = Field(default=True)
    bid_llm_provider: Literal["mock", "anthropic", "g0"] = Field(default="g0")
    bid_llm_temperature: float = Field(default=0.8, ge=0.0, le=1.0)
    bid_llm_max_bid_amount_usdc: float = Field(default=5.0, gt=0.0)
    bid_llm_request_timeout_seconds: float = Field(default=20.0, ge=1.0)
    anthropic_api_key: str = Field(default="")
    anthropic_bid_model: str = Field(default="claude-sonnet-4-6")
    g0_api_key: str = Field(default="")
    g0_base_url: str = Field(default="https://0g-serving-broker.0g.ai/v1")
    g0_bid_model: str = Field(default="meta-llama/Llama-3.3-70B-Instruct")
    kite_session_url: str = Field(default="")
    kite_api_key: str = Field(default="")
    kite_payment_timeout_seconds: float = Field(default=20.0, ge=1.0)
    producer_ws_url: str = Field(default="ws://127.0.0.1:8000/ws/signals")
    producer_bid_ws_url: str = Field(default="ws://127.0.0.1:8000/ws/bids")
    producer_ws_reconnect_seconds: float = Field(default=2.0, ge=0.1)

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


# ---------------------------------------------------------------------------
# Runtime trading-mode override (survives without restarting the process)
# ---------------------------------------------------------------------------
_trading_mode_override: str | None = None


def set_trading_mode(mode: str) -> None:
    global _trading_mode_override
    if mode not in ("paper", "live"):
        raise ValueError(f"Invalid trading mode: {mode}")
    _trading_mode_override = mode


def get_trading_mode() -> str:
    if _trading_mode_override is not None:
        return _trading_mode_override
    return get_settings().trading_mode

