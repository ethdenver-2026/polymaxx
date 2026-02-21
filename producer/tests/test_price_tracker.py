"""Tests for CLOB WebSocket price tracker."""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from signal_producer.data.polymarket_registry import MarketRegistry
from signal_producer.data.polymarket_price_tracker import PriceTracker, CLOB_WS_URL


class TestPriceTracker:
    """Tests for PriceTracker."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock MarketRegistry."""
        registry = MagicMock(spec=MarketRegistry)
        registry.get_active_token_ids.return_value = ["token_123", "token_456"]
        return registry

    @pytest.fixture
    def tracker(self, mock_registry):
        """Create PriceTracker instance."""
        return PriceTracker(mock_registry)

    def test_build_subscription_message(self, tracker):
        """Test subscription message format."""
        token_ids = ["token_a", "token_b"]
        msg = tracker._build_subscription_message(token_ids)

        assert msg["type"] == "market"
        assert msg["assets_ids"] == ["token_a", "token_b"]

    def test_parse_price_change_event(self, tracker):
        """Test parsing price_change event."""
        event = {
            "event_type": "price_change",
            "market": "market_123",
            "timestamp": "1757908892351",
            "price_changes": [
                {
                    "asset_id": "token_123",
                    "price": "0.45",
                    "best_bid": "0.44",
                    "best_ask": "0.46",
                    "size": "100",
                    "side": "BUY",
                }
            ],
        }

        updates = tracker._parse_price_change(event)

        assert len(updates) == 1
        assert updates[0]["token_id"] == "token_123"
        assert updates[0]["price"] == 0.45

    def test_parse_price_change_multiple(self, tracker):
        """Test parsing multiple price changes in one event."""
        event = {
            "event_type": "price_change",
            "timestamp": "1757908892351",
            "price_changes": [
                {"asset_id": "token_a", "price": "0.30"},
                {"asset_id": "token_b", "price": "0.70"},
            ],
        }

        updates = tracker._parse_price_change(event)

        assert len(updates) == 2

    @pytest.mark.asyncio
    async def test_handle_message_updates_registry(self, tracker, mock_registry):
        """Test that price updates are forwarded to registry."""
        message = json.dumps({
            "event_type": "price_change",
            "timestamp": "1757908892351",
            "price_changes": [
                {"asset_id": "token_123", "price": "0.55"},
            ],
        })

        await tracker._handle_message(message)

        mock_registry.update_price.assert_called_once()
        call_kwargs = mock_registry.update_price.call_args.kwargs
        assert call_kwargs["token_id"] == "token_123"
        assert call_kwargs["price"] == 0.55

    @pytest.mark.asyncio
    async def test_subscribe_sends_message(self, tracker):
        """Test that subscribe sends correct websocket message."""
        mock_ws = AsyncMock()
        token_ids = ["token_a", "token_b"]

        await tracker._subscribe(mock_ws, token_ids)

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["type"] == "market"
        assert set(sent_msg["assets_ids"]) == {"token_a", "token_b"}
