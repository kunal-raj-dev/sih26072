"""Nowcast models: baselines + late-fusion ML, behind one interface.

All models predict P(>=1 lightning flash within cell/area, next `lead` minutes).
Grid painting (cell probabilities -> 2-D field with a background) lives in
`painting.py` so every model composes the same way and the router can swap them.

Trained-on provenance is mandatory: no model ships without saying what trained it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from ..schemas import Cell


@dataclass
class CycleContext:
    """Everything a model may use at issue time t (no future data)."""

    t: object                       # issue time (datetime, tz-aware)
    grid: object                    # canonical GridSpec
    cells: list[Cell] = field(default_factory=list)
    radar_frames: list = field(default_factory=list)
    satellite_frames: list = field(default_factory=list)
    lightning_frames: list = field(default_factory=list)
    surface_frames: list = field(default_factory=list)
    model_frames: list = field(default_factory=list)
    features: object = None         # pandas.DataFrame from features.build_features
    modalities_available: dict[str, bool] = field(default_factory=dict)
    flash_radius_km: float = 12.0


@dataclass
class ModelOutput:
    p_cell: dict[str, float]        # cell_id -> P(flash within lead)
    background_p: float             # domain background probability (climatology)
    p_grid: np.ndarray | None = None  # optional full-grid probability field
    notes: list[str] = field(default_factory=list)


class NowcastModel(ABC):
    name: str = "abstract"
    version: str = "0"
    trained_on: str = "n/a"

    @abstractmethod
    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput: ...

    def available(self, ctx: CycleContext) -> bool:
        return True


def flashes_rate_per_min(cnt_10: float) -> float:
    return float(cnt_10) / 10.0


def poisson_p(rate_per_min: float, lead_minutes: int) -> float:
    """P(>=1 event) under Poisson rate — honest closed form, no magic."""
    lam = max(0.0, rate_per_min) * lead_minutes
    return float(1.0 - np.exp(-lam))
