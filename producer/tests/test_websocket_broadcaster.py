"""Tests for WebSocket broadcaster."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from signal_producer.publishing.websocket_signal_broadcaster import SignalBroadcaster
from signal_schema import PolymarketInfo, ProducerSignal, WeatherMetadata


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

        await broadcaster.connect(mock_ws, consumer_did="did:kite:test/consumer-a")
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

        # Should have sent the signal
        mock_ws.send_json.assert_called_once()
        payload = mock_ws.send_json.call_args[0][0]

        assert payload["type"] == "SignalPreviewMessage"
        assert payload["signal_type"] == "weather"
        assert payload["producer_did"].startswith("did:")
        assert payload["auction_id"]
        assert payload["auction_end_utc"]
        assert "published_at" in payload

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, broadcaster):
        """Test disconnecting removes client."""
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        await broadcaster.connect(mock_ws, consumer_did="did:kite:test/consumer-a")
        assert len(broadcaster._signal_connections) == 1

        await broadcaster.disconnect("did:kite:test/consumer-a")
        assert len(broadcaster._signal_connections) == 0

    @pytest.mark.asyncio
    async def test_late_bid_rejected(self, broadcaster, sample_producer_signal):
        signal_ws = AsyncMock()
        signal_ws.accept = AsyncMock()
        signal_ws.send_json = AsyncMock()
        bid_ws = AsyncMock()
        bid_ws.accept = AsyncMock()
        bid_ws.send_json = AsyncMock()

        await broadcaster.connect(signal_ws, consumer_did="did:kite:test/consumer-a")
        await broadcaster.connect_bid(bid_ws, consumer_did="did:kite:test/consumer-a")
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

        preview_payload = signal_ws.send_json.call_args_list[0][0][0]
        auction_id = preview_payload["auction_id"]

        # Force-close via elapsed path before sending bid.
        await broadcaster._close_auction(auction_id, "auction_elapsed")
        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionBidMessage",
                "auction_id": auction_id,
                "consumer_did": "did:kite:test/consumer-a",
                "bid_amount": 3.5,
                "wallet_address": "0xabc",
            },
            consumer_did="did:kite:test/consumer-a",
        )
        last_payload = bid_ws.send_json.call_args_list[-1][0][0]
        assert last_payload["type"] == "AuctionBidRejected"

    @pytest.mark.asyncio
    async def test_ranked_payment_fallback_and_winner_delivery(
        self,
        broadcaster,
        sample_producer_signal,
    ):
        signal_ws_a = AsyncMock()
        signal_ws_a.accept = AsyncMock()
        signal_ws_a.send_json = AsyncMock()
        signal_ws_b = AsyncMock()
        signal_ws_b.accept = AsyncMock()
        signal_ws_b.send_json = AsyncMock()
        bid_ws_a = AsyncMock()
        bid_ws_a.accept = AsyncMock()
        bid_ws_a.send_json = AsyncMock()
        bid_ws_b = AsyncMock()
        bid_ws_b.accept = AsyncMock()
        bid_ws_b.send_json = AsyncMock()

        did_a = "did:kite:test/consumer-a"
        did_b = "did:kite:test/consumer-b"
        await broadcaster.connect(signal_ws_a, consumer_did=did_a)
        await broadcaster.connect(signal_ws_b, consumer_did=did_b)
        await broadcaster.connect_bid(bid_ws_a, consumer_did=did_a)
        await broadcaster.connect_bid(bid_ws_b, consumer_did=did_b)
        await broadcaster.broadcast_producer_signal(sample_producer_signal)
        preview = signal_ws_a.send_json.call_args_list[0][0][0]
        auction_id = preview["auction_id"]

        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionBidMessage",
                "auction_id": auction_id,
                "consumer_did": did_a,
                "bid_amount": 10.0,
                "wallet_address": "0xa",
            },
            consumer_did=did_a,
        )
        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionBidMessage",
                "auction_id": auction_id,
                "consumer_did": did_b,
                "bid_amount": 6.0,
                "wallet_address": "0xb",
            },
            consumer_did=did_b,
        )
        await asyncio.sleep(0.05)
        assert any(
            call[0][0]["type"] == "AuctionWinNotice"
            for call in bid_ws_a.send_json.call_args_list
        )

        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionPaymentResult",
                "auction_id": auction_id,
                "consumer_did": did_a,
                "payment_success": False,
            },
            consumer_did=did_a,
        )
        await asyncio.sleep(0.05)
        assert any(
            call[0][0]["type"] == "AuctionWinNotice"
            for call in bid_ws_b.send_json.call_args_list
        )

        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionPaymentResult",
                "auction_id": auction_id,
                "consumer_did": did_b,
                "payment_success": True,
            },
            consumer_did=did_b,
        )
        await asyncio.sleep(0.05)
        assert any(
            call[0][0]["type"] == "AuctionPaymentStatus"
            and call[0][0]["status"] == "PAYMENT_SUCCEEDS"
            for call in bid_ws_b.send_json.call_args_list
        )
        assert any(
            call[0][0]["type"] == "SignalMessage"
            for call in bid_ws_b.send_json.call_args_list
        )
        assert any(
            call[0][0]["type"] == "AuctionLossNotice"
            for call in bid_ws_a.send_json.call_args_list
        )

    @pytest.mark.asyncio
    async def test_win_notice_uses_x402_v2_mode_when_configured(
        self,
        monkeypatch,
        sample_producer_signal,
    ):
        monkeypatch.setenv("PRODUCER_X402_MODE", "x402_v2")
        monkeypatch.setenv("PRODUCER_X402_V2_URL", "https://x402.v2.example/weather")
        broadcaster = SignalBroadcaster()

        signal_ws = AsyncMock()
        signal_ws.accept = AsyncMock()
        signal_ws.send_json = AsyncMock()
        bid_ws = AsyncMock()
        bid_ws.accept = AsyncMock()
        bid_ws.send_json = AsyncMock()

        did = "did:kite:test/consumer-a"
        await broadcaster.connect(signal_ws, consumer_did=did)
        await broadcaster.connect_bid(bid_ws, consumer_did=did)
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

        preview = signal_ws.send_json.call_args_list[0][0][0]
        auction_id = preview["auction_id"]
        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionBidMessage",
                "auction_id": auction_id,
                "consumer_did": did,
                "bid_amount": 6.0,
                "wallet_address": "0x1111111111111111111111111111111111111111",
            },
            consumer_did=did,
        )
        await asyncio.sleep(0.05)

        win_notices = [
            call[0][0]
            for call in bid_ws.send_json.call_args_list
            if call[0][0]["type"] == "AuctionWinNotice"
        ]
        assert win_notices
        assert win_notices[0]["x402_mode"] == "x402_v2"
        assert win_notices[0]["x402_payment_url"] == "https://x402.v2.example/weather"

    @pytest.mark.asyncio
    async def test_win_notice_uses_local_x402_v2_endpoint_by_default(
        self,
        monkeypatch,
        sample_producer_signal,
    ):
        monkeypatch.setenv("PRODUCER_X402_MODE", "x402_v2")
        monkeypatch.delenv("PRODUCER_X402_V2_URL", raising=False)
        monkeypatch.setenv("PRODUCER_PUBLIC_BASE_URL", "http://127.0.0.1:8014")
        broadcaster = SignalBroadcaster()

        signal_ws = AsyncMock()
        signal_ws.accept = AsyncMock()
        signal_ws.send_json = AsyncMock()
        bid_ws = AsyncMock()
        bid_ws.accept = AsyncMock()
        bid_ws.send_json = AsyncMock()

        did = "did:kite:test/consumer-a"
        await broadcaster.connect(signal_ws, consumer_did=did)
        await broadcaster.connect_bid(bid_ws, consumer_did=did)
        await broadcaster.broadcast_producer_signal(sample_producer_signal)

        preview = signal_ws.send_json.call_args_list[0][0][0]
        auction_id = preview["auction_id"]
        await broadcaster.handle_bid_payload(
            {
                "type": "AuctionBidMessage",
                "auction_id": auction_id,
                "consumer_did": did,
                "bid_amount": 6.0,
                "wallet_address": "0x1111111111111111111111111111111111111111",
            },
            consumer_did=did,
        )
        await asyncio.sleep(0.05)

        win_notice = next(
            call[0][0]
            for call in bid_ws.send_json.call_args_list
            if call[0][0]["type"] == "AuctionWinNotice"
        )
        assert win_notice["x402_mode"] == "x402_v2"
        assert win_notice["x402_payment_url"] == "http://127.0.0.1:8014/x402/v2/payment"
