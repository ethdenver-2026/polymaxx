"""NOAA GEFS client for fetching historical ensemble forecasts from S3.

Uses byte-range requests to efficiently fetch only TMAX data (~140KB per member
instead of ~40MB full file).

S3 Structure:
    s3://noaa-gefs-pds/gefs.YYYYMMDD/00/atmos/pgrb2ap5/
        gec00.t00z.pgrb2a.0p50.f024  (control member)
        gep01.t00z.pgrb2a.0p50.f024  (perturbation member 1)
        ...
        gep30.t00z.pgrb2a.0p50.f024  (perturbation member 30)

Index files (.idx) contain byte ranges for each variable.
"""

import asyncio
import hashlib
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import httpx
import structlog

logger = structlog.get_logger()

# Retry configuration (AWS best practices: exponential backoff with jitter)
MAX_RETRIES = 5
BASE_DELAY = 0.1  # 100ms initial delay
MAX_DELAY = 20.0  # Cap at 20 seconds per AWS SDK defaults


def _calculate_backoff(attempt: int) -> float:
    """Calculate delay with exponential backoff and jitter.

    Uses truncated binary exponential backoff with full jitter per AWS best practices.
    """
    import random
    # Exponential: 0.1, 0.2, 0.4, 0.8, 1.6, ... capped at MAX_DELAY
    exp_delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
    # Full jitter: random between 0 and exp_delay
    return random.uniform(0, exp_delay)


# GEFS S3 bucket base URL
GEFS_S3_BASE = "https://noaa-gefs-pds.s3.amazonaws.com"

# Cache directory for downloaded data (project-local)
DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "gefs_cache"


class GEFSMember(NamedTuple):
    """Ensemble member identifier."""
    name: str  # gec00, gep01, etc.
    is_control: bool


# All 31 ensemble members
ENSEMBLE_MEMBERS = [
    GEFSMember("gec00", True),  # Control
] + [GEFSMember(f"gep{i:02d}", False) for i in range(1, 31)]  # Perturbations


@dataclass
class EnsembleForecast:
    """Ensemble forecast for a single location and date."""
    forecast_date: date
    target_date: date
    latitude: float
    longitude: float
    member_temps: list[float]  # 31 TMAX values in Fahrenheit

    @property
    def mean(self) -> float:
        return sum(self.member_temps) / len(self.member_temps)

    @property
    def min(self) -> float:
        return min(self.member_temps)

    @property
    def max(self) -> float:
        return max(self.member_temps)

    @property
    def std(self) -> float:
        mean = self.mean
        variance = sum((t - mean) ** 2 for t in self.member_temps) / len(self.member_temps)
        return variance ** 0.5


class GEFSClient:
    """Client for fetching GEFS ensemble forecasts from NOAA S3.

    Args:
        cache_dir: Directory for caching downloaded data. Defaults to ~/.cache/gefs
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout: float = 60.0,
    ):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    def _build_data_url(self, forecast_date: date, member: GEFSMember, lead_hours: int = 24) -> str:
        """Build URL for GEFS data file.

        Args:
            forecast_date: Date of the forecast run (00Z)
            member: Ensemble member
            lead_hours: Forecast lead time in hours (24 for next-day max temp)
        """
        date_str = forecast_date.strftime("%Y%m%d")
        return (
            f"{GEFS_S3_BASE}/gefs.{date_str}/00/atmos/pgrb2ap5/"
            f"{member.name}.t00z.pgrb2a.0p50.f{lead_hours:03d}"
        )

    def _build_index_url(self, forecast_date: date, member: GEFSMember, lead_hours: int = 24) -> str:
        """Build URL for GEFS index file."""
        return self._build_data_url(forecast_date, member, lead_hours) + ".idx"

    def _get_cache_path(self, forecast_date: date, member: GEFSMember, lat: float, lon: float) -> Path:
        """Get cache file path for a specific forecast."""
        date_str = forecast_date.strftime("%Y%m%d")
        # Create a deterministic hash for the location
        loc_hash = hashlib.md5(f"{lat:.4f},{lon:.4f}".encode()).hexdigest()[:8]
        return self.cache_dir / f"{date_str}_{member.name}_{loc_hash}.grib2"

    async def _parse_index(self, index_content: str, variable: str = "TMAX") -> tuple[int, int] | None:
        """Parse index file to find byte range for a variable.

        Index format: line_num:byte_offset:d=YYYYMMDDHH:VARIABLE:level:forecast_info

        Returns:
            Tuple of (start_byte, end_byte) or None if variable not found.
        """
        lines = index_content.strip().split('\n')
        tmax_line = None
        tmax_idx = None

        for i, line in enumerate(lines):
            if f":{variable}:" in line:
                tmax_line = line
                tmax_idx = i
                break

        if tmax_line is None:
            return None

        # Parse byte offset from this line
        parts = tmax_line.split(':')
        start_byte = int(parts[1])

        # Get end byte from next line (or estimate if last line)
        if tmax_idx + 1 < len(lines):
            next_parts = lines[tmax_idx + 1].split(':')
            end_byte = int(next_parts[1]) - 1
        else:
            # Last variable - estimate 200KB
            end_byte = start_byte + 200000

        return start_byte, end_byte

    async def _fetch_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict | None = None,
    ) -> httpx.Response | None:
        """Fetch URL with exponential backoff retry on throttling."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return None  # Not found, don't retry
                if resp.status_code == 503:  # Throttled
                    delay = _calculate_backoff(attempt)
                    logger.debug("S3 throttled, retrying", url=url, attempt=attempt, delay=f"{delay:.2f}s")
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES - 1:
                    delay = _calculate_backoff(attempt)
                    logger.debug("Request failed, retrying", url=url, error=str(e), delay=f"{delay:.2f}s")
                    await asyncio.sleep(delay)
                else:
                    logger.warning("Request failed after retries", url=url, error=str(e))
                    return None
        return None

    async def _fetch_tmax_data(
        self,
        forecast_date: date,
        member: GEFSMember,
        lead_hours: int = 24,
    ) -> bytes | None:
        """Fetch TMAX GRIB data using byte-range request.

        Returns:
            Raw GRIB2 bytes for TMAX variable, or None if not available.
        """
        index_url = self._build_index_url(forecast_date, member, lead_hours)
        data_url = self._build_data_url(forecast_date, member, lead_hours)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Fetch index file with retry
            idx_resp = await self._fetch_with_retry(client, index_url)
            if idx_resp is None:
                return None

            # Parse byte range for TMAX
            byte_range = await self._parse_index(idx_resp.text)
            if byte_range is None:
                logger.warning("TMAX not found in index", url=index_url)
                return None

            start_byte, end_byte = byte_range

            # Fetch TMAX data with byte-range request and retry
            headers = {"Range": f"bytes={start_byte}-{end_byte}"}
            data_resp = await self._fetch_with_retry(client, data_url, headers)
            if data_resp is None:
                return None

            return data_resp.content

    def _extract_temperature(
        self,
        grib_data: bytes,
        lat: float,
        lon: float,
    ) -> float | None:
        """Extract temperature at a specific lat/lon from GRIB data.

        Args:
            grib_data: Raw GRIB2 bytes
            lat: Latitude (degrees)
            lon: Longitude (degrees, -180 to 180)

        Returns:
            Temperature in Fahrenheit, or None if extraction fails.
        """
        try:
            import xarray as xr
        except ImportError:
            raise ImportError("xarray and cfgrib required for GEFS parsing. Install with: pip install 'prediction-market-bot[backtest]'")

        # Write to temp file for cfgrib
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
            f.write(grib_data)
            temp_path = f.name

        try:
            ds = xr.open_dataset(temp_path, engine="cfgrib")

            # GEFS uses 0-360 longitude
            gefs_lon = lon if lon >= 0 else lon + 360

            # Get TMAX at nearest grid point
            tmax = ds["tmax"].sel(latitude=lat, longitude=gefs_lon, method="nearest")

            # Convert Kelvin to Fahrenheit
            tmax_k = float(tmax.values)
            tmax_f = (tmax_k - 273.15) * 9/5 + 32

            return tmax_f
        except Exception as e:
            logger.warning("Failed to extract temperature", error=str(e))
            return None
        finally:
            Path(temp_path).unlink(missing_ok=True)

    async def fetch_ensemble(
        self,
        forecast_date: date,
        lat: float,
        lon: float,
        lead_hours: int = 24,
    ) -> EnsembleForecast | None:
        """Fetch complete 31-member ensemble forecast for a location.

        Args:
            forecast_date: Date of the 00Z forecast run
            lat: Latitude of target location
            lon: Longitude of target location (-180 to 180)
            lead_hours: Forecast lead time (default 24 for next-day)

        Returns:
            EnsembleForecast with all member temperatures, or None if unavailable.
        """
        target_date = forecast_date + timedelta(days=lead_hours // 24)
        member_temps: list[float] = []

        logger.info(
            "Fetching GEFS ensemble",
            forecast_date=forecast_date.isoformat(),
            target_date=target_date.isoformat(),
            lat=lat,
            lon=lon,
        )

        for member in ENSEMBLE_MEMBERS:
            # Check cache first
            cache_path = self._get_cache_path(forecast_date, member, lat, lon)

            if cache_path.exists():
                grib_data = cache_path.read_bytes()
            else:
                grib_data = await self._fetch_tmax_data(forecast_date, member, lead_hours)
                if grib_data is None:
                    logger.warning("Missing member data", member=member.name)
                    continue
                # Cache the data
                cache_path.write_bytes(grib_data)

            temp = self._extract_temperature(grib_data, lat, lon)
            if temp is not None:
                member_temps.append(temp)
            else:
                logger.warning("Failed to extract temp", member=member.name)

        if len(member_temps) < 20:
            # Need at least 20 members for meaningful ensemble
            logger.warning(
                "Insufficient ensemble members",
                got=len(member_temps),
                expected=31,
            )
            return None

        return EnsembleForecast(
            forecast_date=forecast_date,
            target_date=target_date,
            latitude=lat,
            longitude=lon,
            member_temps=member_temps,
        )

    async def fetch_ensemble_batch(
        self,
        forecast_dates: list[date],
        lat: float,
        lon: float,
    ) -> dict[date, EnsembleForecast]:
        """Fetch ensemble forecasts for multiple dates.

        Args:
            forecast_dates: List of forecast dates to fetch
            lat: Latitude
            lon: Longitude

        Returns:
            Dict mapping target_date to EnsembleForecast
        """
        results = {}

        for forecast_date in forecast_dates:
            forecast = await self.fetch_ensemble(forecast_date, lat, lon)
            if forecast:
                results[forecast.target_date] = forecast

        return results

    def clear_cache(self) -> int:
        """Clear all cached GEFS data.

        Returns:
            Number of files deleted.
        """
        count = 0
        for f in self.cache_dir.glob("*.grib2"):
            f.unlink()
            count += 1
        return count
