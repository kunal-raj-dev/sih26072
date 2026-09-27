"""Baseline models. These are the yardstick every ML claim is measured against
(MASTER.md §7 / D8 E1-E2). Implemented exactly as described — no hidden ML."""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from .base import CycleContext, ModelOutput, NowcastModel, flashes_rate_per_min, poisson_p


def flashes_per_min_history(lightning_frames: list[ObsFrame], t, minutes: int) -> float:
    n = 0
    t0 = t - timedelta(minutes=minutes)
    for fr in lightning_frames:
        if t0 < fr.meta.time <= t and fr.points is not None:
            n += len(fr.points)
    return n / minutes if minutes else 0.0


class PersistenceModel(NowcastModel):
    """Flash-activity persistence: Poisson P from the observed flash rate in the
    past 10 minutes, per cell. Zero activity -> zero predicted probability
    (a deliberate, documented weakness of persistence)."""

    name = "persistence"
    version = "1.0"
    trained_on = "no training (observation rule)"

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        p_cell: dict[str, float] = {}
        feats = ctx.features
        if feats is not None and len(feats):
            for _, row in feats.iterrows():
                rate = flashes_rate_per_min(row["flash_cnt_10"])
                p_cell[row["_cell_id"]] = poisson_p(rate, lead_minutes)
        else:
            # No cells: domain-level persistence from total flash rate.
            rate = flashes_per_min_history(ctx.lightning_frames, ctx.t, 10)
            return ModelOutput(p_cell={}, background_p=poisson_p(rate, lead_minutes),
                               notes=["no cells; domain persistence"])
        return ModelOutput(p_cell=p_cell, background_p=0.0,
                           notes=["persistence of observed flash rate"])


class ClimatologyModel(NowcastModel):
    """Reference climatology: constant base rate estimated from a training
    sample's label prevalence, per lead. Required for Brier Skill Score."""

    name = "climatology"
    version = "1.0"
    trained_on: str = "set at fit time"

    def __init__(self) -> None:
        self.base_rate: float | None = None

    def fit(self, labels: list[int]) -> None:
        self.base_rate = float(np.mean(labels)) if labels else 0.0
        self.trained_on = f"label prevalence of {len(labels)} training samples"

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        p = self.base_rate if self.base_rate is not None else 0.0
        return ModelOutput(p_cell={c.id: p for c in ctx.cells}, background_p=p,
                           notes=[f"climatological base rate {p:.3f}"])


class LightningJumpModel(NowcastModel):
    """Classical 2-sigma lightning-jump rule (Schultz et al. 2009 lineage).

    Implementation: per cell, compare flash counts in the two most recent 5-min
    bins against the mean+2*std of the preceding bins within the history window.
    A jump raises the cell's probability above the persistence estimate; the
    threshold and boost are documented config, not learned."""

    name = "lightning_jump"
    version = "1.0"
    trained_on = "no training (threshold rule)"

    def __init__(self, jump_p: float = 0.85) -> None:
        self.jump_p = jump_p

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        p_cell: dict[str, float] = {}
        counts = self._flash_counts_per_5min(ctx)
        for cell in ctx.cells:
            base = self._cell_flash_rate(ctx, cell.id, lead_minutes)
            jumped = self._has_jump(counts.get(cell.id, []))
            p_cell[cell.id] = max(base, self.jump_p) if jumped else base
        return ModelOutput(p_cell=p_cell, background_p=0.0,
                           notes=["2-sigma flash-rate jump rule + persistence blend"])

    def _flash_counts_per_5min(self, ctx: CycleContext) -> dict[str, list[int]]:
        t = ctx.t
        bins = [t - timedelta(minutes=5 * k) for k in range(9, -1, -1)]  # 10 bin edges
        out: dict[str, list[int]] = {}
        for cell in ctx.cells:
            per_bin = []
            for k in range(10):
                t0, t1 = bins[k], bins[k + 1] if k < 9 else t
                n = 0
                for fr in ctx.lightning_frames:
                    if t0 < fr.meta.time <= t1 and fr.points is not None:
                        lat_r = ctx.flash_radius_km / 111.32
                        lon_r = ctx.flash_radius_km / max(1e-6, 111.32 * np.cos(np.radians(cell.centroid_lat)))
                        sel = ((np.abs(fr.points[:, 0] - cell.centroid_lat) <= lat_r)
                               & (np.abs(fr.points[:, 1] - cell.centroid_lon) <= lon_r))
                        n += int(sel.sum())
                per_bin.append(n)
            out[cell.id] = per_bin
        return out

    def _has_jump(self, bins: list[int]) -> bool:
        if len(bins) < 6:
            return False
        hist = np.array(bins[:-2], dtype=float)
        recent = bins[-2:]
        if hist.std() == 0 and hist.mean() == 0:
            return sum(recent) >= 6  # activity start from zero: treat sustained burst as jump
        mu, sd = hist.mean(), hist.std()
        return all(r > mu + 2 * sd for r in recent)

    def _cell_flash_rate(self, ctx: CycleContext, cell_id: str, lead_minutes: int) -> float:
        feats = ctx.features
        if feats is not None and len(feats):
            row = feats[feats["_cell_id"] == cell_id]
            if len(row):
                return poisson_p(row.iloc[0]["flash_cnt_10"] / 10.0, lead_minutes)
        return 0.0


class AdvectionModel(NowcastModel):
    """Optical-flow-lite advection: advect the current intensity field along the
    domain-mean cell motion and convert advected intensity to a Poisson-style
    probability. Documented limitation: advection carries motion, not growth/decay
    (the STEPS/DGMR motivation in the research)."""

    name = "advection"
    version = "1.0"
    trained_on = "no training (physics extrapolation)"

    def __init__(self, vil_threshold: float, intensity_to_rate: float = 0.05):
        self.vil_threshold = vil_threshold
        self.k = intensity_to_rate

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        if not ctx.radar_frames:
            return ModelOutput(p_cell={}, background_p=0.0, notes=["no radar field; unavailable"])
        field = ctx.radar_frames[-1].field
        cells = ctx.cells
        vlat = vlon = 0.0
        if cells:
            vlat = float(np.mean([c.motion_dlat for c in cells]))
            vlon = float(np.mean([c.motion_dlon for c in cells]))
        g = ctx.grid
        shift_i = int(round(vlat * (lead_minutes / 60.0) / abs(g.dlat)))
        shift_j = int(round(vlon * (lead_minutes / 60.0) / g.dlon))
        adv = np.zeros_like(field)
        src = field
        i0, i1 = max(0, shift_i), min(g.nlat, g.nlat + shift_i)
        j0, j1 = max(0, -shift_j), min(g.nlon, g.nlon - shift_j)
        di0, di1 = max(0, -shift_i), min(g.nlat, g.nlat - shift_i)
        dj0, dj1 = max(0, shift_j), min(g.nlon, g.nlon + shift_j)
        adv[di0:di1, dj0:dj1] = src[i0:i1, j0:j1]
        # Intensity above threshold -> Poisson probability of >=1 flash.
        intensity = np.clip((adv - self.vil_threshold) / max(1.0, 255 - self.vil_threshold), 0, 1)
        p_grid = 1.0 - np.exp(-self.k * intensity * lead_minutes)
        p_cell = {}
        for c in cells:
            i, j = g.index_of(c.centroid_lat, c.centroid_lon) or (None, None)
            if i is not None:
                p_cell[c.id] = float(p_grid[max(0, i - 2):i + 3, max(0, j - 2):j + 3].max())
        return ModelOutput(p_cell=p_cell, background_p=0.0, p_grid=p_grid,
                           notes=["advected intensity -> Poisson P", "motion-only (no growth/decay)"])
