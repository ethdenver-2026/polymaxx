"""Polymarket execution helpers (py-clob-client)."""

from __future__ import annotations

import structlog

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderType
from py_clob_client.constants import POLYGON
from py_clob_client.order_builder.constants import BUY

from signal_schema import Signal

from .config import Settings

logger = structlog.get_logger()


def _require(value: str, name: str) -> str:
    if not value or not value.strip():
        raise RuntimeError(f"Missing required setting: {name}")
    return value.strip()


def build_clob_client(settings: Settings) -> ClobClient:
    if settings.chain_id != 137:
        raise RuntimeError(
            f"Unsupported CHAIN_ID={settings.chain_id}; Polymarket mainnet requires 137 (Polygon)"
        )

    private_key = _require(settings.polymarket_private_key, "POLYMARKET_PRIVATE_KEY")
    api_key = _require(settings.polymarket_api_key, "POLYMARKET_API_KEY")
    api_secret = _require(settings.polymarket_api_secret, "POLYMARKET_API_SECRET")
    api_passphrase = _require(settings.polymarket_api_passphrase, "POLYMARKET_API_PASSPHRASE")

    creds = ApiCreds(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
    )

    # Polymarket mainnet is Polygon (137). Use the library constant.
    return ClobClient(
        host=settings.clob_api_url,
        key=private_key,
        chain_id=POLYGON,
        creds=creds,
    )


def execute_weather_signal_market_buy(
    *,
    settings: Settings,
    signal: Signal,
    request_id: str,
) -> dict:
    """
    Execute a weather signal as a FOK market BUY.

    - BUY amount is USD you want to spend (per Polymarket docs).
    - price is a worst-price limit (slippage protection).
    """
    if settings.trading_mode != "live":
        raise RuntimeError(
            f"TRADING_MODE={settings.trading_mode!r} - refusing to place real order"
        )

    client = build_clob_client(settings)

    token_id = signal.token_id
    amount_usd = float(signal.position_size_usd)
    if amount_usd <= 0:
        raise RuntimeError(f"Signal position_size_usd must be > 0, got {amount_usd}")

    # Worst-price limit: allow bounded slippage above observed price.
    worst_price = min(signal.market_price + settings.max_slippage_abs, 0.99)

    # Market-specific options: discover tick size + neg risk flags.
    tick_size = client.get_tick_size(token_id)
    neg_risk = client.get_neg_risk(token_id)

    logger.info(
        "Placing Polymarket market BUY (FOK)",
        request_id=request_id,
        token_id=token_id,
        amount_usd=amount_usd,
        worst_price=worst_price,
        tick_size=tick_size,
        neg_risk=neg_risk,
    )

    resp = client.create_and_post_market_order(
        token_id=token_id,
        side=BUY,
        amount=amount_usd,
        price=worst_price,
        options={"tick_size": tick_size, "neg_risk": neg_risk},
        order_type=OrderType.FOK,
    )

    logger.info(
        "Order placed",
        request_id=request_id,
        response=resp,
    )
    return resp

