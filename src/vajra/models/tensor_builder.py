"""Spatiotemporal Multi-Channel Tensor Builder (Phase V2-3 / TASK-V2-3.1).

Constructs normalized 5D spatiotemporal tensors:
    X in R^{B x C x T x H x W}
for deep learning fusion across geostationary satellite radiometry, Doppler radar mosaics,
satellite precipitation rates, ground/orbital lightning, and numerical weather prediction soundings.

Channel Specification (C=8):
    0: TIR1 (Kelvin, normalized 180..320 K) -> Cloud-top height / temperature
    1: WV (Kelvin, normalized 200..280 K)   -> Mid-tropospheric moisture / subsidence
    2: Split_Diff (TIR1 - TIR2, -4..+6 K)   -> Cloud-top glaciation / optical thickness
    3: Radar_MaxZ (dBZ, normalized 0..70 dBZ) -> Column maximum reflectivity
    4: IMERG_Rain (mm/h, normalized 0..60 mm/h) -> Surface precipitation rate
    5: Flash_Density (flashes/100km², 0..25) -> Electrical activity density
    6: CAPE_Norm (J/kg, normalized 0..4000 J/kg) -> Convective Available Potential Energy
    7: Bulk_Shear_Norm (m/s, normalized 0..40 m/s) -> 0-6 km Bulk Vertical Wind Shear

Temporal depth:
    T = 4 frames spanning T-45m, T-30m, T-15m, T_0 (15-minute cadence).
Standard patch size:
    H x W = 192 x 192.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

from ..grid import GridSpec


# Normalization boundaries (physical minimum, physical maximum)
NORM_BOUNDS = {
    "tir1": (180.0, 320.0),       # Kelvin (inverted so cold cloud tops = 1.0)
    "wv": (200.0, 280.0),         # Kelvin (inverted so cold moist layers = 1.0)
    "split_diff": (-4.0, 6.0),    # Kelvin (TIR1 - TIR2)
    "radar_maxz": (0.0, 70.0),    # dBZ
    "imerg_rain": (0.0, 60.0),    # mm/h
    "flash_density": (0.0, 25.0), # flashes / 100 km²
    "cape": (0.0, 4000.0),        # J/kg
    "bulk_shear": (0.0, 40.0),    # m/s
}


def normalize_channel(data: np.ndarray, channel_name: str) -> np.ndarray:
    """Normalize physical meteorological raster to [0.0, 1.0] range."""
    arr = np.nan_to_num(data.astype(np.float32), nan=0.0)

    if channel_name == "tir1":
        # Invert: cold cloud tops (180 K) -> 1.0, warm surfaces (320 K) -> 0.0
        vmin, vmax = NORM_BOUNDS["tir1"]
        return np.clip((vmax - arr) / (vmax - vmin), 0.0, 1.0).astype(np.float32)

    elif channel_name == "wv":
        # Invert: cold moist layers (200 K) -> 1.0, dry warm layers (280 K) -> 0.0
        vmin, vmax = NORM_BOUNDS["wv"]
        return np.clip((vmax - arr) / (vmax - vmin), 0.0, 1.0).astype(np.float32)

    elif channel_name == "split_diff":
        vmin, vmax = NORM_BOUNDS["split_diff"]
        return np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0).astype(np.float32)

    elif channel_name in NORM_BOUNDS:
        vmin, vmax = NORM_BOUNDS[channel_name]
        return np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0).astype(np.float32)

    else:
        raise ValueError(f"Unknown channel name: '{channel_name}'")


def resize_or_pad_field(field: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Resample, crop, or pad a 2D field to exactly (target_h, target_w)."""
    target_h, target_w = target_shape
    cur_h, cur_w = field.shape

    if (cur_h, cur_w) == (target_h, target_w):
        return field.astype(np.float32)

    # Use bilinear/nearest interpolation via grid sampling
    y_idx = np.linspace(0, cur_h - 1, target_h)
    x_idx = np.linspace(0, cur_w - 1, target_w)

    y0 = np.floor(y_idx).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, cur_h - 1)
    x0 = np.floor(x_idx).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, cur_w - 1)

    dy = (y_idx - y0)[:, None]
    dx = (x_idx - x0)[None, :]

    c00 = field[y0[:, None], x0[None, :]]
    c01 = field[y0[:, None], x1[None, :]]
    c10 = field[y1[:, None], x0[None, :]]
    c11 = field[y1[:, None], x1[None, :]]

    interpolated = (
        (1.0 - dy) * (1.0 - dx) * c00 +
        (1.0 - dy) * dx * c01 +
        dy * (1.0 - dx) * c10 +
        dy * dx * c11
    )
    return interpolated.astype(np.float32)


def build_spatiotemporal_tensor(
    channels_dict: dict[str, list[np.ndarray]],
    target_shape: tuple[int, int] = (192, 192),
    temporal_depth: int = 4,
    missing_modalities: list[str] | None = None,
) -> np.ndarray:
    """Construct an 8-channel normalized spatiotemporal tensor.

    Parameters
    ----------
    channels_dict:
        Mapping of channel names to temporal lists of 2D arrays:
        - "tir1": list of T arrays (Kelvin)
        - "wv": list of T arrays (Kelvin)
        - "split_diff": list of T arrays (Kelvin difference)
        - "radar_maxz": list of T arrays (dBZ)
        - "imerg_rain": list of T arrays (mm/h)
        - "flash_density": list of T arrays (flashes/100km²)
        - "cape": list of T arrays (J/kg) or single 2D array
        - "bulk_shear": list of T arrays (m/s) or single 2D array
    target_shape:
        Target spatial patch size (H, W), default (192, 192).
    temporal_depth:
        Number of time frames T (default: 4).
    missing_modalities:
        List of modalities to zero-mask for offline fallback:
        Options: "satellite", "radar", "imerg", "lightning", "nwp".

    Returns
    -------
    (8, T, H, W) float32 array with all values in [0.0, 1.0].
    """
    target_h, target_w = target_shape
    missing = set(m.lower() for m in (missing_modalities or []))

    channel_keys = [
        ("tir1", "satellite"),
        ("wv", "satellite"),
        ("split_diff", "satellite"),
        ("radar_maxz", "radar"),
        ("imerg_rain", "imerg"),
        ("flash_density", "lightning"),
        ("cape", "nwp"),
        ("bulk_shear", "nwp"),
    ]

    tensor = np.zeros((8, temporal_depth, target_h, target_w), dtype=np.float32)

    for c_idx, (key, modality) in enumerate(channel_keys):
        if modality in missing:
            # Leave channel zero-masked
            continue

        raw_frames = channels_dict.get(key, [])
        if not raw_frames:
            # No data provided for this channel: remains zero
            continue

        for t_idx in range(temporal_depth):
            # Take available frame or fallback to latest available
            if t_idx < len(raw_frames):
                frame = raw_frames[t_idx]
            else:
                frame = raw_frames[-1]

            if frame is None or frame.size == 0:
                continue

            resized = resize_or_pad_field(frame, target_shape)
            norm = normalize_channel(resized, key)
            tensor[c_idx, t_idx] = norm

    return np.clip(tensor, 0.0, 1.0).astype(np.float32)


def generate_synthetic_spatiotemporal_tensor(
    batch_size: int = 1,
    temporal_depth: int = 4,
    height: int = 192,
    width: int = 192,
    missing_modalities: list[str] | None = None,
    seed: int = 42,
) -> np.ndarray:
    """Generate realistic normalized synthetic spatiotemporal tensor (B, 8, T, H, W).

    Simulates a developing multicellular convective storm moving across the domain:
    - Decreasing TIR1 temperature (cloud-top cooling from 280 K down to 210 K).
    - Increasing water vapor saturation (WV cooling towards IR).
    - Decreasing split-window BTD (glaciating anvil).
    - Emerging and intensifying radar MaxZ core (from 15 dBZ up to 58 dBZ).
    - Increasing IMERG rain rate and lightning flash density.
    - Synoptic thermodynamic CAPE environment (~2500 J/kg) and wind shear (~22 m/s).

    Parameters
    ----------
    batch_size:
        Batch size B.
    temporal_depth:
        Temporal depth T (default: 4).
    height:
        Grid height H (default: 192).
    width:
        Grid width W (default: 192).
    missing_modalities:
        Optional list of modalities to zero-mask (e.g. ["radar"]).
    seed:
        Random number generator seed.

    Returns
    -------
    (B, 8, T, H, W) float32 numpy array with all channels strictly normalized in [0.0, 1.0].
    """
    rng = np.random.default_rng(seed)
    batch = np.zeros((batch_size, 8, temporal_depth, height, width), dtype=np.float32)

    y_coords = np.arange(height, dtype=np.float32)
    x_coords = np.arange(width, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(x_coords, y_coords)

    for b in range(batch_size):
        # Initial convective storm core position
        start_y = height * (0.35 + 0.1 * rng.uniform(-1, 1))
        start_x = width * (0.30 + 0.1 * rng.uniform(-1, 1))
        vel_y = 1.5  # Northward drift
        vel_x = 4.0  # Eastward drift

        channels: dict[str, list[np.ndarray]] = {k: [] for k in NORM_BOUNDS}

        for t in range(temporal_depth):
            cy = start_y + t * vel_y
            cx = start_x + t * vel_x

            # Radial distance from storm core
            dist = np.sqrt((grid_y - cy) ** 2 + (grid_x - cx) ** 2)
            r_core = 16.0 + t * 3.0  # Expanding storm footprint
            core_mask = np.exp(-0.5 * (dist / max(1.0, r_core)) ** 2)

            # 0. TIR1: Clear sky 295 K cooling to 215 K in core
            t_core = 215.0 - t * 4.0
            tir1_field = 295.0 - (295.0 - t_core) * core_mask
            channels["tir1"].append(tir1_field)

            # 1. WV: Ambient 250 K cooling to 220 K in deep cloud top
            wv_field = 250.0 - (250.0 - 220.0) * core_mask
            channels["wv"].append(wv_field)

            # 2. Split_Diff: Ambient +3.0 K dropping to +0.5 K in glaciated anvil
            split_field = 3.5 - 3.0 * core_mask
            channels["split_diff"].append(split_field)

            # 3. Radar_MaxZ: Intensifying from 20 dBZ to 58 dBZ
            peak_dbz = 20.0 + t * 12.0
            radar_field = peak_dbz * np.exp(-0.5 * (dist / 12.0) ** 2)
            channels["radar_maxz"].append(radar_field)

            # 4. IMERG Rain: Intensifying from 5 mm/h to 45 mm/h
            peak_rain = 5.0 + t * 10.0
            imerg_field = peak_rain * np.exp(-0.5 * (dist / 14.0) ** 2)
            channels["imerg_rain"].append(imerg_field)

            # 5. Flash Density: Surging in later frames
            peak_fl = (t ** 1.8) * 2.5
            flash_field = peak_fl * np.exp(-0.5 * (dist / 10.0) ** 2)
            channels["flash_density"].append(flash_field)

            # 6. CAPE: Ambient high instability field (2800 J/kg)
            cape_field = np.full((height, width), 2800.0, dtype=np.float32) + 200.0 * np.sin(grid_y / 30.0)
            channels["cape"].append(cape_field)

            # 7. Bulk Shear: Favorable 0-6 km shear (24 m/s)
            shear_field = np.full((height, width), 24.0, dtype=np.float32) + 4.0 * np.cos(grid_x / 40.0)
            channels["bulk_shear"].append(shear_field)

        sample = build_spatiotemporal_tensor(
            channels_dict=channels,
            target_shape=(height, width),
            temporal_depth=temporal_depth,
            missing_modalities=missing_modalities,
        )
        batch[b] = sample

    return batch
