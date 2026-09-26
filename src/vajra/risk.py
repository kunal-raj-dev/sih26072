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
    """Static documented mapping — decision support, not an order."""
    actions = {
        ("WARNING", "protective"): "Move people out of open fields; shelter livestock; postpone outdoor work.",
        ("WARNING", "operational"): "Consider issuing district siren/SMS; notify field teams.",
        ("WATCH", "protective"): "Prepare to move; monitor updates every 30 min.",
        ("WATCH", "operational"): "Alert response teams; verify communication channels.",
        ("ADVISORY", "protective"): "Conditions developing; stay alert to updates.",
        ("ADVISORY", "operational"): "No action required yet; monitor next cycle.",
    }
    return actions.get((severity, preset), "Monitor next update.")
