"""Deterministic PNG rendering of forecast/observation fields for the map overlay.

Probability fields are rendered with the exact risk-band palette shown in the UI
legend — the map never displays a color that the legend cannot explain. Rendering
is pure Pillow; no tile server, no GIS service dependency.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

# (r, g, b, a) per risk band — must match web/legend exactly.
BAND_COLORS: dict[str, tuple[int, int, int, int]] = {
    "LOW": (59, 130, 246, 0),        # transparent below first threshold
    "MODERATE": (250, 204, 21, 110),
    "ELEVATED": (249, 115, 22, 140),
    "HIGH": (239, 68, 68, 170),
    "SEVERE": (168, 0, 230, 200),
}

BAND_THRESHOLDS = [0.20, 0.40, 0.60, 0.80]  # LOW < 0.20 <= MODERATE < 0.40 <= ...


def render_probability_png(p_grid: np.ndarray, alpha_scale: bool = True) -> bytes:
    """Map a 0..1 probability grid onto the risk-band palette (top-left origin)."""
    p = np.clip(np.nan_to_num(p_grid, nan=0.0), 0.0, 1.0)
    h, w = p.shape
    img = np.zeros((h, w, 4), dtype=np.uint8)
    # Build a band index image.
    band_idx = np.digitize(p, BAND_THRESHOLDS, right=False)  # 0=LOW,1=MODERATE,...
    names = ["LOW", "MODERATE", "ELEVATED", "HIGH", "SEVERE"]
    for k, name in enumerate(names):
        sel = band_idx == k
        if not sel.any():
            continue
        color = BAND_COLORS[name]
        img[sel] = color
    if alpha_scale:
        # Scale alpha slightly with probability within the band for readability.
        a = img[:, :, 3].astype(float)
        lower = np.r_[0.0, BAND_THRESHOLDS]                      # 5 lower bounds
        widths = np.diff(np.r_[0.0, BAND_THRESHOLDS, 1.0001])    # 5 band widths
        base = np.clip((p - lower[band_idx]) / widths[band_idx], 0.0, 1.0)
        img[:, :, 3] = (a * np.clip(0.6 + 0.4 * base, 0, 1)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def render_field_png(field: np.ndarray, vmin: float, vmax: float) -> bytes:
    """Grayscale rendering of an observation field (e.g. VIL / IR)."""
    f = np.nan_to_num(field.astype(float), nan=vmin)
    norm = np.clip((f - vmin) / max(1e-6, vmax - vmin), 0.0, 1.0)
    gray = (norm * 255).astype(np.uint8)
    rgba = np.stack([gray, gray, gray, np.full_like(gray, 165)], axis=-1)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


# Standard meteorological radar reflectivity color scale (WSR-88D / IMD NWS color ramp)
REFLECTIVITY_COLORS: list[tuple[float, tuple[int, int, int, int]]] = [
    (5.0,  (100, 181, 246, 120)),  # Light blue - drizzle / light echo
    (15.0, (30, 136, 229, 140)),   # Blue - light rain
    (25.0, (67, 160, 71, 160)),    # Green - moderate rain
    (35.0, (124, 179, 66, 180)),   # Yellow-green - heavy stratiform
    (40.0, (253, 216, 53, 200)),   # Yellow - heavy rain / convective onset
    (45.0, (251, 140, 0, 215)),    # Amber/Orange - intense convective core
    (50.0, (229, 57, 53, 230)),    # Red - severe storm core
    (55.0, (183, 28, 28, 240)),    # Dark Red - severe storm with hail risk
    (60.0, (216, 27, 96, 250)),    # Magenta - destructive hail probable
    (65.0, (142, 36, 170, 255)),   # Purple/Violet - extreme convective cell
]


def render_reflectivity_png(dbz_grid: np.ndarray) -> bytes:
    """Render a 2D radar reflectivity grid (dBZ) with standard meteorological colors."""
    dbz = np.nan_to_num(dbz_grid.astype(float), nan=0.0)
    h, w = dbz.shape
    img = np.zeros((h, w, 4), dtype=np.uint8)

    for thresh, (r, g, b, a) in REFLECTIVITY_COLORS:
        sel = dbz >= thresh
        img[sel] = (r, g, b, a)

    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def render_uncertainty_png(sigma_grid: np.ndarray) -> bytes:
    """Render a 2D spatial uncertainty field as an amber/cyan semi-transparent overlay."""
    sig = np.clip(np.nan_to_num(sigma_grid.astype(float), nan=0.0), 0.0, 1.0)
    h, w = sig.shape
    img = np.zeros((h, w, 4), dtype=np.uint8)

    # Low uncertainty (< 0.25): transparent to subtle teal
    # Medium uncertainty (0.25 - 0.60): cyan / blue
    # High uncertainty (> 0.60): warm amber / magenta
    r = (np.clip((sig - 0.20) / 0.80, 0, 1) * 220).astype(np.uint8)
    g = (np.clip((1.0 - np.abs(sig - 0.50) * 2.0), 0, 1) * 180).astype(np.uint8)
    b = (np.clip((0.80 - sig) / 0.80, 0, 1) * 240).astype(np.uint8)
    a = (np.clip((sig - 0.10) / 0.90, 0, 1) * 160).astype(np.uint8)

    img[:, :, 0] = r
    img[:, :, 1] = g
    img[:, :, 2] = b
    img[:, :, 3] = a

    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG")
    return buf.getvalue()
