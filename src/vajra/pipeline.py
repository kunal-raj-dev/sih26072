"""Nowcast pipeline: the vertical slice orchestrator.

One cycle (at issue time t):
  gather history per modality -> QC -> modality availability -> cell detection
  (tracker) -> features -> router (baseline or ML with fallback rung) -> per-lead
  probability fields -> risk bands -> forecast (+ artifacts) -> alerts.

A replay run repeats cycles across a historical event. Evaluation is honest by
construction: forecasts are scored ONLY against lightning that actually occurred
after issue time (labels computed when replay time reaches issue+lead), and
training-sample features are frozen at issue time. Modes LIVE/REPLAY/SIMULATION
propagate from the event to every forecast and alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from .alerts import AlertEngine
from .cells import CellTracker, detect_lightning_jump
from .config import Settings
from .features import FEATURE_NAMES, build_features
from .geocoding import SpatialIndex
from .grid import GridSpec
from .logsetup import get_logger, log_event
from .models.base import CycleContext
from .models.router import ModelRouter
from .qc import modality_health, validate_frame
from .render import render_field_png, render_probability_png
from .risk import band_for_probability
from .schemas import (
    Alert,
    DataMode,
    Event,
    Forecast,
    ForecastStep,
    FallbackRung,
    GridMeta,
    InferenceRun,
    Modality,
    ObsFrame,
    QualityStatus,
)

logger = get_logger("vajra.pipeline")


def _meta_of(g: GridSpec) -> GridMeta:
    return GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                    nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)


@dataclass
class _PendingSample:
    """A forecast awaiting its outcome (label) once replay time advances."""

    t_issue: datetime
    lead_minutes: int
    p_cell: dict[str, float]
    cells: list           # Cell objects at issue time (bbox/centroid snapshots)
    features_rows: list[dict] = field(default_factory=list)


class NowcastPipeline:
    def __init__(self, settings: Settings, sources: dict[Modality, object],
                 router: ModelRouter, model_version: str = "unloaded",
                 spatial_index: SpatialIndex | None = None):
        self.settings = settings
        self.sources = sources
        self.router = router
        self.model_version = model_version
        self.spatial_index = spatial_index if spatial_index is not None else SpatialIndex()
        self.alert_engine = AlertEngine(settings, spatial_index=self.spatial_index)
        self.tracker: CellTracker | None = None
        self._active_grid: GridSpec | None = None
        self._store = None
        self._last_fields: dict[int, tuple[np.ndarray, bytes]] = {}
        self._last_issue: tuple = (None, None, None, [])
        self._prev_ci_candidates: list = []

    def attach_store(self, store) -> None:  # type: ignore[no-untyped-def]
        self._store = store

    # -- data gathering -----------------------------------------------------------
    def _history(self, mod: Modality, t: datetime) -> list[ObsFrame]:
        src = self.sources.get(mod)
        if src is None:
            return []
        try:
            frames = src.get_history(t, self.settings.replay.history_minutes)
        except Exception as exc:  # noqa: BLE001 — provider boundary: record, don't crash
            log_event(logger, 30, "provider failed", modality=mod.value, error=str(exc))
            return []
        return [validate_frame(f) for f in frames]

    @staticmethod
    def _satellite_as_radar_proxy(frames: list[ObsFrame]) -> list[ObsFrame]:
        """Cold IR brightness -> 0..255 convective-intensity proxy so detection can
        run without radar. Every proxy frame is explicitly annotated."""
        out = []
        for f in frames:
            if f.field is None:
                continue
            inten = np.clip((300.0 - f.field) / 95.0, 0.0, 1.0)
            proxy = (inten * 255.0).astype(np.float32)
            meta = f.meta.model_copy(update={
                "variable": "ir_intensity_proxy",
                "units": "0-255 (IR proxy)",
                "note": (f.meta.note + " | " if f.meta.note else "")
                        + "IR->intensity proxy for detection; NOT radar",
            })
            out.append(ObsFrame(meta=meta, field=proxy, points=f.points))
        return out

    @staticmethod
    def _precipitation_as_radar_proxy(frames: list[ObsFrame]) -> list[ObsFrame]:
        """Precipitation rate (mm/hr) -> 0..255 convective-intensity proxy so detection
        can proceed when radar/satellite are absent. Every proxy frame is annotated."""
        out = []
        for f in frames:
            if f.field is None:
                continue
            # 50 mm/hr represents very severe convection; map 0..50 mm/hr -> 0..255
            inten = np.clip(f.field / 50.0, 0.0, 1.0)
            proxy = (inten * 255.0).astype(np.float32)
            meta = f.meta.model_copy(update={
                "variable": "precip_intensity_proxy",
                "units": "0-255 (Rain proxy)",
                "note": (f.meta.note + " | " if f.meta.note else "")
                        + "Rain->intensity proxy for detection; NOT radar",
            })
            out.append(ObsFrame(meta=meta, field=proxy, points=f.points))
        return out

    def _available(self, frames: list[ObsFrame], t: datetime) -> bool:
        if not frames:
            return False
        worst = modality_health(frames)
        if worst in (QualityStatus.MISSING.value, QualityStatus.BAD.value):
            return False
        last = max(f.meta.time for f in frames)
        if frames and frames[0].meta.modality == Modality.MODEL:
            limit = timedelta(hours=12)
        else:
            limit = timedelta(minutes=max(3 * self.settings.replay.cycle_minutes, 30))
        return (t - last) <= limit

    # -- one cycle -----------------------------------------------------------------
    def run_cycle(self, t: datetime, event_id: str, mode: DataMode,
                  run_id: str = "") -> tuple[Forecast, list[Alert]]:
        cycle_minutes = self.settings.replay.cycle_minutes
        radar = self._history(Modality.RADAR, t)
        satellite = self._history(Modality.SATELLITE, t)
        lightning = self._history(Modality.LIGHTNING, t)
        surface = self._history(Modality.SURFACE, t)
        model = self._history(Modality.MODEL, t)

        radar_ok = self._available(radar, t)
        sat_ok = self._available(satellite, t)
        light_ok = self._available(lightning, t)
        surface_ok = self._available(surface, t)
        model_ok = self._available(model, t)
        available = {
            Modality.RADAR.value: radar_ok,
            Modality.SATELLITE.value: sat_ok,
            Modality.LIGHTNING.value: light_ok,
            Modality.SURFACE.value: surface_ok,
            Modality.MODEL.value: model_ok,
        }

        if radar_ok:
            det_frames = radar
            det_mod = Modality.RADAR
        elif sat_ok:
            det_frames = self._satellite_as_radar_proxy(satellite)
            det_mod = Modality.SATELLITE
        elif surface_ok:
            det_frames = self._precipitation_as_radar_proxy(surface)
            det_mod = Modality.SURFACE
        else:
            det_frames = []
            det_mod = Modality.RADAR
        det_ok = self._available(det_frames, t) if det_frames else False

        if not det_ok:
            ctx = CycleContext(t=t, grid=self._active_grid, cells=[],
                               modalities_available=available, features=None)
            routed = self.router.predict(ctx, self.settings.replay.lead_minutes[0],
                                         self._active_grid)
            fc = Forecast(run_id=run_id, event_id=event_id, replay_time=t, mode=mode,
                          fallback_rung=FallbackRung.CLIMATOLOGY,
                          model_version=self.model_version,
                          grid=_meta_of(self._active_grid) if self._active_grid else None,
                          modalities_used=[Modality(m) for m, ok in available.items() if ok],
                          data_quality={"radar": modality_health(radar),
                                        "satellite": modality_health(satellite),
                                        "lightning": modality_health(lightning),
                                        "surface": modality_health(surface),
                                        "model": modality_health(model)},
                          confidence=0.05,
                          notes=["no usable detection field; climatology background only"])
            self._last_fields = {}
            return fc, []

        det_field = det_frames[-1].field
        gm = det_frames[-1].meta.grid
        self._obs_png = render_field_png(det_field, 0.0, 255.0)
        grid = GridSpec(name=gm.name, lat0=gm.lat0, lon0=gm.lon0, dlat=gm.dlat, dlon=gm.dlon,
                        nlat=gm.nlat, nlon=gm.nlon, geolocation=gm.geolocation)
        self._active_grid = grid
        if self.tracker is None:
            self.tracker = CellTracker(grid, self.settings.cells, cycle_minutes)
        cells = self.tracker.step(t, det_field)

        radar_for_feats = radar if radar_ok else []
        satellite_for_feats = satellite if sat_ok else []
        lightning_for_feats = lightning if light_ok else []
        surface_for_feats = surface if surface_ok else []
        model_for_feats = model if model_ok else []
        feats = build_features(t, cells, self.tracker, radar_for_feats,
                               satellite_for_feats, lightning_for_feats,
                               self.settings.cells.flash_radius_km, grid,
                               surface_frames=surface_for_feats,
                               model_frames=model_for_feats)
        if len(feats):
            fc30 = feats.set_index("_cell_id")["flash_cnt_30"].to_dict()
            for c in cells:
                c.flash_count_history = int(fc30.get(c.id, 0))

        ctx = CycleContext(t=t, grid=grid, cells=cells,
                           radar_frames=radar_for_feats, satellite_frames=satellite_for_feats,
                           lightning_frames=lightning_for_feats, surface_frames=surface_for_feats,
                           model_frames=model_for_feats,
                           features=feats,
                           modalities_available=available,
                           flash_radius_km=self.settings.cells.flash_radius_km)

        # Convective Initiation (CI) precursor detection from satellite & radar frames
        from .models.ci import extract_ci_candidates_from_cycle, generate_ci_probability_grid
        from .models.field_nowcast import compute_spatial_uncertainty_field, render_uncertainty_png

        ci_candidates = extract_ci_candidates_from_cycle(
            satellite_frames=satellite_for_feats,
            radar_frames=radar_for_feats,
            grid=grid,
            history_candidates=self._prev_ci_candidates,
        )
        self._prev_ci_candidates = ci_candidates

        steps: list[ForecastStep] = []
        fields: dict[int, tuple[np.ndarray, bytes]] = {}
        p_by_lead: dict[int, dict[str, float]] = {}
        rung_by_lead: dict[int, FallbackRung] = {}
        uncertainty_png = None

        for lead in self.settings.replay.lead_minutes:
            routed = self.router.predict(ctx, lead, grid, ci_candidates=ci_candidates)
            p_grid = routed.output.p_grid
            p_max = float(np.max(p_grid)) if p_grid is not None and p_grid.size else 0.0
            band = band_for_probability(p_max, self.settings.risk)

            # 2D Convective Initiation probability plume field
            p_ci_grid = generate_ci_probability_grid(ci_candidates, grid, lead_minutes=lead)

            # Spatial uncertainty field
            if p_grid is not None and p_grid.size:
                u_grid = compute_spatial_uncertainty_field(
                    p_grid=p_grid,
                    lead_minutes=lead,
                    grid=grid,
                    missing_modalities=[m for m, ok in available.items() if not ok],
                    radar_available=available.get(Modality.RADAR.value, False),
                )
                u_mean = float(np.mean(u_grid))
                if uncertainty_png is None or lead == 30:
                    uncertainty_png = render_uncertainty_png(u_grid)
            else:
                u_grid = None
                u_mean = 0.0

            steps.append(ForecastStep(valid_time=t + timedelta(minutes=lead),
                                      lead_minutes=lead, p_flash_max=round(p_max, 3),
                                      risk_band=band, uncertainty_p_mean=round(u_mean, 3),
                                      cells=cells,
                                      p_flash_grid=p_grid,
                                      p_ci_grid=p_ci_grid,
                                      uncertainty_grid=u_grid))
            p_by_lead[lead] = dict(routed.output.p_cell)
            rung_by_lead[lead] = routed.rung
            if p_grid is not None:
                fields[lead] = (p_grid.astype(np.float32), render_probability_png(p_grid))

        self._uncertainty_png = uncertainty_png
        confidence = self._confidence(available, radar + satellite + lightning + surface + model)
        rung_order = [r.value for r in FallbackRung]
        best_rung = min(rung_by_lead.values(),
                        key=lambda r: rung_order.index(r.value)) if rung_by_lead else FallbackRung.CLIMATOLOGY
        notes = []
        if det_mod == Modality.SATELLITE:
            notes.append("detection on IR intensity proxy (radar unavailable) — reduced-modality rung")
        elif det_mod == Modality.SURFACE:
            notes.append("detection on IMERG precipitation proxy (radar/satellite unavailable) — reduced-modality rung")
        if not model_ok and Modality.MODEL in self.sources:
            notes.append("NWP environmental model unavailable/delayed — running reduced-modality fallback")
        if ci_candidates:
            notes.append(f"{len(ci_candidates)} convective initiation precursor candidate(s) tracked (15-45m lead)")
        forecast = Forecast(
            run_id=run_id, event_id=event_id, replay_time=t, mode=mode, fallback_rung=best_rung,
            model_version=self.model_version, grid=_meta_of(grid),
            modalities_used=[Modality(m) for m, ok in available.items() if ok],
            data_quality={"radar": modality_health(radar),
                          "satellite": modality_health(satellite),
                          "lightning": modality_health(lightning),
                          "surface": modality_health(surface),
                          "model": modality_health(model)},
            steps=steps, confidence=round(confidence, 3), notes=notes,
            ci_candidates=ci_candidates,
        )

        # Detect lightning jump cells (2-sigma flash count rate surge)
        jump_cells: set[str] = set()
        if len(feats):
            for _, r in feats.iterrows():
                f10 = float(r.get("flash_cnt_10", 0) or 0)
                f30 = float(r.get("flash_cnt_30", 0) or 0)
                past_rate = (f30 - f10) / 2.0
                is_jump, _, _ = detect_lightning_jump([past_rate, f10], min_flash_rate=6.0, sigma_threshold=2.0)
                if is_jump:
                    cid = str(r["_cell_id"])
                    jump_cells.add(cid)
                    matching_cell = next((c for c in cells if c.id == cid), None)
                    if matching_cell and t not in matching_cell.lightning_jump_times:
                        matching_cell.lightning_jump_times.append(t)

        alerts = self.alert_engine.generate(forecast, cells,
                                            lead_minutes=max(p_by_lead) if p_by_lead else None,
                                            p_cell=p_by_lead.get(max(p_by_lead) if p_by_lead else 0, {}),
                                            jump_cells=jump_cells)
        self._last_fields = fields
        # expose issue-time state for the replay runner's outcome settlement
        self._last_issue = (t, p_by_lead, cells,
                            feats.to_dict(orient="records") if feats is not None and len(feats) else [])
        return forecast, alerts

    def _confidence(self, available: dict[str, bool], frames: list[ObsFrame]) -> float:
        """Documented heuristic (NOT operationally validated): more healthy modalities
        raise confidence; suspect QC lowers it. Bounded [0.05, 0.9]."""
        n_ok = sum(1 for v in available.values() if v)
        base = 0.35 + 0.15 * max(0, n_ok - 1)
        suspect = sum(1 for f in frames if f.meta.quality.status != QualityStatus.OK)
        return float(np.clip(base - 0.05 * suspect, 0.05, 0.9))

    # -- replay runner with honest outcome settlement ---------------------------------
    def run_replay(self, event: Event, t_start: datetime, t_end: datetime,
                   step_minutes: int | None = None,
                   collect_training: bool = False) -> InferenceRun:
        step = step_minutes or max(10, self.settings.replay.cycle_minutes)
        self._active_grid = None
        self.tracker = None
        self._prev_ci_candidates = []
        self.alert_engine.reset()
        run = InferenceRun(event_id=event.id)
        max_lead = max(self.settings.replay.lead_minutes)

        pending: list[tuple[datetime, dict[int, dict[str, float]], list, list[dict]]] = []
        training_rows: list[dict] = []

        def settle(now: datetime) -> None:
            """Label any forecast whose outcome window has fully elapsed."""
            still = []
            for (t_issue, p_by_lead, cells, frows) in pending:
                done_leads = [L for L in p_by_lead if t_issue + timedelta(minutes=L) <= now]
                if not done_leads:
                    still.append((t_issue, p_by_lead, cells, frows))
                    continue
                for L in done_leads:
                    t1 = t_issue + timedelta(minutes=L)
                    actual_pts = self._flashes_between(t_issue, t1)
                    for cid, p in p_by_lead[L].items():
                        cell = next((c for c in cells if c.id == cid), None)
                        if cell is None:
                            continue
                        y = self._flash_in_cell(actual_pts, cell)
                        run.metrics.setdefault("samples", {}).setdefault(str(L), []).append(
                            {"p": p, "y": int(y)})
                        if collect_training and frows:
                            for r in frows:
                                if r["_cell_id"] == cid:
                                    row = {k: r.get(k) for k in FEATURE_NAMES}
                                    row["label"] = int(y)
                                    row["lead_minutes"] = L
                                    row["issue_time"] = t_issue.isoformat()
                                    row["cell_id"] = cid
                                    training_rows.append(row)
                remaining = {L: v for L, v in p_by_lead.items() if L not in done_leads}
                if remaining:
                    still.append((t_issue, remaining, cells, frows))
            pending[:] = still

        t = t_start
        while t <= t_end:
            settle(t)
            forecast, alerts = self.run_cycle(t, event.id, event.mode, run_id=run.id)
            run.forecasts.append(forecast.id)
            run.alerts.extend(a.id for a in alerts)
            pending.append((forecast.replay_time, self._last_p_by_lead(), self._last_cells(),
                            self._last_feature_rows))
            if self._store is not None:
                self._store.put_forecast(forecast, self._last_fields,
                                         obs_png=getattr(self, "_obs_png", None),
                                         uncertainty_png=getattr(self, "_uncertainty_png", None))
                self._store.put_alerts(alerts)
            t += timedelta(minutes=step)

        settle(t_end + timedelta(minutes=max_lead + 1))
        run.metrics["metrics"] = self._summarize(run.metrics.get("samples", {}))
        run.cycles = len(run.forecasts)
        run.finished_at = datetime.now(timezone.utc)
        if self._store is not None:
            self._store.put_run(run)
            self._store.put_verification(run.id, run.metrics)
            if collect_training and training_rows:
                path = self._store.put_training_samples(run.id, training_rows)
                run.metrics["training_samples_path"] = str(path)
        log_event(logger, 20, "replay done", event=event.id, cycles=run.cycles,
                  alerts=len(run.alerts), samples={k: len(v) for k, v in run.metrics.get("samples", {}).items()})
        return run

    # -- issue-time state handoff (kept explicit, not hidden globals) ------------------
    _last_issue: tuple = (None, None, None, [])

    def _last_p_by_lead(self) -> dict[int, dict[str, float]]:
        return self._last_issue[1] or {}

    def _last_cells(self) -> list:
        return self._last_issue[2] or []

    @property
    def _last_feature_rows(self) -> list[dict]:
        return self._last_issue[3] or []

    def _summarize(self, samples: dict) -> dict:
        """Per-lead verification summary computed from settled (p, y) samples."""
        from .verify import compute_verification_suite
        summary = {}
        for L, s in samples.items():
            if not len(s):
                continue
            p = np.array([x["p"] for x in s], dtype=float)
            y = np.array([x["y"] for x in s], dtype=float)
            summary[str(L)] = compute_verification_suite(p, y, threshold=0.35, n_bins=5)
        return summary


    def _flashes_between(self, t0: datetime, t1: datetime) -> np.ndarray:
        src = self.sources.get(Modality.LIGHTNING)
        if src is None:
            return np.zeros((0, 2), dtype=np.float32)
        frames = src.get_history(t1, int((t1 - t0).total_seconds() / 60.0) + 1)
        pts = []
        for f in frames:
            if f.points is None or not len(f.points):
                continue
            p = f.points
            if p.shape[1] >= 4:  # per-point absolute epoch seconds
                sel = (p[:, 3] >= t0.timestamp()) & (p[:, 3] <= t1.timestamp())
                if sel.any():
                    pts.append(p[sel, :2])
            elif t0 < f.meta.time <= t1:
                pts.append(p[:, :2])
        return np.concatenate(pts) if pts else np.zeros((0, 2), dtype=np.float32)

    def _flash_in_cell(self, pts: np.ndarray, cell) -> bool:
        if len(pts) == 0:
            return False
        lat_r = self.settings.cells.flash_radius_km / 111.32
        lon_r = self.settings.cells.flash_radius_km / max(
            1e-6, 111.32 * np.cos(np.radians(cell.centroid_lat)))
        return bool(((np.abs(pts[:, 0] - cell.centroid_lat) <= lat_r)
                     & (np.abs(pts[:, 1] - cell.centroid_lon) <= lon_r)).any())
