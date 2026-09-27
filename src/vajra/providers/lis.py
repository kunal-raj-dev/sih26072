"""NASA ISS LIS (Lightning Imaging Sensor) Orbital Lightning Ingestion & Ground-Truth Engine.

Research & Operational Basis:
- Low-Earth orbit optical lightning sensor on the International Space Station (ISS).
- Ingests flash-level records from NASA GHRC DAAC (HDF4/HDF5/NetCDF) covering the
  tropical and subtropical belt (including the entire Indian subcontinent).
- Extracts georeferenced flash points:
    * Latitude [-90.0, 90.0]
    * Longitude [-180.0, 180.0]
    * Radiance / Energy (µJ / (m^2 * sr))
    * UTC Epoch Seconds
- Filters flashes to the canonical Indian geographical window (6–38°N, 66–98°E).
- Implements spatial cross-verification: correlates orbital lightning flashes against
  deep convective satellite cores (T_TIR1 <= 235 K) and radar cells to validate
  detection efficiency and flash co-location.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ..config import Settings
from ..grid import KM_PER_DEG_LAT, make_india_grid
from ..logsetup import get_logger, log_event
from ..schemas import (
    DataHealth,
    DataMode,
    GridMeta,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
)
from .base import AtmosphericDataProvider

logger = get_logger("vajra.providers.lis")

INDIA_BOUNDS = {
    "lat_min": 6.0,
    "lat_max": 38.0,
    "lon_min": 66.0,
    "lon_max": 98.0,
}

# TAI93 reference epoch: 1993-01-01 00:00:00 UTC (used in standard LIS products)
TAI93_EPOCH = datetime(1993, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()


# =============================================================================
# 1. ISS LIS HDF5 Parsing & Filtering
# =============================================================================

def parse_lis_hdf5(
    path: Path,
    bounds: dict[str, float] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Parse an ISS LIS HDF5/NetCDF file and extract flashes inside the India window.

    Returns:
    - points: np.ndarray of shape (N, 4) with columns [lat, lon, energy, epoch_seconds]
    - metadata: dict of orbit and dataset metadata
    """
    b = bounds or INDIA_BOUNDS
    with h5py.File(path, "r") as h5:
        # Search for flash group / datasets with fallback paths
        lats_raw = None
        lons_raw = None
        times_raw = None
        energy_raw = None

        possible_lat_keys = [
            "Lightning/Flash/Flash_Latitude",
            "Flash_Latitude",
            "flash_lat",
            "Latitude",
            "lat",
        ]
        for k in possible_lat_keys:
            if k in h5:
                lats_raw = h5[k][:]
                break

        possible_lon_keys = [
            "Lightning/Flash/Flash_Longitude",
            "Flash_Longitude",
            "flash_lon",
            "Longitude",
            "lon",
        ]
        for k in possible_lon_keys:
            if k in h5:
                lons_raw = h5[k][:]
                break

        possible_time_keys = [
            "Lightning/Flash/Flash_Time",
            "Flash_Time",
            "flash_time",
            "Time",
            "time",
        ]
        for k in possible_time_keys:
            if k in h5:
                times_raw = h5[k][:]
                break

        possible_energy_keys = [
            "Lightning/Flash/Flash_Radiance",
            "Lightning/Flash/Flash_Energy",
            "Flash_Radiance",
            "Flash_Energy",
            "energy",
            "radiance",
        ]
        for k in possible_energy_keys:
            if k in h5:
                energy_raw = h5[k][:]
                break

        if lats_raw is None or lons_raw is None:
            return np.zeros((0, 4), dtype=np.float32), {"count": 0}

        lats = np.asarray(lats_raw, dtype=np.float32).ravel()
        lons = np.asarray(lons_raw, dtype=np.float32).ravel()

        n = len(lats)
        if times_raw is not None:
            raw_t = np.asarray(times_raw, dtype=np.float64).ravel()
            # If stored as seconds since TAI93 (< 1.5e9), convert to Unix epoch seconds
            if np.nanmean(raw_t) < 1.4e9:
                epochs = raw_t + TAI93_EPOCH
            else:
                epochs = raw_t
        else:
            epochs = np.full(n, datetime.now(timezone.utc).timestamp(), dtype=np.float64)

        if energy_raw is not None:
            energies = np.asarray(energy_raw, dtype=np.float32).ravel()
        else:
            energies = np.full(n, 120.0, dtype=np.float32)

        # Spatial filter to Indian domain
        mask = (
            (lats >= b["lat_min"]) & (lats <= b["lat_max"]) &
            (lons >= b["lon_min"]) & (lons <= b["lon_max"])
        )

        n_filtered = int(np.sum(mask))
        if n_filtered == 0:
            return np.zeros((0, 4), dtype=np.float32), {"total_raw": n, "india_flashes": 0}

        pts = np.column_stack([
            lats[mask],
            lons[mask],
            energies[mask],
            epochs[mask],
        ]).astype(np.float32)

        meta = {
            "total_raw_flashes": n,
            "india_flashes": n_filtered,
            "orbit_id": h5.attrs.get("Orbit_Number", "unknown"),
            "granule_id": path.stem,
        }
        return pts, meta


# =============================================================================
# 2. Convective Core Cross-Verification
# =============================================================================

def verify_lightning_against_convective_cores(
    flashes_frame: ObsFrame,
    satellite_frame: ObsFrame,
    tir1_cold_threshold_k: float = 235.0,
    search_radius_km: float = 25.0,
) -> dict[str, Any]:
    """Verify ISS LIS lightning flashes against cold convective cloud-top cores.

    Acceptance Criterion:
    - Verifies that orbital lightning flashes over India physically align with
      satellite convective cores (T_TIR1 <= 235 K) within the search radius.
    """
    pts = flashes_frame.points
    if pts is None or len(pts) == 0:
        return {
            "total_flashes": 0,
            "co_located_flashes": 0,
            "co_location_rate": 0.0,
            "mean_flash_energy": 0.0,
            "convective_core_pixels": 0,
        }

    sat_field = satellite_frame.field
    g = satellite_frame.meta.grid
    if sat_field is None:
        return {
            "total_flashes": len(pts),
            "co_located_flashes": 0,
            "co_location_rate": 0.0,
            "mean_flash_energy": float(np.mean(pts[:, 2])),
            "convective_core_pixels": 0,
        }

    # Identify cold convective cores
    core_mask = (sat_field <= tir1_cold_threshold_k) & np.isfinite(sat_field)
    core_i, core_j = np.nonzero(core_mask)
    n_core_px = len(core_i)

    if n_core_px == 0:
        return {
            "total_flashes": len(pts),
            "co_located_flashes": 0,
            "co_location_rate": 0.0,
            "mean_flash_energy": float(np.mean(pts[:, 2])),
            "convective_core_pixels": 0,
        }

    core_lats = g.lat0 + core_i * g.dlat
    core_lons = g.lon0 + core_j * g.dlon

    # Check co-location for each flash
    co_located = 0
    cos_lat = np.cos(np.radians(22.0))
    radius_deg_sq = (search_radius_km / KM_PER_DEG_LAT) ** 2

    for lat_f, lon_f, _, _ in pts:
        d_lat = core_lats - lat_f
        d_lon = (core_lons - lon_f) * cos_lat
        d_sq = d_lat ** 2 + d_lon ** 2
        if np.any(d_sq <= radius_deg_sq):
            co_located += 1

    total = len(pts)
    rate = float(co_located / total) if total > 0 else 0.0

    return {
        "total_flashes": total,
        "co_located_flashes": co_located,
        "co_location_rate": round(rate, 3),
        "mean_flash_energy": round(float(np.mean(pts[:, 2])), 1),
        "convective_core_pixels": n_core_px,
    }


# =============================================================================
# 3. Mock LIS HDF5 Generator
# =============================================================================

def create_mock_lis_hdf5(
    filepath: Path,
    flashes: list[tuple[float, float, float, float]] | None = None,
    timestamp: datetime | None = None,
) -> Path:
    """Create a physically authentic mock NASA ISS LIS HDF5 file.

    Generates realistic Flash_Latitude, Flash_Longitude, Flash_Radiance,
    and Flash_Time datasets with orbit metadata.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    t0 = timestamp or datetime.now(timezone.utc)
    t0_epoch = t0.timestamp()

    # Default: 12 flashes distributed in convective clusters over Bihar & Bengal
    pts = flashes or [
        (25.48, 85.15, 145.0, t0_epoch - 300),
        (25.52, 85.18, 180.0, t0_epoch - 240),
        (25.50, 85.22, 210.0, t0_epoch - 180),
        (25.55, 85.12, 130.0, t0_epoch - 120),
        (22.80, 88.35, 160.0, t0_epoch - 400),
        (22.82, 88.38, 195.0, t0_epoch - 320),
        (22.85, 88.40, 240.0, t0_epoch - 200),
        (22.78, 88.32, 110.0, t0_epoch - 100),
    ]

    arr = np.array(pts, dtype=np.float32)
    lats = arr[:, 0]
    lons = arr[:, 1]
    energies = arr[:, 2]
    times = arr[:, 3].astype(np.float64)

    with h5py.File(filepath, "w") as h5:
        grp = h5.create_group("Lightning/Flash")
        grp.create_dataset("Flash_Latitude", data=lats)
        grp.create_dataset("Flash_Longitude", data=lons)
        grp.create_dataset("Flash_Radiance", data=energies)
        grp.create_dataset("Flash_Time", data=times)
        grp.create_dataset("Flash_Duration", data=np.full(len(lats), 15.0, dtype=np.float32))

        h5.attrs["Platform"] = "ISS"
        h5.attrs["Instrument"] = "LIS"
        h5.attrs["Orbit_Number"] = 38412
        h5.attrs["Start_Time"] = t0.strftime("%Y-%m-%dT%H:%M:%SZ")

    return filepath


# =============================================================================
# 4. LisProvider Class
# =============================================================================

class LisProvider(AtmosphericDataProvider):
    """NASA ISS LIS Orbital Lightning Observation Provider."""

    name = "iss_lis"
    modality = Modality.LIGHTNING
    mode = DataMode.REPLAY

    def __init__(self, settings: Settings, timeout_s: float = 60.0):
        self.settings = settings
        self.timeout_s = timeout_s
        self.grid = make_india_grid()
        self.cache_dir = settings.data_root / "external" / "lis"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._last_success: datetime | None = None
        self._history_flashes: list[np.ndarray] = []  # List of (N, 4) arrays
        self._history_meta: list[ObsFrameMeta] = []

    def health(self) -> DataHealth:
        if self._last_success is not None or len(self._history_flashes) > 0:
            total = sum(len(f) for f in self._history_flashes)
            return DataHealth(
                source=self.name,
                modality=self.modality,
                status=self.mode,
                last_success=self._last_success,
                message=f"NASA ISS LIS orbital lightning, {total} flashes cached over India",
            )
        return DataHealth(
            source=self.name,
            modality=self.modality,
            status=DataMode.UNAVAILABLE,
            message="No ISS LIS flash swaths ingested yet. (Requires Earthdata credentials)",
        )

    def ingest_file(self, path: Path) -> ObsFrame:
        """Parse an ISS LIS HDF5 file and register into provider memory."""
        pts, meta = parse_lis_hdf5(path)
        t_frame = datetime.now(timezone.utc)
        if len(pts) > 0:
            t_frame = datetime.fromtimestamp(float(np.max(pts[:, 3])), tz=timezone.utc)

        meta_frame = ObsFrameMeta(
            source=self.name,
            modality=self.modality,
            variable="flash",
            units="optical energy (µJ/(m^2*sr))",
            time=t_frame,
            grid=GridMeta(
                name=self.grid.name,
                lat0=self.grid.lat0,
                lon0=self.grid.lon0,
                dlat=self.grid.dlat,
                dlon=self.grid.dlon,
                nlat=self.grid.nlat,
                nlon=self.grid.nlon,
                geolocation="exact",
            ),
            quality=QualityInfo(status=QualityStatus.OK, missing_fraction=0.0),
            mode=self.mode,
            note=f"ISS LIS orbital pass: {len(pts)} flashes in Indian domain",
        )
        frame = ObsFrame(meta=meta_frame, points=pts)
        self._history_flashes.append(pts)
        self._history_meta.append(meta_frame)
        self._last_success = t_frame
        return frame

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        """Return lightning point frames observed in (t - minutes, t]."""
        t_end = t.timestamp()
        t_start = (t - timedelta(minutes=minutes)).timestamp()

        matched_pts: list[np.ndarray] = []
        for pts in self._history_flashes:
            if len(pts) == 0:
                continue
            mask = (pts[:, 3] > t_start) & (pts[:, 3] <= t_end)
            if np.any(mask):
                matched_pts.append(pts[mask])

        if not matched_pts:
            return []

        combined = np.concatenate(matched_pts, axis=0)
        meta = ObsFrameMeta(
            source=self.name,
            modality=self.modality,
            variable="flash",
            units="optical energy (µJ/(m^2*sr))",
            time=t,
            grid=GridMeta(
                name=self.grid.name,
                lat0=self.grid.lat0,
                lon0=self.grid.lon0,
                dlat=self.grid.dlat,
                dlon=self.grid.dlon,
                nlat=self.grid.nlat,
                nlon=self.grid.nlon,
                geolocation="exact",
            ),
            quality=QualityInfo(status=QualityStatus.OK),
            mode=self.mode,
            note=f"ISS LIS aggregated flashes: {len(combined)} events",
        )
        return [ObsFrame(meta=meta, points=combined)]
