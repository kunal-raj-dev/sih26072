"""Risk interpretation: raw calibrated probability -> documented risk band.

Deliberately boring and configurable (MASTER.md §9 / brief Part 8): the bands come
from config, every factor is stored on the alert so the UI can explain WHY, and no
band is claimed to be a validated IMD operational threshold.
"""

from __future__ import annotations

from .config import RiskConfig
from .schemas import Cell


def band_for_probability(p: float, cfg: RiskConfig) -> str:
    for b in cfg.bands:
        if p <= b.max:
            return b.name
    return cfg.bands[-1].name


def risk_factors(cell: Cell, p_flash: float, confidence: float) -> dict[str, float]:
    """Stored per-alert so the UI can show the 'why' — no hidden scoring."""
    return {
        "p_flash": round(float(p_flash), 4),
        "cell_max_intensity": round(float(cell.max_intensity), 2),
        "cell_area_px": int(cell.area_px),
        "flash_count_history": int(cell.flash_count_history),
        "motion_speed_km_h": round(motion_speed(cell), 1),
        "confidence": round(float(confidence), 3),
    }


def motion_speed(cell: Cell) -> float:
    import numpy as np
    from .features import motion_speed_km_h
    return motion_speed_km_h(cell) if cell.motion_dlat or cell.motion_dlon else float(
        np.hypot(cell.motion_dlat * 111.32, cell.motion_dlon * 111.32))


def recommended_action(severity: str, preset: str) -> str:
    """NDMA / IMD lightning safety directives for disaster management decision support."""
    actions = {
        ("WARNING", "protective"): (
            "Take immediate shelter in a sturdy pucca building. Do NOT stay in open fields, "
            "under tall trees, near metal fences, or tin-shed structures. Suspend outdoor school "
            "activities and farm labor immediately."
        ),
        ("WARNING", "operational"): (
            "Activate District Emergency Operations Center (DEOC). Dispatch high-priority CAP/SMS "
            "broadcast to targeted administrative blocks. Alert quick response teams."
        ),
        ("WATCH", "protective"): (
            "Be prepared to take immediate shelter. Move children, livestock, and outdoor workers "
            "towards safe indoor locations. Avoid water bodies and open spaces."
        ),
        ("WATCH", "operational"): (
            "Alert block disaster management officers and field emergency teams. Verify communication "
            "networks and monitor nowcast updates every 10-15 minutes."
        ),
        ("ADVISORY", "protective"): (
            "Atmospheric instability developing. Monitor nowcast updates every 15-30 minutes. "
            "Identify nearest safe shelter locations."
        ),
        ("ADVISORY", "operational"): (
            "Issue district meteorological advisory. Maintain standard readiness and monitor "
            "subsequent nowcast cycles."
        ),
    }
    return actions.get((severity, preset), "Monitor next update.")
