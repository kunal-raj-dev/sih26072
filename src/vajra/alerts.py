"""Alert engine: configurable, explainable, de-duplicated.

Alerts are raised per storm cell from the calibrated forecast at a chosen lead,
using a documented preset (protective vs operational). Every alert carries its
reason, contributing signals, model version, data quality and mode. Suppression
prevents re-raising the same region+severity inside a configurable window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import Settings
from .geocoding import SpatialIndex
from .risk import band_for_probability, motion_speed, recommended_action, risk_factors
from .schemas import Alert, Cell, DataMode, Forecast, QualityStatus


def _severity_for(p: float, preset_cfg) -> str:
    if p >= preset_cfg.p_threshold + 0.25:
        return "WARNING"
    if p >= preset_cfg.p_threshold:
        return "WATCH"
    if p >= max(0.10, preset_cfg.p_threshold - 0.15):
        return "ADVISORY"
    return ""


class AlertEngine:
    def __init__(self, settings: Settings, spatial_index: SpatialIndex | None = None):
        self.cfg = settings.alerts
        self.risk_cfg = settings.risk
        self.spatial_index = spatial_index if spatial_index is not None else SpatialIndex()
        self._recent: list[tuple[str, str, str, datetime]] = []  # (cell_id, severity, preset, issued_at)

    def reset(self) -> None:
        self._recent = []

    def generate(self, forecast: Forecast, cells: list[Cell], lead_minutes: int | None = None,
                 p_cell: dict[str, float] | None = None) -> list[Alert]:
        """Generate alerts for one forecast (uses the step matching lead_minutes,
        or the longest lead available)."""
        if not forecast.steps:
            return []
        step = (max(forecast.steps, key=lambda s: s.lead_minutes) if lead_minutes is None
                else next((s for s in forecast.steps if s.lead_minutes == lead_minutes),
                          forecast.steps[-1]))
        probs = p_cell or {}
        alerts: list[Alert] = []
        for preset_name, preset_cfg in self.cfg.presets.items():
            for cell in cells:
                p = probs.get(cell.id)
                if p is None:
                    continue
                sev = _severity_for(p, preset_cfg)
                if not sev:
                    continue
                conf = forecast.confidence
                if conf < preset_cfg.min_confidence:
                    continue
                if self._suppressed(cell.id, sev, preset_name, forecast.replay_time):
                    continue
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
                    reason=(f"Calibrated P(flash<={step.lead_minutes} min) = {p:.2f} "
                            f"[{band}] for cell {cell.id}; "
                            f"cell intensity {cell.max_intensity} (raw), "
                            f"flash history {cell.flash_count_history}, "
                            f"motion {motion_speed(cell):.0f} km/h."),
                    contributing_signals=factors,
                    model_version=forecast.model_version,
                    mode=forecast.mode,
                    data_quality=forecast.data_quality,
                    recommended_action=recommended_action(sev, preset_name),
                    affected_districts=affected_districts,
                    affected_blocks=affected_blocks,
                    population_exposed=pop_exposed,
                )
                alerts.append(alert)
                self._recent.append((cell.id, sev, preset_name, forecast.replay_time))
        return alerts

    def _suppressed(self, cell_id: str, severity: str, preset: str, now: datetime) -> bool:
        for (cid, sev, pre, issued) in reversed(self._recent):
            if cid == cell_id and sev == severity and pre == preset:
                if (now - issued).total_seconds() < self.cfg.suppression_minutes * 60:
                    return True
                break
        return False


def data_quality_map(forecast: Forecast) -> dict[str, str]:
    return forecast.data_quality


def worst_quality(forecast: Forecast) -> str:
    order = ["OK", "SUSPECT", "BAD", "MISSING"]
    vals = [v for v in forecast.data_quality.values() if v in order]
    return max(vals, key=order.index) if vals else QualityStatus.MISSING.value
