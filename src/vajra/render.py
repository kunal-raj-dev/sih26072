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
