"""Tests for Producer Orchestrator."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import os

from signal_producer.tasks.orchestrator import ProducerOrchestrator


class TestProducerOrchestrator:
    """Tests for ProducerOrchestrator."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield f.name
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)

    @pytest.fixture
    def orchestrator(self, temp_db):
        """Create ProducerOrchestrator instance."""
        return ProducerOrchestrator(
            db_path=temp_db,
            cities=["nyc"],
            poll_interval=1,
            forecast_interval=1,
        )

    def test_init_components(self, orchestrator):
        """Test component initialization."""
        orchestrator._init_components()

        assert orchestrator._registry is not None
        assert orchestrator._gamma is not None
        assert orchestrator._open_meteo is not None
        assert orchestrator._price_tracker is not None
        assert orchestrator._broadcaster is not None
        assert orchestrator._event_discovery is not None
        assert orchestrator._signal_generator is not None

    def test_registry_property(self, orchestrator):
        """Test registry property accessor."""
        assert orchestrator.registry is None

        orchestrator._init_components()
        assert orchestrator.registry is not None

    def test_broadcaster_property(self, orchestrator):
        """Test broadcaster property accessor."""
        assert orchestrator.broadcaster is None

        orchestrator._init_components()
        assert orchestrator.broadcaster is not None

    @pytest.mark.asyncio
    async def test_run_and_shutdown(self, orchestrator):
        """Test orchestrator starts and responds to shutdown."""
        orchestrator._init_components()

        # Mock the tasks to avoid actual network calls
        orchestrator._event_discovery = MagicMock()
        orchestrator._event_discovery.run = AsyncMock()
        orchestrator._event_discovery.stop = MagicMock()

        orchestrator._price_tracker = MagicMock()
        orchestrator._price_tracker.run = AsyncMock()
        orchestrator._price_tracker.stop = MagicMock()

        orchestrator._signal_generator = MagicMock()
        orchestrator._signal_generator.run = AsyncMock()
        orchestrator._signal_generator.stop = MagicMock()

        # Run orchestrator with immediate shutdown
        async def trigger_shutdown():
            await asyncio.sleep(0.1)
            orchestrator._shutdown_event.set()

        await asyncio.gather(
            orchestrator._run_tasks(),
            trigger_shutdown(),
        )

        # Verify all tasks were stopped
        orchestrator._event_discovery.stop.assert_called_once()
        orchestrator._price_tracker.stop.assert_called_once()
        orchestrator._signal_generator.stop.assert_called_once()
