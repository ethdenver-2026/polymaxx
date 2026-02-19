"""Tests for the GEFS client."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile

from signal_producer.backtest.gefs import GEFSClient, EnsembleForecast, ENSEMBLE_MEMBERS, GEFSMember


class TestEnsembleForecast:
    """Tests for EnsembleForecast dataclass."""

    def test_mean(self):
        """Test mean calculation."""
        forecast = EnsembleForecast(
            forecast_date=date(2025, 8, 15),
            target_date=date(2025, 8, 16),
            latitude=40.7128,
            longitude=-74.0060,
            member_temps=[80.0, 82.0, 84.0],
        )
        assert forecast.mean == 82.0

    def test_min_max(self):
        """Test min/max."""
        forecast = EnsembleForecast(
            forecast_date=date(2025, 8, 15),
            target_date=date(2025, 8, 16),
            latitude=40.7128,
            longitude=-74.0060,
            member_temps=[78.0, 82.0, 86.0],
        )
        assert forecast.min == 78.0
        assert forecast.max == 86.0

    def test_std(self):
        """Test standard deviation."""
        forecast = EnsembleForecast(
            forecast_date=date(2025, 8, 15),
            target_date=date(2025, 8, 16),
            latitude=40.7128,
            longitude=-74.0060,
            member_temps=[80.0, 80.0, 80.0],  # No variation
        )
        assert forecast.std == 0.0


class TestGEFSClient:
    """Tests for GEFSClient."""

    def test_ensemble_members(self):
        """Verify we have 31 ensemble members."""
        assert len(ENSEMBLE_MEMBERS) == 31
        assert ENSEMBLE_MEMBERS[0].name == "gec00"
        assert ENSEMBLE_MEMBERS[0].is_control is True
        assert ENSEMBLE_MEMBERS[1].name == "gep01"
        assert ENSEMBLE_MEMBERS[30].name == "gep30"

    def test_build_data_url(self):
        """Test URL construction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))
            url = client._build_data_url(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
                lead_hours=24,
            )
            assert url == (
                "https://noaa-gefs-pds.s3.amazonaws.com/gefs.20250815/00/atmos/pgrb2ap5/"
                "gec00.t00z.pgrb2a.0p50.f024"
            )

    def test_build_index_url(self):
        """Test index URL construction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))
            url = client._build_index_url(
                date(2025, 8, 15),
                GEFSMember("gep05", False),
                lead_hours=24,
            )
            assert url.endswith(".idx")
            assert "gep05" in url

    @pytest.mark.asyncio
    async def test_parse_index(self):
        """Test parsing GEFS index file format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            # Simulated index content matching real format
            index_content = """1:0:d=2025081500:HGT:1000 mb:anl:ENS=low-res ctl
2:140000:d=2025081500:TMP:2 m above ground:anl:ENS=low-res ctl
3:280000:d=2025081500:TMAX:2 m above ground:18-24 hour max fcst:ENS=low-res ctl
4:420000:d=2025081500:TMIN:2 m above ground:18-24 hour min fcst:ENS=low-res ctl"""

            result = await client._parse_index(index_content, "TMAX")
            assert result is not None
            start, end = result
            assert start == 280000
            assert end == 420000 - 1  # Next line offset minus 1

    @pytest.mark.asyncio
    async def test_parse_index_variable_not_found(self):
        """Test parsing when variable is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            index_content = """1:0:d=2025081500:HGT:1000 mb:anl:ENS=low-res ctl
2:140000:d=2025081500:TMP:2 m above ground:anl:ENS=low-res ctl"""

            result = await client._parse_index(index_content, "TMAX")
            assert result is None

    def test_cache_path_deterministic(self):
        """Test that cache paths are deterministic for same inputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            path1 = client._get_cache_path(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
                40.7128,
                -74.0060,
            )
            path2 = client._get_cache_path(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
                40.7128,
                -74.0060,
            )
            assert path1 == path2

    def test_cache_path_different_for_different_locations(self):
        """Test that different locations get different cache paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            nyc_path = client._get_cache_path(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
                40.7128,
                -74.0060,
            )
            chicago_path = client._get_cache_path(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
                41.8781,
                -87.6298,
            )
            assert nyc_path != chicago_path

    def test_clear_cache(self):
        """Test cache clearing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            client = GEFSClient(cache_dir=cache_dir)

            # Create some fake cache files
            (cache_dir / "test1.grib2").write_bytes(b"test")
            (cache_dir / "test2.grib2").write_bytes(b"test")
            (cache_dir / "other.txt").write_bytes(b"test")  # Not .grib2

            deleted = client.clear_cache()

            assert deleted == 2
            assert not (cache_dir / "test1.grib2").exists()
            assert not (cache_dir / "test2.grib2").exists()
            assert (cache_dir / "other.txt").exists()  # Should not be deleted


@pytest.mark.integration
class TestGEFSClientIntegration:
    """Integration tests that hit real NOAA S3."""

    @pytest.mark.asyncio
    async def test_fetch_single_member(self):
        """Test fetching a single ensemble member."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            # Use a known historical date
            grib_data = await client._fetch_tmax_data(
                date(2025, 8, 15),
                GEFSMember("gec00", True),
            )

            assert grib_data is not None
            assert len(grib_data) > 100000  # Should be ~140KB

    @pytest.mark.asyncio
    async def test_fetch_full_ensemble(self):
        """Test fetching complete 31-member ensemble."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = GEFSClient(cache_dir=Path(tmpdir))

            forecast = await client.fetch_ensemble(
                date(2025, 8, 15),
                lat=40.7128,
                lon=-74.0060,
            )

            assert forecast is not None
            assert len(forecast.member_temps) >= 20
            assert 60 < forecast.mean < 100  # Reasonable summer temp
