"""Risk interpretation: raw calibrated probability -> documented risk band.

Deliberately boring and configurable (MASTER.md §9 / brief Part 8): the bands come
from config, every factor is stored on the alert so the UI can explain WHY, and no
band is claimed to be a validated IMD operational threshold.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import numpy as np

from .config import RiskConfig
from .schemas import Cell


class IMDColorCode(str, Enum):
    """Official India Meteorological Department (IMD) 4-stage warning color codes."""

    GREEN = "GREEN"      # No Warning (Be updated)
    YELLOW = "YELLOW"    # Watch (Be updated)
    ORANGE = "ORANGE"    # Alert (Be prepared)
    RED = "RED"          # Warning (Take action)


def compute_hazard_severity(
    cell: Cell | None = None,
    flash_rate: float = 0.0,
    rain_rate_mmh: float = 0.0,
    max_intensity_dbz: float | None = None,
) -> float:
    """Calculate normalized hazard severity S in [0.0, 1.0].

    Combines peak rain rate (mm/h), lightning flash rate (flashes/min), and core reflectivity (dBZ).
    Normalizations:
    - Flash rate: 0 to 50 flashes/min -> [0, 1]
    - Rain rate: 0 to 60 mm/h -> [0, 1]
    - Radar core reflectivity: 30 to 65 dBZ -> [0, 1]
    """
    dbz = max_intensity_dbz
    if dbz is None and cell is not None:
        dbz = float(cell.max_intensity)

    f_rate = flash_rate
    if f_rate <= 0.0 and cell is not None and cell.flash_count_history > 0:
        f_rate = min(50.0, float(cell.flash_count_history) / 2.0)

    r_rate = rain_rate_mmh

    weights: list[float] = []
    values: list[float] = []

    if f_rate > 0.0:
        values.append(min(1.0, max(0.0, f_rate / 50.0)))
        weights.append(0.40)
    if r_rate > 0.0:
        values.append(min(1.0, max(0.0, r_rate / 60.0)))
        weights.append(0.35)
    if dbz is not None and dbz > 30.0:
        values.append(min(1.0, max(0.0, (dbz - 30.0) / 35.0)))
        weights.append(0.25)

    if not weights:
        if dbz is not None:
            return float(np.clip((dbz - 20.0) / 45.0, 0.0, 1.0))
        return 0.0

    total_w = sum(weights)
    severity = sum(v * w for v, w in zip(values, weights)) / total_w
    return float(np.clip(severity, 0.0, 1.0))


def compute_exposed_population_factor(
    exposed_population: int,
    ref_population: int = 500_000,
) -> float:
    """Logarithmic scaling factor for exposed population in [0.0, 1.0].

    Uses log10(pop + 1) / log10(ref_pop + 1) to compress extreme variations
    between rural hamlets and dense urban agglomerations.
    """
    if exposed_population <= 0:
        return 0.0
    denom = math.log10(ref_population + 1.0)
    numer = math.log10(exposed_population + 1.0)
    return float(np.clip(numer / denom, 0.0, 1.0))


def compute_vulnerability_weight(
    t: datetime | None = None,
    peak_multiplier: float = 1.5,
    base_multiplier: float = 1.0,
) -> float:
    """Calculate temporal vulnerability multiplier based on agricultural labor cycles in IST.

    Rural farm labor and open-field vulnerability peaks between 11:00 AM and 5:00 PM IST (UTC+05:30).
    Returns peak_multiplier (1.5) during 11:00 - 17:00 IST, base_multiplier (1.0) otherwise.
    """
    if t is None:
        return base_multiplier

    ist = timezone(timedelta(hours=5, minutes=30))
    if t.tzinfo is None:
        t_utc = t.replace(tzinfo=timezone.utc)
        t_ist = t_utc.astimezone(ist)
    else:
        t_ist = t.astimezone(ist)

    hour_float = t_ist.hour + t_ist.minute / 60.0
    if 11.0 <= hour_float <= 17.0:
        return peak_multiplier
    return base_multiplier


def compute_impact_risk(
    p_hazard: float,
    hazard_severity: float,
    exposed_population: int,
    t: datetime | None = None,
    ref_population: int = 500_000,
) -> float:
    """Compute quantitative impact risk:

    ImpactRisk = HazardProbability * HazardSeverity * ExposedPopulationFactor * VulnerabilityWeight
    """
    p = float(np.clip(p_hazard, 0.0, 1.0))
    s = float(np.clip(hazard_severity, 0.0, 1.0))
    e = compute_exposed_population_factor(exposed_population, ref_population=ref_population)
    v = compute_vulnerability_weight(t)

    impact = p * s * e * v
    return float(round(impact, 4))


def compute_imd_warning_level(
    p_hazard: float,
    impact_risk: float = 0.0,
    is_lightning_jump: bool = False,
    exposed_population: int = 0,
    high_pop_threshold: int = 100_000,
) -> IMDColorCode:
    """Align project hazard and impact scores with official IMD 4-Stage Warning Color Codes.

    IMD Criteria:
    - RED (Warning / Take Action):
        * P >= 0.75 with high population exposure (>= 100,000) or high impact (>= 0.50)
        * OR P >= 0.70 with 2-sigma lightning jump detected
    - ORANGE (Alert / Be Prepared):
        * 0.50 <= P < 0.75
        * OR 2-sigma lightning jump detected (escalates to at least Orange)
        * OR impact_risk >= 0.35 with P >= 0.40
    - YELLOW (Watch / Be Updated):
        * 0.20 <= P < 0.50
        * OR impact_risk >= 0.15
    - GREEN (No Warning):
        * P < 0.20 or impact_risk < 0.15 (when P < 0.20)
    """
    p = float(p_hazard)

    # 1. RED check: High probability with high population exposure / extreme impact, or jump with high P
    if p >= 0.75 and (exposed_population >= high_pop_threshold or impact_risk >= 0.50):
        return IMDColorCode.RED
    if is_lightning_jump and p >= 0.70:
        return IMDColorCode.RED

    # 2. ORANGE check: 0.50 <= P < 0.75 or 2-sigma jump or elevated impact
    if p >= 0.50:
        return IMDColorCode.ORANGE
    if is_lightning_jump:
        return IMDColorCode.ORANGE
    if impact_risk >= 0.35 and p >= 0.40:
        return IMDColorCode.ORANGE

    # 3. YELLOW check: 0.20 <= P < 0.50 or impact >= 0.15
    if p >= 0.20 or impact_risk >= 0.15:
        return IMDColorCode.YELLOW

    # 4. GREEN (No Warning): P < 0.20 and impact < 0.15
    return IMDColorCode.GREEN



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
