"""Alert engine: IMD 4-Stage Warnings, OASIS CAP 1.2, configurable presets, and de-duplicated.

Features (Phase 8):
1. IMD 4-Stage Warning Color Codes:
   - Green (No Warning): P < 0.15
   - Yellow (Watch / Be Updated): 0.15 <= P < 0.40
   - Orange (Alert / Be Prepared): 0.40 <= P < 0.70
   - Red (Warning / Take Action): P >= 0.70 or severe 2-sigma lightning jump detected.
2. Dual Operating Presets:
   - Protective: Optimized for high POD (schools, outdoor laborers, disaster relief).
   - Operational: Balanced POD/FAR to prevent alert fatigue among district authorities.
3. Spatiotemporal Deduplication & Escalation Bypass:
   - Suppresses duplicate alert tier for the same entity within 45 minutes.
   - Automatically bypasses suppression when storm conditions escalate (e.g. Yellow -> Orange/Red).
   - Links escalating alerts as official CAP 1.2 Update messages with supersedes references.
4. OASIS CAP 1.2 XML & JSON Serialization:
   - Complete export compliant with NDMA SACHET and WMO alert formats.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .config import Settings
from .geocoding import SpatialIndex
from .risk import band_for_probability, motion_speed, recommended_action, risk_factors
from .schemas import Alert, Cell, DataMode, Forecast, QualityStatus

logger = logging.getLogger(__name__)

SEVERITY_RANK: dict[str, int] = {
    "ADVISORY": 1,
    "WATCH": 2,
    "WARNING": 3,
}

IMD_STAGE_RANK: dict[str, int] = {
    "GREEN": 0,
    "YELLOW": 1,
    "ORANGE": 2,
    "RED": 3,
}


def classify_alert_stage(
    p: float,
    preset_name: str,
    preset_cfg: Any,
    has_jump: bool = False,
) -> tuple[str, str, str] | None:
    """Classify risk into (imd_stage, severity, cap_severity).

    Returns:
        (imd_stage, severity, cap_severity) or None if below alert threshold.
    """
    if has_jump:
        # Severe 2-sigma lightning jump rate acceleration automatically escalates to RED Warning!
        return ("RED", "WARNING", "Extreme")

    p_thresh = getattr(preset_cfg, "p_threshold", 0.40)

    if preset_name == "protective":
        # Protective preset: high POD for public safety, schools, agriculture
        if p >= max(0.60, p_thresh + 0.20):
            return ("RED", "WARNING", "Extreme")
        if p >= p_thresh:
            return ("ORANGE", "WATCH", "Severe")
        if p >= max(0.15, p_thresh - 0.15):
            return ("YELLOW", "ADVISORY", "Moderate")
    else:
        # Operational preset: balanced POD/FAR for district administration
        if p >= max(0.70, p_thresh + 0.20):
            return ("RED", "WARNING", "Extreme")
        if p >= p_thresh:
            return ("ORANGE", "WATCH", "Severe")
        if p >= max(0.20, p_thresh - 0.30):
            return ("YELLOW", "ADVISORY", "Moderate")

    return None


class AlertEngine:
    def __init__(self, settings: Settings, spatial_index: SpatialIndex | None = None):
        self.cfg = settings.alerts
        self.risk_cfg = settings.risk
        self.spatial_index = spatial_index if spatial_index is not None else SpatialIndex()
        # History: (cell_id, region_name, severity, imd_stage, preset, issued_at, alert_id)
        self._recent: list[tuple[str, str, str, str, str, datetime, str]] = []

    def reset(self) -> None:
        self._recent = []

    def generate(
        self,
        forecast: Forecast,
        cells: list[Cell],
        lead_minutes: int | None = None,
        p_cell: dict[str, float] | None = None,
        jump_cells: set[str] | None = None,
    ) -> list[Alert]:
        """Generate alerts for one forecast cycle with IMD color codes and CAP 1.2 attributes."""
        if not forecast.steps:
            return []

        step = (
            max(forecast.steps, key=lambda s: s.lead_minutes)
            if lead_minutes is None
            else next((s for s in forecast.steps if s.lead_minutes == lead_minutes), forecast.steps[-1])
        )

        probs = p_cell or {}
        jumps = jump_cells or set()
        alerts: list[Alert] = []

        for preset_name, preset_cfg in self.cfg.presets.items():
            for cell in cells:
                p = probs.get(cell.id)
                if p is None:
                    continue

                has_jump = cell.id in jumps
                classification = classify_alert_stage(
                    p=p,
                    preset_name=preset_name,
                    preset_cfg=preset_cfg,
                    has_jump=has_jump,
                )
                if classification is None:
                    continue

                imd_stage, sev, cap_sev = classification

                conf = forecast.confidence
                if conf < preset_cfg.min_confidence:
                    continue

                # Geocoding and administrative impact resolution
                factors = risk_factors(cell, p, conf)
                band = band_for_probability(p, self.risk_cfg)

                fallback_region = f"Cell {cell.id} ({band})"
                region_name = fallback_region
                affected_districts: list[str] = []
                affected_blocks: list[str] = []
                pop_exposed: int = 0

                if self.spatial_index and self.spatial_index.is_ready():
                    intersections = self.spatial_index.intersect_cell(cell)
                    if intersections:
                        region_name = self.spatial_index.format_region_name(
                            intersections, fallback=fallback_region
                        )
                        affected_districts = list(
                            dict.fromkeys(ix.entity.district for ix in intersections)
                        )
                        affected_blocks = list(
                            dict.fromkeys(ix.entity.name for ix in intersections)
                        )
                        pop_exposed = sum(ix.exposed_population for ix in intersections)
                    else:
                        matches = self.spatial_index.query_point(
                            cell.centroid_lat, cell.centroid_lon
                        )
                        if matches:
                            region_name = self.spatial_index.format_region_name(
                                matches, fallback=fallback_region
                            )
                            affected_districts = list(
                                dict.fromkeys(m.district for m in matches)
                            )
                            affected_blocks = list(dict.fromkeys(m.name for m in matches))
                            pop_exposed = sum(m.population for m in matches)

                # Spatiotemporal deduplication & escalation check
                should_suppress, is_update, prior_id = self._check_suppression_and_escalation(
                    cell_id=cell.id,
                    region_key=region_name,
                    severity=sev,
                    preset=preset_name,
                    now=forecast.replay_time,
                )
                if should_suppress:
                    continue

                # Urgency & Certainty per CAP 1.2 standards
                urgency = "Immediate" if (step.lead_minutes <= 15 or imd_stage == "RED" or has_jump) else "Expected"
                certainty = (
                    "Observed"
                    if (cell.flash_count_history >= 1 or cell.max_intensity >= 45.0)
                    else ("Likely" if p >= 0.50 else "Possible")
                )

                jump_note = " [SEVERE LIGHTNING JUMP RATE SURGE]" if has_jump else ""
                headline = (
                    f"[IMD {imd_stage} {sev}] Lightning Hazard Expected in {region_name} "
                    f"within {step.lead_minutes} min (P={p:.0%}){jump_note}"
                )

                speed_kmh = motion_speed(cell)
                reason_text = (
                    f"Calibrated P(flash<={step.lead_minutes} min) = {p:.2f} "
                    f"[{band} / IMD {imd_stage}] for cell {cell.id}; "
                    f"cell intensity {cell.max_intensity} (raw), "
                    f"flash history {cell.flash_count_history}, "
                    f"motion {speed_kmh:.0f} km/h.{jump_note}"
                )

                alert = Alert(
                    run_id=forecast.run_id or forecast.id,
                    event_id=forecast.event_id,
                    valid_from=forecast.replay_time,
                    valid_until=forecast.replay_time + timedelta(minutes=self.cfg.validity_minutes),
                    severity=sev,  # type: ignore[arg-type]
                    hazard="LIGHTNING",
                    region_name=region_name,
                    bbox=cell.bbox,
                    probability=round(p, 3),
                    confidence=round(conf, 3),
                    lead_minutes=step.lead_minutes,
                    preset=preset_name,
                    reason=reason_text,
                    contributing_signals=factors,
                    model_version=forecast.model_version,
                    mode=forecast.mode,
                    data_quality=forecast.data_quality,
                    recommended_action=recommended_action(sev, preset_name),
                    affected_districts=affected_districts,
                    affected_blocks=affected_blocks,
                    population_exposed=pop_exposed,
                    imd_stage=imd_stage,  # type: ignore[arg-type]
                    cap_severity=cap_sev,  # type: ignore[arg-type]
                    urgency=urgency,  # type: ignore[arg-type]
                    certainty=certainty,  # type: ignore[arg-type]
                    headline=headline,
                    is_update=is_update,
                    supersedes_id=prior_id,
                )
                alerts.append(alert)
                self._recent.append(
                    (cell.id, region_name, sev, imd_stage, preset_name, forecast.replay_time, alert.id)
                )

        return alerts

    def _check_suppression_and_escalation(
        self,
        cell_id: str,
        region_key: str,
        severity: str,
        preset: str,
        now: datetime,
    ) -> tuple[bool, bool, str]:
        """Check whether an alert is suppressed, or bypasses suppression due to severity escalation.

        Returns:
            (should_suppress, is_update, prior_alert_id)
        """
        curr_rank = SEVERITY_RANK.get(severity, 0)
        window_seconds = self.cfg.suppression_minutes * 60

        for (cid, rkey, prev_sev, _prev_imd, pre, issued, prev_id) in reversed(self._recent):
            if (cid == cell_id or rkey == region_key) and pre == preset:
                elapsed_sec = (now - issued).total_seconds()
                if elapsed_sec < window_seconds:
                    prev_rank = SEVERITY_RANK.get(prev_sev, 0)
                    if curr_rank > prev_rank:
                        # Severity escalated (e.g. Yellow -> Orange, or Orange -> Red)!
                        # Immediately bypass suppression and issue an Update!
                        return False, True, prev_id
                    else:
                        # Same or lower severity within suppression window: suppress duplicate
                        return True, False, ""
                break

        return False, False, ""


def data_quality_map(forecast: Forecast) -> dict[str, str]:
    return forecast.data_quality


def worst_quality(forecast: Forecast) -> str:
    order = ["OK", "SUSPECT", "BAD", "MISSING"]
    vals = [v for v in forecast.data_quality.values() if v in order]
    return max(vals, key=order.index) if vals else QualityStatus.MISSING.value
