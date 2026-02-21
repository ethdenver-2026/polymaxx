"""CLOB WebSocket price tracker.

Maintains persistent websocket connection to Polymarket CLOB,
subscribes to token price updates, and forwards them to MarketRegistry.

See: https://docs.polymarket.com/developers/CLOB/websocket/market-channel
"""

import asyncio
import json
from datetime import datetime, UTC
from typing import Any

import structlog

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    websockets = None  # type: ignore
    ConnectionClosed = Exception  # type: ignore

from .polymarket_registry import MarketRegistry

logger = structlog.get_logger()

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RECONNECT_DELAY = 5  # seconds


class PriceTracker:
    """
    Tracks live prices via Polymarket CLOB websocket.

    Subscribes to token price updates and forwards them to MarketRegistry.
    Handles reconnection automatically.
    """

    def __init__(self, registry: MarketRegistry, ws_url: str = CLOB_WS_URL):
        self._registry = registry
        self._ws_url = ws_url
        self._running = False
        self._ws = None
        self._subscribed_tokens: set[str] = set()
        self._ready = asyncio.Event()

    @property
    def ready(self) -> asyncio.Event:
        """Fires once the first price update has been received."""
        return self._ready

    def _build_subscription_message(self, token_ids: list[str]) -> dict[str, Any]:
        """Build websocket subscription message."""
        return {
            "assets_ids": token_ids,
            "type": "market",
        }

    def _parse_price_change(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse price_change event into list of updates."""
        updates = []
        price_changes = event.get("price_changes", [])

        for change in price_changes:
            token_id = change.get("asset_id")
            price_str = change.get("price")

            if token_id and price_str:
                try:
                    price = float(price_str)
                    updates.append({
                        "token_id": token_id,
                        "price": price,
                        "best_bid": change.get("best_bid"),
                        "best_ask": change.get("best_ask"),
                    })
                except ValueError:
                    logger.warning("Invalid price value", price=price_str, token_id=token_id)

        return updates

    async def _handle_message(self, message: str) -> None:
        """Handle incoming websocket message."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON message", message=message[:100])
            return

        # Handle both single event and list of events
        events = data if isinstance(data, list) else [data]

        for event in events:
            if not isinstance(event, dict):
                continue

            event_type = event.get("event_type")

            if event_type == "price_change":
                timestamp = event.get("timestamp", datetime.now(UTC).isoformat())
                updates = self._parse_price_change(event)

                for update in updates:
                    self._registry.update_price(
                        token_id=update["token_id"],
                        price=update["price"],
                        timestamp=timestamp,
                    )

                if updates:
                    if not self._ready.is_set():
                        self._ready.set()
                        logger.info("Price tracker ready (first prices received)")
                    logger.debug(
                        "Price updates received",
                        count=len(updates),
                        tokens=[u["token_id"][:16] + "..." for u in updates],
                    )

            elif event_type == "market_resolved":
                # Handle market resolution
                market_id = event.get("market")
                if market_id:
                    logger.info("Market resolved event", market=market_id)
                    # The orchestrator will handle resolution via Gamma API polling

    async def _subscribe(self, ws: Any, token_ids: list[str]) -> None:
        """Send subscription message to websocket."""
        if not token_ids:
            logger.debug("No tokens to subscribe to")
            return

        msg = self._build_subscription_message(token_ids)
        await ws.send(json.dumps(msg))
        self._subscribed_tokens.update(token_ids)

        logger.info("Subscribed to tokens", count=len(token_ids))

    async def subscribe_tokens(self, token_ids: list[str]) -> None:
        """Subscribe to additional tokens (called when new events discovered)."""
        new_tokens = [t for t in token_ids if t not in self._subscribed_tokens]

        if not new_tokens:
            return

        if self._ws:
            await self._subscribe(self._ws, new_tokens)
        else:
            # Will be subscribed on next connection
            self._subscribed_tokens.update(new_tokens)

    async def unsubscribe_tokens(self, token_ids: list[str]) -> None:
        """Unsubscribe from tokens (called when events resolved)."""
        for token_id in token_ids:
            self._subscribed_tokens.discard(token_id)

        # Note: CLOB websocket doesn't support unsubscribe message,
        # we just stop tracking locally. Full reconnect would clean up server-side.

    async def run(self) -> None:
        """Run the price tracker (maintains websocket connection)."""
        if websockets is None:
            logger.error("websockets library not installed")
            return

        self._running = True

        while self._running:
            try:
                await self._connect_and_listen()
            except ConnectionClosed:
                logger.warning("CLOB websocket disconnected, reconnecting...")
                await asyncio.sleep(RECONNECT_DELAY)
            except Exception as e:
                logger.error("CLOB websocket error", error=str(e))
                await asyncio.sleep(RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        """Connect to websocket and listen for messages."""
        logger.info("Connecting to CLOB websocket", url=self._ws_url)

        async with websockets.connect(self._ws_url) as ws:
            self._ws = ws

            # Subscribe to all active tokens
            token_ids = self._registry.get_active_token_ids()
            if token_ids:
                await self._subscribe(ws, token_ids)

            # Listen for messages
            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

        self._ws = None

    def stop(self) -> None:
        """Stop the price tracker."""
        self._running = False
        logger.info("Price tracker stopping")
