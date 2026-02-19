"""Tests for the resolution service."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.services.resolver import ResolutionService


class TestResolutionService:
    """Tests for ResolutionService."""

    @pytest.mark.asyncio
    async def test_check_resolution_returns_winning_bucket(self):
        """Verify we correctly identify the winning bucket."""
        service = ResolutionService()

        # Mock the Gamma API response for a resolved event
        mock_event = {
            "closed": True,
            "markets": [
                {
                    "question": "Will the highest temperature be between 46-47°F?",
                    "outcomePrices": '["1", "0"]',  # YES won
                    "clobTokenIds": '["token_yes_46", "token_no_46"]',
                    "closed": True,
                },
                {
                    "question": "Will the highest temperature be between 44-45°F?",
                    "outcomePrices": '["0", "1"]',  # NO won (this bucket lost)
                    "clobTokenIds": '["token_yes_44", "token_no_44"]',
                    "closed": True,
                },
            ],
        }

        with patch.object(service, '_fetch_event', return_value=mock_event):
            result = await service.check_resolution("nyc", date(2026, 2, 17))

        assert result is not None
        assert result["winning_bucket"] == "Will the highest temperature be between 46-47°F?"
        assert result["winning_token"] == "token_yes_46"
        assert result["resolution"] == "yes"

    @pytest.mark.asyncio
    async def test_check_resolution_returns_none_if_not_resolved(self):
        """Verify we return None for unresolved markets."""
        service = ResolutionService()

        mock_event = {
            "closed": False,
            "markets": [
                {
                    "question": "Will the highest temperature be between 46-47°F?",
                    "outcomePrices": '["0.5", "0.5"]',
                    "clobTokenIds": '["token1", "token2"]',
                    "closed": False,
                },
            ],
        }

        with patch.object(service, '_fetch_event', return_value=mock_event):
            result = await service.check_resolution("nyc", date(2026, 2, 20))

        assert result is None

    @pytest.mark.asyncio
    async def test_check_resolution_returns_none_if_event_not_found(self):
        """Verify we return None if the event doesn't exist."""
        service = ResolutionService()

        with patch.object(service, '_fetch_event', return_value=None):
            result = await service.check_resolution("nonexistent", date(2026, 2, 20))

        assert result is None

    @pytest.mark.asyncio
    async def test_build_slug(self):
        """Verify slug is built correctly."""
        service = ResolutionService()

        slug = service._build_slug("nyc", date(2026, 2, 17))
        assert slug == "highest-temperature-in-nyc-on-february-17-2026"

        slug = service._build_slug("chicago", date(2026, 12, 25))
        assert slug == "highest-temperature-in-chicago-on-december-25-2026"


@pytest.mark.integration
class TestResolutionServiceIntegration:
    """Integration tests that hit real APIs."""

    @pytest.mark.asyncio
    async def test_check_recent_resolved_event(self):
        """Verify we can check a recently resolved event."""
        from datetime import timedelta

        service = ResolutionService()

        # Check yesterday's NYC weather (should be resolved)
        yesterday = date.today() - timedelta(days=1)
        result = await service.check_resolution("nyc", yesterday)

        # Should either be resolved or None (if no market existed)
        if result is not None:
            assert "winning_bucket" in result
            assert "winning_token" in result
            assert result["resolution"] == "yes"
