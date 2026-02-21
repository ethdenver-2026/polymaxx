"""Configuration for the signal consumer service."""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime
    env: Literal["dev", "prod"] = Field(default="dev")

    # Trading controls
    trading_mode: Literal["paper", "live"] = Field(default="paper")
    edge_threshold_pct: float = Field(default=8.0, ge=0.0, le=100.0)
    paper_edge_threshold_pct: float = Field(default=2.0, ge=0.0, le=100.0)
    trade_strategy_mode: Literal["regular", "coin_flip"] = Field(default="regular")
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    max_slippage_abs: float = Field(default=0.05, ge=0.0, le=1.0)
    bankroll_usdc: float = Field(default=50.0, gt=0.0)
    max_position_usd: float = Field(default=5.0, gt=0.0)
    min_position_usd: float = Field(default=1.0, gt=0.0)
    execution_workers: int = Field(default=16, ge=1)
    execution_queue_maxsize: int = Field(default=1000, ge=1)
    consumer_did: str = Field(default="did:kite:consumer/default")
    # Legacy/shared wallet identity (kept for backward compatibility).
    consumer_wallet_address: str = Field(default="0x0000000000000000000000000000000000000000")
    # Trading wallet identity (Polygon trading balance + CLOB trading key).
    trading_wallet_address: str = Field(default="")
    trading_wallet_private_key: str = Field(default="")
    # Payment wallet identity (SIWx + x402 payment settlement key/address).
    payment_wallet_address: str = Field(default="")
    payment_wallet_private_key: str = Field(default="")
    consumer_bid_timeout_seconds: float = Field(default=25.0, ge=1.0)
    consumer_payment_auto_succeeds: bool = Field(default=True)
    bid_llm_provider: Literal["anthropic", "g0"] = Field(default="g0")
    bid_llm_temperature: float = Field(default=0.8, ge=0.0, le=1.0)
    bid_llm_max_bid_amount_usdc: float = Field(default=5.0, gt=0.0)
    bid_llm_request_timeout_seconds: float = Field(default=20.0, ge=1.0)
    min_polygon_pol_for_bidding: float = Field(default=0.01, ge=0.0)
    anthropic_api_key: str = Field(default="")
    anthropic_bid_model: str = Field(default="claude-sonnet-4-6")
    g0_api_key: str = Field(default="")
    g0_base_url: str = Field(default="https://0g-serving-broker.0g.ai/v1")
    g0_bid_model: str = Field(default="meta-llama/Llama-3.3-70B-Instruct")
    x402_mode: Literal["kite", "x402_v2"] = Field(default="x402_v2")
    x402_v2_network: str = Field(default="base-sepolia")
    x402_v2_asset: str = Field(default="usdc")
    x402_v2_chain_id: int = Field(default=84532)
    x402_v2_rpc_url: str = Field(default="https://base-sepolia-rpc.publicnode.com")
    x402_v2_token_address: str = Field(default="0x036cbd53842c5426634e7929541ec2318f3dcf7e")
    x402_v2_token_decimals: int = Field(default=6, ge=0)
    x402_v2_timeout_seconds: float = Field(default=20.0, ge=1.0)
    siwx_challenge_url: str = Field(default="")
    siwx_auth_url: str = Field(default="")
    siwx_app_id: str = Field(default="")
    siwx_wallet_private_key: str = Field(default="")
    reputation_storage_backend: Literal["local_db", "0g_stub"] = Field(default="local_db")
    reputation_0g_enabled: bool = Field(default=False)
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

    @model_validator(mode="after")
    def _validate_live_networks(self) -> "Settings":
        if self.trading_mode != "live":
            return self
        if self.chain_id != 137:
            raise ValueError(
                f"TRADING_MODE=live requires CHAIN_ID=137 for Polymarket trading, got {self.chain_id}"
            )
        if self.x402_mode == "x402_v2":
            if self.x402_v2_chain_id != 8453:
                raise ValueError(
                    "TRADING_MODE=live with X402_MODE=x402_v2 requires "
                    f"X402_V2_CHAIN_ID=8453 (Base mainnet), got {self.x402_v2_chain_id}"
                )
            if self.x402_v2_asset.strip().lower() != "usdc":
                raise ValueError(
                    "TRADING_MODE=live with X402_MODE=x402_v2 requires "
                    f"X402_V2_ASSET=usdc, got {self.x402_v2_asset!r}"
                )
        return self


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

