"""ISRO MOSDAC INSAT-3D/3DR/3DS Satellite Provider & Convective Initiation Engine.

Research & Operational Basis:
- Primary geostationary observations over the Indian subcontinent from INSAT-3D/3DR/3DS.
- Ingests L1B/L2 HDF5 files containing Imager channels:
    * TIR1 (10.8 µm): Thermal Infrared 1 (cloud top temperature & cooling rate)
    * WV   (6.8 µm):  Water Vapor (mid/upper troposphere moisture)
    * TIR2 (12.0 µm): Thermal Infrared 2 (split window)
    * MIR  (3.9 µm):  Middle Infrared
    * VIS  (0.65 µm): Visible channel
- Calibrates raw counts or spectral radiances to physical Kelvin brightness temperature
  using the inverse Planck radiation relation with sensor central wavenumbers and LUTs.
- Calculates multi-spectral Convective Initiation (CI) indicators:
    * (T_IR1 - T_WV) Brightness Temperature Difference (BTD)
    * 15-min / 30-min cloud-top cooling rate dT_b / dt (< -4 K / 15 min)
    * Tri-spectral CI candidate segmentation
- Persists processed and calibrated Indian regional frames to data/processed/insat/.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ..config import Settings
from ..grid import GridSpec, make_india_grid
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

logger = get_logger("vajra.providers.mosdac")

# Planck radiation constants (CODATA / meteorological standard)
# c1 = 2 * h * c^2 = 1.19104276e-5 mW * m^-2 * sr^-1 * cm^4
# c2 = (h * c) / k = 1.43877688 cm * K
PLANCK_C1 = 1.19104276e-5
PLANCK_C2 = 1.43877688

# INSAT-3D/3DR/3DS Imager nominal central wavenumbers nu_c (cm^-1)
# nu_c = 10000.0 / wavelength_microns
CHANNEL_WAVENUMBERS: dict[str, float] = {
    "TIR1": 925.926,    # 10.8 µm
    "WV": 1470.588,     # 6.8 µm
    "TIR2": 833.333,    # 12.0 µm
    "MIR": 2564.103,    # 3.9 µm
    "VIS": 15384.615,   # 0.65 µm
}

# Empirical sensor band correction coefficients: T_eff = a + b * T_brightness
BAND_CORRECTION: dict[str, tuple[float, float]] = {
    "TIR1": (0.45, 0.998),
    "WV": (1.25, 0.995),
    "TIR2": (0.35, 0.998),
    "MIR": (1.80, 0.992),
}


# =============================================================================
# 1. Physics & Radiometry: Planck Inversion & Calibration
# =============================================================================

def radiance_to_kelvin(
    radiance: np.ndarray | float,
    channel: str = "TIR1",
    apply_band_correction: bool = True,
) -> np.ndarray | float:
    """Convert spectral radiance (mW / (m^2 * sr * cm^-1)) to Kelvin brightness temperature.

    Uses the inverted Planck function:
        T_b = (c2 * nu) / ln(1 + (c1 * nu^3) / L)
    followed by linear band-effective temperature adjustment:
        T_eff = a + b * T_b
    """
    nu = CHANNEL_WAVENUMBERS.get(channel.upper(), 925.926)
    arr = np.asarray(radiance, dtype=np.float64)

    # Avoid divide-by-zero or log of negative/zero radiance
    rad_safe = np.clip(arr, 1e-4, 500.0)
    c1_nu3 = PLANCK_C1 * (nu ** 3)
    c2_nu = PLANCK_C2 * nu

    t_b = c2_nu / np.log1p(c1_nu3 / rad_safe)

    if apply_band_correction and channel.upper() in BAND_CORRECTION:
        a, b = BAND_CORRECTION[channel.upper()]
        t_eff = a + b * t_b
    else:
        t_eff = t_b

    # Valid physical Kelvin bounds [150.0, 350.0]
    out = np.clip(t_eff, 150.0, 350.0).astype(np.float32)
    if np.isscalar(radiance):
        return float(out)
    return out


def kelvin_to_radiance(
    temperature_k: np.ndarray | float,
    channel: str = "TIR1",
) -> np.ndarray | float:
    """Forward Planck function: compute spectral radiance for a given temperature in Kelvin."""
    nu = CHANNEL_WAVENUMBERS.get(channel.upper(), 925.926)
    arr = np.asarray(temperature_k, dtype=np.float64)
    t_safe = np.clip(arr, 100.0, 400.0)

    c1_nu3 = PLANCK_C1 * (nu ** 3)
    c2_nu = PLANCK_C2 * nu

    rad = c1_nu3 / np.expm1(c2_nu / t_safe)
    out = rad.astype(np.float32)
    if np.isscalar(temperature_k):
        return float(out)
    return out


def counts_to_kelvin(
    counts: np.ndarray,
    lut: np.ndarray | None = None,
    slope: float = 1.0,
    intercept: float = 0.0,
    channel: str = "TIR1",
) -> np.ndarray:
    """Convert raw 10-bit or 16-bit digital counts to calibrated Kelvin.

    If a lookup table (LUT) is provided (as found in MOSDAC L1B files):
        Uses LUT indexing. If values in LUT are already Kelvin (>100), returns directly;
        if values are radiances, passes through radiance_to_kelvin.
    Otherwise:
        L = counts * slope + intercept, then converts via radiance_to_kelvin.
    """
    arr = np.asarray(counts)
    if lut is not None:
        lut_arr = np.asarray(lut)
        max_idx = len(lut_arr) - 1
        idx = np.clip(arr.astype(np.int64), 0, max_idx)
        val = lut_arr[idx]
        if np.nanmean(val) > 100.0:  # already Kelvin
            return np.clip(val, 150.0, 350.0).astype(np.float32)
        return radiance_to_kelvin(val, channel=channel)

    radiance = arr.astype(np.float32) * slope + intercept
    return radiance_to_kelvin(radiance, channel=channel)


# =============================================================================
# 2. Multi-Spectral Convective Initiation (CI) & Precursors
# =============================================================================

def compute_btd_ir_wv(tir1_k: np.ndarray, wv_k: np.ndarray) -> np.ndarray:
    """Compute Brightness Temperature Difference: BTD = T_IR1 - T_WV (Kelvin).

    Physical interpretation:
    - Tropopause-penetrating overshooting tops: BTD >= -1 K to +4 K.
    - Deep glaciated anvil clouds: -4 K <= BTD < -1 K.
    - Low/mid-level non-convective clouds: BTD < -10 K to -30 K.
    """
    return (np.asarray(tir1_k, dtype=np.float32) - np.asarray(wv_k, dtype=np.float32))


def compute_cooling_rate(
    tir1_curr: np.ndarray,
    tir1_prev: np.ndarray,
    dt_minutes: float = 15.0,
) -> np.ndarray:
    """Compute cloud-top cooling rate: dT_b / dt (in Kelvin per 15 minutes).

    Negative values denote cooling (temperature drop = cloud top rising).
    Convective updraft signal: cooling_rate <= -4.0 K / 15 min.
    """
    curr = np.asarray(tir1_curr, dtype=np.float32)
    prev = np.asarray(tir1_prev, dtype=np.float32)
    dt_safe = max(float(dt_minutes), 1.0)
    # Scale to standard 15-minute meteorological convention
    rate = (curr - prev) * (15.0 / dt_safe)
    return rate


def detect_convective_initiation(
    tir1_k: np.ndarray,
    wv_k: np.ndarray | None = None,
    cooling_rate_15m: np.ndarray | None = None,
    cooling_threshold_k: float = -4.0,
    max_tir1_k: float = 273.15,
    min_btd_k: float = -5.0,
    grid: GridSpec | None = None,
) -> dict[str, Any]:
    """Flag satellite pixels exhibiting Convective Initiation (CI) precursor signals.

    Standard Satellite Meteorology CI Decision Rules (Mecikalski & Bedka 2006):
    1. Cloud top must be glaciated or supercooled: T_TIR1 <= max_tir1_k (273.15 K).
    2. Strong vertical updraft: cooling_rate_15m <= cooling_threshold_k (-4.0 K / 15 min).
    3. Deep tropospheric depth: if WV available, BTD (TIR1 - WV) >= min_btd_k (-5.0 K).

    Returns a dict containing:
    - `ci_mask`: 2D boolean array of candidate pixels.
    - `candidate_count`: Total number of active candidate pixels.
    - `candidates`: List of detected pre-convective clusters with centroid lat/lon and stats.
    """
    tir1 = np.asarray(tir1_k, dtype=np.float32)
    mask = (tir1 <= max_tir1_k) & (tir1 >= 180.0)

    if cooling_rate_15m is not None:
        cr = np.asarray(cooling_rate_15m, dtype=np.float32)
        mask &= (cr <= cooling_threshold_k)

    btd = None
    if wv_k is not None:
        btd = compute_btd_ir_wv(tir1, wv_k)
        mask &= (btd >= min_btd_k)

    # Segment connected candidate clusters (pure numpy 4-connectivity)
    candidates: list[dict[str, Any]] = []
    if np.any(mask):
        nlat, nlon = mask.shape
        visited = np.zeros_like(mask, dtype=bool)

        for i in range(nlat):
            for j in range(nlon):
                if mask[i, j] and not visited[i, j]:
                    # Breadth-first flood fill
                    cluster_i = [i]
                    cluster_j = [j]
                    visited[i, j] = True
                    idx = 0
                    while idx < len(cluster_i):
                        ci, cj = cluster_i[idx], cluster_j[idx]
                        idx += 1
                        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            ni, nj = ci + di, cj + dj
                            if 0 <= ni < nlat and 0 <= nj < nlon:
                                if mask[ni, nj] and not visited[ni, nj]:
                                    visited[ni, nj] = True
                                    cluster_i.append(ni)
                                    cluster_j.append(nj)

                    area_px = len(cluster_i)
                    if area_px >= 3:  # minimum cluster threshold
                        mean_i = float(np.mean(cluster_i))
                        mean_j = float(np.mean(cluster_j))
                        c_t = float(np.min(tir1[cluster_i, cluster_j]))
                        c_cr = float(np.mean(cooling_rate_15m[cluster_i, cluster_j])) if cooling_rate_15m is not None else -4.0
                        c_btd = float(np.mean(btd[cluster_i, cluster_j])) if btd is not None else 0.0

                        lat_c = grid.lat0 + mean_i * grid.dlat if grid else 25.0
                        lon_c = grid.lon0 + mean_j * grid.dlon if grid else 85.0

                        candidates.append({
                            "centroid_lat": round(lat_c, 3),
                            "centroid_lon": round(lon_c, 3),
                            "area_px": area_px,
                            "min_tir1_k": round(c_t, 1),
                            "mean_cooling_rate_15m": round(c_cr, 2),
                            "mean_btd_k": round(c_btd, 2),
                            "ci_confidence": min(1.0, 0.4 + 0.1 * abs(c_cr) / 4.0 + (0.2 if c_btd >= -2.0 else 0.0)),
                        })

    return {
        "ci_mask": mask,
        "candidate_count": int(np.sum(mask)),
        "candidates": candidates,
    }


# =============================================================================
# 3. Spatial Windowing & Indian Grid Resampling
# =============================================================================

def resample_to_india_grid(
    data: np.ndarray,
    src_lats: np.ndarray,
    src_lons: np.ndarray,
    target_grid: GridSpec | None = None,
) -> np.ndarray:
    """Extract and resample a satellite channel onto the canonical 0.1° India regional grid."""
    grid = target_grid or make_india_grid()
    out = np.full((grid.nlat, grid.nlon), np.nan, dtype=np.float32)

    # 1D or 2D coordinate vectors
    if src_lats.ndim == 1 and src_lons.ndim == 1:
        # Regular or rectangular grid: fast bilinear / nearest slicing
        lat_idx = np.searchsorted(src_lats if src_lats[0] < src_lats[-1] else src_lats[::-1],
                                  [grid.lat_min, grid.lat_max])
        # Direct nearest neighbor index mapping
        target_lat = grid.lat0 + np.arange(grid.nlat) * grid.dlat
        target_lon = grid.lon0 + np.arange(grid.nlon) * grid.dlon

        # Clip indices to source bounds
        i_src = np.clip(np.interp(target_lat, src_lats if src_lats[0] < src_lats[-1] else src_lats[::-1],
                                  np.arange(len(src_lats))).astype(int), 0, data.shape[0] - 1)
        j_src = np.clip(np.interp(target_lon, src_lons if src_lons[0] < src_lons[-1] else src_lons[::-1],
                                  np.arange(len(src_lons))).astype(int), 0, data.shape[1] - 1)

        out = data[np.ix_(i_src, j_src)].astype(np.float32)
    else:
        # 2D curvilinear swath or satellite projection
        # Nearest neighbor interpolation for Indian domain
        india_mask = (src_lats >= grid.lat_min - 0.5) & (src_lats <= grid.lat_max + 0.5) & \
                     (src_lons >= grid.lon_min - 0.5) & (src_lons <= grid.lon_max + 0.5)

        if not np.any(india_mask):
            return out

        sub_lats = src_lats[india_mask]
        sub_lons = src_lons[india_mask]
        sub_data = data[india_mask]

        # Map each target grid cell
        for i in range(grid.nlat):
            lat_t = grid.lat0 + i * grid.dlat
            for j in range(grid.nlon):
                lon_t = grid.lon0 + j * grid.dlon
                # Fast box filter
                dist_sq = (sub_lats - lat_t) ** 2 + (sub_lons - lon_t) ** 2
                best = np.argmin(dist_sq)
                if dist_sq[best] <= 0.04:  # within ~0.2 deg
                    out[i, j] = sub_data[best]

    return out


# =============================================================================
# 4. Processed Frame Persistence (data/processed/insat/)
# =============================================================================

def save_processed_satellite_frame(
    frame: ObsFrame,
    target_dir: Path | None = None,
    auxiliary: dict[str, np.ndarray] | None = None,
) -> Path:
    """Persist calibrated Indian satellite frame and auxiliary fields into compressed NPZ."""
    out_dir = target_dir or (Path(__file__).resolve().parents[3] / "data" / "processed" / "insat")
    out_dir.mkdir(parents=True, exist_ok=True)

    dt_str = frame.meta.time.strftime("%Y%m%d_%H%M%S")
    filename = f"insat_{frame.meta.variable}_{dt_str}.npz"
    filepath = out_dir / filename

    arrays: dict[str, Any] = {"field": frame.field}
    if auxiliary:
        for k, v in auxiliary.items():
            arrays[k] = v

    meta_json = json.dumps(frame.meta.model_dump(), default=str)
    arrays["_meta_json"] = np.array(meta_json)

    np.savez_compressed(filepath, **arrays)
    return filepath


def load_processed_satellite_frame(path: Path) -> tuple[ObsFrame, dict[str, np.ndarray]]:
    """Load an observation frame and auxiliary channels from a persisted NPZ file."""
    with np.load(path, allow_pickle=False) as npz:
        meta_dict = json.loads(str(npz["_meta_json"]))
        meta = ObsFrameMeta(**meta_dict)
        field = npz["field"]
        aux = {k: npz[k] for k in npz.files if k not in ("field", "_meta_json")}
        frame = ObsFrame(meta=meta, field=field)
        return frame, aux


# =============================================================================
# 5. Synthetic / Mock MOSDAC HDF5 Generator
# =============================================================================

def create_mock_mosdac_hdf5(
    filepath: Path,
    timestamp: datetime,
    grid: GridSpec | None = None,
    convective_cores: list[tuple[float, float, float]] | None = None,
    channel_counts: bool = True,
) -> Path:
    """Create a physically authentic mock MOSDAC INSAT-3D/3DR L1B HDF5 file.

    Generates realistic TIR1, WV, and TIR2 datasets with calibrated attributes,
    lookup tables, coordinates, and optional simulated convective cooling cells.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    g = grid or make_india_grid()
    nlat, nlon = g.nlat, g.nlon

    # Base background: warm land/ocean in India summer (295 K - 305 K)
    tir1_k = np.full((nlat, nlon), 298.0, dtype=np.float32)
    wv_k = np.full((nlat, nlon), 242.0, dtype=np.float32)
    tir2_k = np.full((nlat, nlon), 296.0, dtype=np.float32)

    # Embed convective cores if requested: (lat, lon, min_temp_k)
    cores = convective_cores or [
        (25.5, 85.2, 215.0),  # Severe Nor'wester core over Bihar/Patna
        (22.8, 88.3, 222.0),  # Storm over Bengal
    ]
    y_grid, x_grid = np.ogrid[:nlat, :nlon]
    for c_lat, c_lon, c_temp in cores:
        i_c = int((c_lat - g.lat0) / g.dlat)
        j_c = int((c_lon - g.lon0) / g.dlon)
        dist = np.hypot(y_grid - i_c, x_grid - j_c)
        shield = np.exp(-0.5 * (dist / 14.0) ** 2)
        tir1_k = np.minimum(tir1_k, (298.0 - (298.0 - c_temp) * shield).astype(np.float32))
        wv_k = np.minimum(wv_k, (242.0 - (242.0 - (c_temp + 3.0)) * shield).astype(np.float32))

    lats = (g.lat0 + np.arange(nlat) * g.dlat).astype(np.float32)
    lons = (g.lon0 + np.arange(nlon) * g.dlon).astype(np.float32)

    with h5py.File(filepath, "w") as h5:
        # Datasets
        if channel_counts:
            # Convert Kelvin to radiance then 10-bit counts (0-1023)
            rad1 = kelvin_to_radiance(tir1_k, "TIR1")
            counts1 = np.clip(rad1 * 5.0, 0, 1023).astype(np.uint16)
            ds_tir1 = h5.create_dataset("IMG_TIR1", data=counts1, compression="gzip")
            ds_tir1.attrs["Slope"] = 0.2
            ds_tir1.attrs["Intercept"] = 0.0
            ds_tir1.attrs["Units"] = "Counts"
            ds_tir1.attrs["Central_Wavenumber"] = 925.926

            # Lookup table for TIR1: count -> Kelvin
            lut_counts = np.arange(1024, dtype=np.float32) * 0.2
            lut_k = radiance_to_kelvin(lut_counts, "TIR1")
            h5.create_dataset("IMG_TIR1_LUT", data=lut_k)

            rad_wv = kelvin_to_radiance(wv_k, "WV")
            counts_wv = np.clip(rad_wv * 10.0, 0, 1023).astype(np.uint16)
            ds_wv = h5.create_dataset("IMG_WV", data=counts_wv, compression="gzip")
            ds_wv.attrs["Slope"] = 0.1
            ds_wv.attrs["Intercept"] = 0.0
            ds_wv.attrs["Units"] = "Counts"
            ds_wv.attrs["Central_Wavenumber"] = 1470.588

            counts2 = np.clip(kelvin_to_radiance(tir2_k, "TIR2") * 5.0, 0, 1023).astype(np.uint16)
            ds_tir2 = h5.create_dataset("IMG_TIR2", data=counts2, compression="gzip")
            ds_tir2.attrs["Slope"] = 0.2
            ds_tir2.attrs["Intercept"] = 0.0
            ds_tir2.attrs["Units"] = "Counts"
        else:
            # Calibrated Kelvin arrays
            ds_tir1 = h5.create_dataset("IMG_TIR1", data=tir1_k)
            ds_tir1.attrs["Units"] = "Kelvin"
            h5.create_dataset("IMG_WV", data=wv_k)
            h5.create_dataset("IMG_TIR2", data=tir2_k)

        h5.create_dataset("Latitude", data=lats)
        h5.create_dataset("Longitude", data=lons)

        # Global attributes
        h5.attrs["Satellite_Name"] = "INSAT-3DR"
        h5.attrs["Sensor_ID"] = "IMAGER"
        h5.attrs["Acquisition_Time"] = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        h5.attrs["Product_Type"] = "L1B"

    return filepath


# =============================================================================
# 6. MosdacProvider Class
# =============================================================================

class MosdacProvider(AtmosphericDataProvider):
    """ISRO MOSDAC INSAT-3D/3DR/3DS Geostationary Satellite Observation Provider."""

    name = "mosdac_insat"
    modality = Modality.SATELLITE
    mode = DataMode.REPLAY

    def __init__(self, settings: Settings, timeout_s: float = 60.0):
        self.settings = settings
        self.timeout_s = timeout_s
        self.grid = make_india_grid()
        self.cache_dir = settings.data_root / "external" / "mosdac"
        self.processed_dir = settings.data_root / "processed" / "insat"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self._last_success: datetime | None = None
        self._last_error = "" if settings.mosdac.configured else (
            "MOSDAC credentials not configured (.env: MOSDAC_USERNAME/PASSWORD). "
            "Free registration available at https://www.mosdac.gov.in"
        )
        self._history_cache: dict[datetime, ObsFrame] = {}

    def health(self) -> DataHealth:
        if self._last_success is not None or len(self._history_cache) > 0:
            return DataHealth(
                source=self.name,
                modality=self.modality,
                status=self.mode,
                last_success=self._last_success or max(self._history_cache.keys(), default=None),
                message=f"INSAT-3D/3DR Imager calibrated Kelvin, {len(self._history_cache)} slots cached",
            )
        return DataHealth(
            source=self.name,
            modality=self.modality,
            status=DataMode.UNAVAILABLE,
            message=self._last_error or "No INSAT satellite frames ingested yet",
        )

    def parse_mosdac_file(self, path: Path) -> tuple[ObsFrame, dict[str, np.ndarray]]:
        """Parse MOSDAC HDF5 or processed NPZ into calibrated ObsFrame and auxiliary channels."""
        if path.suffix == ".npz":
            return load_processed_satellite_frame(path)

        with h5py.File(path, "r") as h5:
            # 1. Determine Acquisition Time
            acq_str = h5.attrs.get("Acquisition_Time", "")
            if isinstance(acq_str, bytes):
                acq_str = acq_str.decode("utf-8")
            if acq_str:
                dt = datetime.fromisoformat(acq_str.replace("Z", "+00:00"))
            else:
                # Infer from filename
                dt = datetime.now(timezone.utc)

            # 2. Extract Latitude / Longitude
            lats = h5["Latitude"][:] if "Latitude" in h5 else None
            lons = h5["Longitude"][:] if "Longitude" in h5 else None

            # 3. Extract and Calibrate TIR1
            if "IMG_TIR1" in h5:
                raw_tir1 = h5["IMG_TIR1"][:]
                lut = h5["IMG_TIR1_LUT"][:] if "IMG_TIR1_LUT" in h5 else None
                slope = float(h5["IMG_TIR1"].attrs.get("Slope", 1.0))
                intercept = float(h5["IMG_TIR1"].attrs.get("Intercept", 0.0))
                units = str(h5["IMG_TIR1"].attrs.get("Units", ""))
                is_counts = "count" in units.lower() or lut is not None or slope != 1.0 or intercept != 0.0
                if not is_counts and ("kelvin" in units.lower() or (150.0 <= np.nanmean(raw_tir1) <= 350.0)):
                    tir1_k = np.clip(raw_tir1, 150.0, 350.0).astype(np.float32)
                else:
                    tir1_k = counts_to_kelvin(raw_tir1, lut=lut, slope=slope, intercept=intercept, channel="TIR1")
            elif "TIR1" in h5:
                tir1_k = np.clip(h5["TIR1"][:], 150.0, 350.0).astype(np.float32)
            else:
                raise KeyError(f"No TIR1 dataset found in {path.name}")

            # 4. Extract WV if present
            wv_k = None
            if "IMG_WV" in h5:
                raw_wv = h5["IMG_WV"][:]
                lut_wv = h5["IMG_WV_LUT"][:] if "IMG_WV_LUT" in h5 else None
                slope_wv = float(h5["IMG_WV"].attrs.get("Slope", 1.0))
                intercept_wv = float(h5["IMG_WV"].attrs.get("Intercept", 0.0))
                units_wv = str(h5["IMG_WV"].attrs.get("Units", ""))
                is_wv_counts = "count" in units_wv.lower() or lut_wv is not None or slope_wv != 1.0 or intercept_wv != 0.0
                if not is_wv_counts and ("kelvin" in units_wv.lower() or (150.0 <= np.nanmean(raw_wv) <= 350.0)):
                    wv_k = np.clip(raw_wv, 150.0, 350.0).astype(np.float32)
                else:
                    wv_k = counts_to_kelvin(raw_wv, lut=lut_wv, slope=slope_wv, intercept=intercept_wv, channel="WV")

            # Resample to canonical 0.1° grid if dimensions differ
            if tir1_k.shape != (self.grid.nlat, self.grid.nlon) and lats is not None and lons is not None:
                tir1_k = resample_to_india_grid(tir1_k, lats, lons, self.grid)
                if wv_k is not None:
                    wv_k = resample_to_india_grid(wv_k, lats, lons, self.grid)

            meta = ObsFrameMeta(
                source=self.name,
                modality=self.modality,
                variable="bt_ir107",
                units="K",
                time=dt,
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
                quality=QualityInfo(status=QualityStatus.OK, missing_fraction=float(np.mean(np.isnan(tir1_k)))),
                mode=self.mode,
                note=f"MOSDAC calibrated brightness temperature ({h5.attrs.get('Satellite_Name', 'INSAT-3D')})",
            )
            frame = ObsFrame(meta=meta, field=tir1_k)
            aux: dict[str, np.ndarray] = {}
            if wv_k is not None:
                aux["wv"] = wv_k
                aux["btd"] = compute_btd_ir_wv(tir1_k, wv_k)

            return frame, aux

    def ingest_frame(self, frame: ObsFrame, aux: dict[str, np.ndarray] | None = None) -> None:
        """Register a parsed or generated frame into provider memory and storage."""
        self._history_cache[frame.meta.time] = frame
        self._last_success = frame.meta.time
        # Save to processed storage
        save_processed_satellite_frame(frame, target_dir=self.processed_dir, auxiliary=aux)

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        """Return frames in (t - minutes, t], oldest first, annotated with cooling rates."""
        t_start = t - timedelta(minutes=minutes)
        slots = sorted([dt for dt in self._history_cache.keys() if t_start < dt <= t])
        frames = [self._history_cache[dt] for dt in slots]

        # Calculate cooling rate between consecutive frames if 2+ exist
        if len(frames) >= 2:
            dt_min = (frames[-1].meta.time - frames[-2].meta.time).total_seconds() / 60.0
            if dt_min > 0:
                cr = compute_cooling_rate(frames[-1].field, frames[-2].field, dt_minutes=dt_min)
                ci_result = detect_convective_initiation(
                    frames[-1].field,
                    cooling_rate_15m=cr,
                    grid=self.grid,
                )
                note = frames[-1].meta.note or ""
                frames[-1] = frames[-1].with_meta(
                    note=note + f" | Cooling dT/dt: {float(np.nanmin(cr)):.1f} K/15m | CI Candidates: {ci_result['candidate_count']}"
                )

        return frames
