"""Data quality control. Never silently accept invalid atmospheric data.

QC runs on every ObsFrame before it enters the pipeline. Findings are recorded
in the frame's QualityInfo — the pipeline decides per-policy what to do (skip,
downgrade, or fail loudly), but the QC verdict is always attached.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .schemas import Modality, ObsFrame, QualityStatus

# Plausible physical ranges per (source, variable) or fallback by variable.
# Anything outside is flagged BAD or SUSPECT.
RANGE_RULES: dict[tuple[str, str] | str, tuple[float, float]] = {
    # Source-specific rules
    ("sevir", "vil"): (0.0, 255.0),                 # SEVIR raw scale uint8
    ("sevir", "bt_ir107"): (150.0, 350.0),           # Kelvin physical brightness temperature
    ("sevir_raw_ir", "bt_ir107"): (0.0, 255.0),      # Raw uint8 scale before calibration
    ("sevir_glm", "flash"): (0.0, 1e9),
    ("synthetic", "vil_proxy"): (0.0, 255.0),
    ("synthetic", "bt_ir_proxy"): (150.0, 330.0),
    ("synthetic", "refl_proxy"): (-40.0, 95.0),
    ("imerg", "precipitation"): (0.0, 500.0),        # IMERG mm/hr
    ("imerg_earthdata", "precipitation"): (0.0, 500.0),
    ("mosdac", "bt_ir107"): (150.0, 350.0),
    ("mosdac", "bt_wv"): (150.0, 350.0),
    ("mosdac", "ctt"): (150.0, 350.0),
    ("mosdac_insat", "bt_ir107"): (150.0, 350.0),
    ("mosdac_insat", "bt_wv"): (150.0, 350.0),
    ("mosdac_insat", "ctt"): (150.0, 350.0),
    ("iss_lis", "flash"): (0.0, 1e9),
    ("lis_earthdata", "flash"): (0.0, 1e9),
    ("gfs_nomads", "cape_jkg"): (0.0, 7500.0),
    ("gfs_nomads", "cin_jkg"): (0.0, 2000.0),
    ("gfs_nomads", "shear_0_6km_ms"): (0.0, 120.0),
    ("gfs_nomads", "rh_700hpa_pct"): (0.0, 100.0),
    # Variable fallbacks (used when (source, variable) is not explicitly listed)
    "vil": (0.0, 255.0),            # SEVIR raw scale
    "vil_proxy": (0.0, 255.0),      # synthetic VIL-scale proxy
    "refl_proxy": (-40.0, 95.0),    # dBZ
    "bt_ir107": (150.0, 350.0),     # Kelvin (physical range)
    "bt_ir_proxy": (150.0, 330.0),
    "flash": (0.0, 1e9),
    "precipitation": (0.0, 500.0),  # IMERG mm/hr
    "cape_jkg": (0.0, 7500.0),
    "cin_jkg": (0.0, 2000.0),
    "shear_0_6km_ms": (0.0, 120.0),
    "rh_700hpa_pct": (0.0, 100.0),
}

STALE_MAX_AGE_MIN = 90.0


def get_range_rule(source: str, variable: str) -> tuple[float, float]:
    """Lookup valid physical range for a given (source, variable) pair with variable fallback."""
    if (source, variable) in RANGE_RULES:
        return RANGE_RULES[(source, variable)]
    return RANGE_RULES.get(variable, (-np.inf, np.inf))


def sevir_ir_to_kelvin(raw: np.ndarray | float) -> np.ndarray | float:
    """Convert raw SEVIR IR data to physical Kelvin brightness temperature.

    SEVIR HDF5 stores IR107 as int16 scaled by 0.01 deg C:
        T_K = raw * 0.01 + 273.15
    If uint8 raw scale (0-255) is provided:
        T_K = 150.0 + raw * (200.0 / 255.0)
    """
    arr = np.asarray(raw, dtype=np.float32)
    # Check if data resembles int16 hundredths of deg C (negative values or max > 255)
    if np.nanmin(arr) < 0.0 or np.nanmax(arr) > 255.0:
        res = arr * 0.01 + 273.15
    else:
        res = 150.0 + arr * (200.0 / 255.0)
    if np.isscalar(raw):
        return float(res)
    return res



def validate_frame(frame: ObsFrame, now: datetime | None = None) -> ObsFrame:
    """Validate one frame; returns the frame with an updated QualityInfo."""
    q = frame.meta.quality.model_copy()
    problems: list[str] = []

    # Timestamp sanity: future-dated or very old observations.
    t = frame.meta.time
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
        problems.append("naive timestamp (assumed UTC)")
    now = now or datetime.now(timezone.utc)
    # Replay/simulation frames may legitimately be historical: staleness only
    # applies to LIVE-mode frames.
    if frame.meta.mode.value == "LIVE":
        age_min = (now - t).total_seconds() / 60.0
        if age_min < -5:
            problems.append(f"timestamp in the future by {-age_min:.0f} min")
        elif age_min > STALE_MAX_AGE_MIN:
            q.stale = True
            problems.append(f"stale: {age_min:.0f} min old")

    if frame.meta.grid.geolocation == "approximate" and "geo" not in q.message:
        q.message = (q.message + " | " if q.message else "") + "grid geolocation approximate"

    if frame.field is not None:
        f = frame.field
        miss = float(np.mean(~np.isfinite(f)))
        if miss > 0:
            q.missing_fraction = miss
            problems.append(f"{miss * 100:.1f}% non-finite values")
        if miss > 0.5:
            q.status = QualityStatus.MISSING
        lo, hi = get_range_rule(frame.meta.source, frame.meta.variable)
        finite = f[np.isfinite(f)]
        if finite.size and (finite.min() < lo or finite.max() > hi):
            problems.append(f"values outside [{lo}, {hi}] for {frame.meta.variable} (source={frame.meta.source})")
        if finite.size and float(finite.max()) == float(finite.min()):
            problems.append("constant field (no variance)")

    if frame.points is not None:
        p = frame.points
        if p.ndim != 2 or p.shape[1] < 2:
            problems.append("malformed point array")
        else:
            bad_geo = (p[:, 0] < -90) | (p[:, 0] > 90) | (p[:, 1] < -180) | (p[:, 1] > 180)
            if bad_geo.any():
                problems.append(f"{int(bad_geo.sum())} flashes with invalid coordinates")
                p = p[~bad_geo]
                frame.points = p

    if problems:
        q.message = (q.message + " | " if q.message else "") + "; ".join(problems)
        if q.status == QualityStatus.OK:
            q.status = QualityStatus.SUSPECT if q.missing_fraction <= 0.5 else QualityStatus.BAD
    frame.meta.quality = q
    return frame


def modality_health(frames: list[ObsFrame]) -> str:
    """Aggregate QC verdict for a modality's history window.

    BAD only when a frame is unusable-and-present; MISSING when no data arrived;
    SUSPECT when anything is degraded (including partially-missing history)."""
    if not frames:
        return QualityStatus.MISSING.value
    statuses = [f.meta.quality.status for f in frames]
    if QualityStatus.BAD in statuses:
        return QualityStatus.BAD.value
    if all(s == QualityStatus.MISSING for s in statuses):
        return QualityStatus.MISSING.value
    if any(s in (QualityStatus.SUSPECT, QualityStatus.MISSING) for s in statuses) \
            or any(f.meta.quality.stale for f in frames):
        return QualityStatus.SUSPECT.value
    return QualityStatus.OK.value
