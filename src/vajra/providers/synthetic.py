"""Deterministic synthetic storm events on the India grid. Mode: SIMULATION.

Purpose: hermetic tests, pipeline plumbing, and a demo fallback when no real event
is cached. Synthetic data is ALWAYS labelled DataMode.SIMULATION end-to-end.

Physics sketch (documented, not claimed as real meteorology):
- one primary cell advects north-east while intensifying then decaying;
- a secondary smaller cell trails it;
- IR brightness temperature dips where the cell is strongest (cold anvil proxy);
- lightning flash rate follows cell intensity x growth phase (Poisson sampling).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..config import Settings
from ..grid import GridSpec, india_grid, haversine_km
from ..schemas import (
    DataHealth,
    DataMode,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
    GridMeta,
    iso,
)
from .base import AtmosphericDataProvider

RNG_SEED_DEFAULT = 2026072


def _grid_meta(g: GridSpec) -> GridMeta:
    return GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                    nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)


@dataclass
class StormCellSpec:
    lat0: float
    lon0: float
    v_lat: float            # deg per hour
    v_lon: float
    peak_sigma: float       # deg
    peak_intensity: float   # 0..1 envelope
    t_ramp_up_h: float
    t_ramp_down_h: float


@dataclass
class SyntheticEvent:
    event_id: str
    start: datetime
    hours: float = 3.0
    cells: list[StormCellSpec] = field(default_factory=list)


def default_bihar_event(seed: int = RNG_SEED_DEFAULT, start: datetime | None = None) -> SyntheticEvent:
    """A 3-hour pre-monsoon-style event over Bihar/E-UP on the India grid."""
    start = start or datetime(2026, 5, 12, 13, 30, tzinfo=__import__("datetime").timezone.utc)
    return SyntheticEvent(
        event_id="SIM_BIHAR_001",
        start=start,
        hours=3.0,
        cells=[
            StormCellSpec(lat0=25.4, lon0=84.2, v_lat=0.35, v_lon=0.45,
                          peak_sigma=0.28, peak_intensity=1.0,
                          t_ramp_up_h=1.1, t_ramp_down_h=1.9),
            StormCellSpec(lat0=24.8, lon0=85.6, v_lat=0.20, v_lon=0.30,
                          peak_sigma=0.18, peak_intensity=0.55,
                          t_ramp_up_h=1.6, t_ramp_down_h=1.4),
        ],
    )


def cell_envelope(cell: StormCellSpec, t_hours: float) -> float:
    """0..1 life-cycle envelope: linear ramp-up, plateau, exponential decay."""
    total = cell.t_ramp_up_h + cell.t_ramp_down_h
    if t_hours < 0 or t_hours > total:
        return 0.0
    if t_hours < cell.t_ramp_up_h:
        return cell.peak_intensity * (t_hours / cell.t_ramp_up_h) ** 1.5
    frac = (t_hours - cell.t_ramp_up_h) / cell.t_ramp_down_h
    return cell.peak_intensity * float(np.exp(-2.2 * frac))


class SyntheticProvider(AtmosphericDataProvider):
    """Generates satellite/radar/lightning frames for a SyntheticEvent."""

    def __init__(self, event: SyntheticEvent, settings: Settings,
                 modality: Modality, grid: GridSpec | None = None):
        self.event = event
        self.settings = settings
        self.modality = modality
        self.mode = DataMode.SIMULATION
        self.name = f"synthetic_{modality.value}"
        self.rng = np.random.default_rng(RNG_SEED_DEFAULT + hash(event.event_id) % 9973)
        self._flash_cache: dict[int, np.ndarray] = {}
        self.grid = grid or india_grid(settings.grid.step_deg)

    # -- geometry -----------------------------------------------------------
    def _cell_state(self, cell: StormCellSpec, t: datetime) -> tuple[float, float, float]:
        t_hours = (t - self.event.start).total_seconds() / 3600.0
        env = cell_envelope(cell, t_hours)
        lat = cell.lat0 + cell.v_lat * t_hours
        lon = cell.lon0 + cell.v_lon * t_hours
        return lat, lon, env

    def _intensity_field(self, t: datetime) -> np.ndarray:
        """0..1 convective intensity envelope on the provider grid."""
        g = self.grid
        lat = g.lat0 + g.dlat * np.arange(g.nlat)[:, None]
        lon = g.lon0 + g.dlon * np.arange(g.nlon)[None, :]
        f = np.zeros((g.nlat, g.nlon), dtype=np.float32)
        for cell in self.event.cells:
            clat, clon, env = self._cell_state(cell, t)
            if env <= 0:
                continue
            sigma = cell.peak_sigma * (0.75 + 0.25 * env)
            d2 = ((lat - clat) ** 2 + (lon - clon) ** 2) / (2 * sigma**2)
            f += env * np.exp(-d2)
        return np.clip(f, 0.0, 1.0).astype(np.float32)

    def _flash_points(self, t: datetime, window_minutes: int) -> np.ndarray:
        """Flashes within (t-window, t]. Points: (N,4) lat, lon, energy, epoch_s."""
        out = []
        t0 = t - timedelta(minutes=window_minutes)
        m0 = int((t0 - self.event.start).total_seconds() // 60) + 1
        m1 = int((t - self.event.start).total_seconds() // 60)
        for m in range(max(0, m0), m1 + 1):
            if m not in self._flash_cache:
                self._flash_cache[m] = self._gen_flash_minute(m)
            pts = self._flash_cache[m]
            if pts is not None and len(pts):
                out.append(pts)
        return np.concatenate(out) if out else np.zeros((0, 4), dtype=np.float32)

    def _gen_flash_minute(self, minute: int) -> np.ndarray:
        rng = np.random.default_rng(RNG_SEED_DEFAULT + minute * 7919)
        t = self.event.start + timedelta(minutes=minute)
        epoch = t.timestamp()
        pts = []
        for cell in self.event.cells:
            clat, clon, env = self._cell_state(cell, t)
            rate = 22.0 * env**2.2  # flashes per minute at peak
            n = rng.poisson(rate)
            if n == 0:
                continue
            sigma = cell.peak_sigma * 0.6
            lats = rng.normal(clat, sigma, n)
            lons = rng.normal(clon, sigma / max(0.3, np.cos(np.radians(clat))), n)
            energ = rng.gamma(2.0, 8.0, n)
            pts.append(np.stack([lats, lons, energ, np.full(n, epoch)], axis=1))
        return np.concatenate(pts) if pts else np.zeros((0, 4), np.float32)

    # -- provider contract ---------------------------------------------------
    def health(self) -> DataHealth:
        return DataHealth(source=self.name, modality=self.modality, status=DataMode.SIMULATION,
                          last_success=self.event.start + timedelta(hours=self.event.hours),
                          message="deterministic synthetic generator (SIMULATION)")

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        frames: list[ObsFrame] = []
        cycle = timedelta(minutes=self.settings.replay.cycle_minutes)
        first = max(t - timedelta(minutes=minutes), self.event.start)
        tt = ((first - self.event.start) // cycle) * cycle + self.event.start
        while tt <= t:
            f = self._frame_at(tt)
            if f is not None:
                frames.append(f)
            tt = tt + cycle
        return frames

    def _frame_at(self, t: datetime) -> ObsFrame | None:
        common = dict(time=t, grid=_grid_meta(self.grid), mode=DataMode.SIMULATION,
                      quality=QualityInfo(status=QualityStatus.OK))
        if self.modality == Modality.SATELLITE:
            inten = self._intensity_field(t)
            field = 300.0 - 95.0 * inten  # brightness-temperature-like, K
            return ObsFrame(ObsFrameMeta(source=self.name, modality=Modality.SATELLITE,
                                         variable="bt_ir_proxy", units="K", note="synthetic IR proxy",
                                         **common), field=field.astype(np.float32))
        if self.modality == Modality.RADAR:
            inten = self._intensity_field(t)
            # VIL-raw-scale field (0-255) so config thresholds (e.g. 74) behave
            # exactly like the SEVIR replay path. Documented as a proxy.
            field = 255.0 * (inten ** 0.7)
            return ObsFrame(ObsFrameMeta(source=self.name, modality=Modality.RADAR,
                                         variable="vil_proxy", units="VIL raw scale equiv. (0-255)",
                                         note="synthetic radar/VIL proxy",
                                         **common), field=field.astype(np.float32))
        if self.modality == Modality.LIGHTNING:
            pts = self._flash_points(t, window_minutes=self.settings.replay.cycle_minutes)
            return ObsFrame(ObsFrameMeta(source=self.name, modality=Modality.LIGHTNING,
                                         variable="flash", units="count", note="synthetic flashes",
                                         **common), points=pts.astype(np.float32))
        return None
