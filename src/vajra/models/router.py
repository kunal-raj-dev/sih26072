"""Fallback router (MASTER.md D9 / research Part 29).

Rungs, exactly as designed:
  FULL_FUSION        — XGBoost with all verified modalities present
  REDUCED_MODALITY   — XGBoost with some modalities missing (NaN features)
  PHYSICS_BASELINE   — advection (+ jump rule) on the last observed field
  PERSISTENCE        — observed flash-rate persistence
  CLIMATOLOGY        — climatological base rate

The rung actually used is attached to every forecast. Degradation is information,
never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..schemas import FallbackRung, Modality
from .base import CycleContext, ModelOutput, NowcastModel
from .painting import paint_probability


@dataclass
class RoutedForecast:
    rung: FallbackRung
    model_name: str
    model_version: str
    output: ModelOutput


class ModelRouter:
    def __init__(self, fusion: NowcastModel | None,
                 physics: NowcastModel,
                 persistence: NowcastModel,
                 climatology: NowcastModel):
        self.fusion = fusion
        self.physics = physics
        self.persistence = persistence
        self.climatology = climatology

    def _required_modalities_ok(self, ctx: CycleContext) -> bool:
        req = [Modality.RADAR, Modality.SATELLITE, Modality.LIGHTNING]
        if Modality.MODEL.value in ctx.modalities_available:
            req.append(Modality.MODEL)
        return all(ctx.modalities_available.get(m.value, False) for m in req)

    def route(self, ctx: CycleContext) -> tuple[NowcastModel, FallbackRung]:
        if self.fusion is not None and self.fusion.available(ctx):
            if self._required_modalities_ok(ctx):
                return self.fusion, FallbackRung.FULL_FUSION
            return self.fusion, FallbackRung.REDUCED_MODALITY
        if self.physics.available(ctx) and ctx.modalities_available.get(Modality.RADAR.value, False):
            return self.physics, FallbackRung.PHYSICS_BASELINE
        if self.persistence.available(ctx):
            return self.persistence, FallbackRung.PERSISTENCE
        return self.climatology, FallbackRung.CLIMATOLOGY

    def predict(self, ctx: CycleContext, lead_minutes: int, grid_spec,
                ci_candidates: list | None = None) -> RoutedForecast:
        model, rung = self.route(ctx)
        out = model.predict(ctx, lead_minutes)
        if grid_spec is not None:
            from .field_nowcast import generate_continuous_probability_field
            out.p_grid = generate_continuous_probability_field(
                cells=ctx.cells,
                p_cell=out.p_cell,
                grid=grid_spec,
                background_p=out.background_p,
                base_unet_field=out.p_grid,
                ci_candidates=ci_candidates,
                lead_minutes=lead_minutes,
            )
        return RoutedForecast(rung=rung, model_name=model.name,
                              model_version=model.version, output=out)

    def health(self) -> dict:
        return {
            "fusion_loaded": bool(self.fusion and getattr(self.fusion, "_booster", None) is not None),
            "fusion_version": getattr(self.fusion, "version", None) if self.fusion else None,
            "physics": self.physics.name,
            "persistence": self.persistence.name,
            "climatology": self.climatology.name,
        }
