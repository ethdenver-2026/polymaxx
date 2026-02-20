"""Tests for WebSocket broadcaster."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from signal_producer.publishing.websocket import SignalBroadcaster
from signal_producer.signals.types import ProducerSignal, WeatherMetadata, PolymarketInfo


@pytest.fixture
def broadcaster():
    """Create SignalBroadcaster instance."""
    return SignalBroadcaster()


@pytest.fixture
def sample_producer_signal():
    """Sample ProducerSignal for testing."""
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 43.0,
        "ensemble_std": 2.5,
        "members_in_range": 20,
    }

    exchange_info: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "yes_token_123",
        "side": "yes",
        "market_description": "Will temp be 42-44°F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.30,
        "edge": 0.35,
        "price_timestamp": "2026-02-20T12:00:00Z",
    }

    return ProducerSignal(
        signal_type="weather",
        model_probability=0.65,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-20T11:00:00Z",
        metadata=metadata,
        exchanges=[exchange_info],
    )


class TestSignalBroadcaster:
    """Tests for SignalBroadcaster."""

    @pytest.mark.asyncio
    async def test_broadcast_producer_signal_no_clients(
        self, broadcaster, sample_producer_signal
    ):
        """Test broadcast with no connected clients."""
        # Should not raise, just log
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

    @pytest.mark.asyncio
    async def test_broadcast_producer_signal_with_client(
        self, broadcaster, sample_producer_signal
    ):
        """Test broadcast sends to connected client."""
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        await broadcaster.connect(mock_ws)
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

        # Should have sent the signal
        mock_ws.send_json.assert_called_once()
        payload = mock_ws.send_json.call_args[0][0]

        assert payload["signal_type"] == "weather"
        assert payload["model_probability"] == 0.65
        assert payload["metadata"]["city"] == "nyc"
        assert "published_at" in payload

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, broadcaster):
        """Test disconnecting removes client."""
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        await broadcaster.connect(mock_ws)
        assert len(broadcaster._connections) == 1

        await broadcaster.disconnect(mock_ws)
        assert len(broadcaster._connections) == 0
