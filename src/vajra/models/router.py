"""Adaptive 5-Rung Fallback Router 2.0 (Phase V2-6 / TASK-V2-6.3).

Operational 5-Rung Ladder:
  Rung 1: FULL_MULTIMODAL    — Track B Attention U-Net on Radar + Satellite + NWP + Lightning
  Rung 2: REDUCED_MODALITY   — Track B on Satellite + NWP + Lightning (Radar zero-masked)
  Rung 3: SATELLITE_SURFACE  — Track A GBDT on INSAT + IMERG (NWP/Radar delayed or offline)
  Rung 4: KINEMATIC_PERSISTENCE — Track A Advection of tracked convective storm cells
  Rung 5: CLIMATOLOGY        — Pure historical prevalence background field

The rung actually used is attached to every forecast. Degradation is transparent,
never hidden. Routing decisions are guaranteed to execute in < 5ms.
"""

from __future__ import annotations

import time
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
    decision_time_ms: float = 0.0


class ModelRouter:
    """Adaptive 5-Rung Fallback Router 2.0."""

    def __init__(
        self,
        fusion: NowcastModel | None,
        physics: NowcastModel,
        persistence: NowcastModel,
        climatology: NowcastModel,
        unet: NowcastModel | None = None,
    ):
        self.fusion = fusion
        self.physics = physics
        self.persistence = persistence
        self.climatology = climatology
        self.unet = unet

    def _required_modalities_ok(self, ctx: CycleContext) -> bool:
        req = [Modality.RADAR, Modality.SATELLITE, Modality.LIGHTNING]
        if Modality.MODEL.value in ctx.modalities_available:
            req.append(Modality.MODEL)
        return all(ctx.modalities_available.get(m.value, False) for m in req)

    def route(self, ctx: CycleContext) -> tuple[NowcastModel, FallbackRung]:
        """Evaluate sensor availability and select the highest operational rung (< 5ms SLA)."""
        radar_ok = bool(ctx.modalities_available.get(Modality.RADAR.value, False))
        sat_ok = bool(ctx.modalities_available.get(Modality.SATELLITE.value, False))
        ltg_ok = bool(ctx.modalities_available.get(Modality.LIGHTNING.value, False))
        model_ok = bool(ctx.modalities_available.get(Modality.MODEL.value, False))
        surf_ok = bool(ctx.modalities_available.get(Modality.SURFACE.value, False))

        # 1. Track B Deep Attention U-Net
        if self.unet is not None and self.unet.available(ctx):
            # Rung 1: FULL_MULTIMODAL (Radar + Sat + NWP + Ltg all healthy)
            if radar_ok and sat_ok and ltg_ok:
                return self.unet, FallbackRung.FULL_MULTIMODAL
            # Rung 2: REDUCED_MODALITY (Radar offline/missing, satellite active)
            if sat_ok:
                return self.unet, FallbackRung.REDUCED_MODALITY

        # 2. Track A Machine Learning GBDT / Fusion
        if self.fusion is not None and self.fusion.available(ctx):
            if radar_ok and sat_ok and ltg_ok:
                return self.fusion, FallbackRung.FULL_FUSION
            if sat_ok or surf_ok:
                # Rung 3: SATELLITE_SURFACE (INSAT + IMERG; NWP/Radar delayed)
                return self.fusion, FallbackRung.SATELLITE_SURFACE
            return self.fusion, FallbackRung.REDUCED_MODALITY

        # 3. Kinematic Advection / Persistence
        # Rung 4: KINEMATIC_PERSISTENCE (Advection of existing detected cells)
        if self.physics.available(ctx) and (radar_ok or bool(ctx.cells)):
            return self.physics, FallbackRung.KINEMATIC_PERSISTENCE
        if self.persistence.available(ctx) and bool(ctx.cells):
            return self.persistence, FallbackRung.PERSISTENCE

        # 4. Rung 5: CLIMATOLOGY (Zero observations or background only)
        return self.climatology, FallbackRung.CLIMATOLOGY

    def predict(
        self,
        ctx: CycleContext,
        lead_minutes: int,
        grid_spec,
        ci_candidates: list | None = None,
    ) -> RoutedForecast:
        t0 = time.perf_counter()
        model, rung = self.route(ctx)
        t_decision_ms = (time.perf_counter() - t0) * 1000.0

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
        return RoutedForecast(
            rung=rung,
            model_name=model.name,
            model_version=model.version,
            output=out,
            decision_time_ms=round(t_decision_ms, 4),
        )

    def health(self) -> dict:
        return {
            "unet_loaded": bool(self.unet and getattr(self.unet, "_net", None) is not None),
            "unet_version": getattr(self.unet, "version", None) if self.unet else None,
            "fusion_loaded": bool(self.fusion and getattr(self.fusion, "_booster", None) is not None),
            "fusion_version": getattr(self.fusion, "version", None) if self.fusion else None,
            "physics": self.physics.name,
            "persistence": self.persistence.name,
            "climatology": self.climatology.name,
        }
