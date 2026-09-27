"""Grid painting: cell probabilities -> full 2-D continuous probability field.

Replaced rectangular box painting and footprint dilation with continuous
anisotropic Gaussian kernel blending oriented along storm motion vectors.
"""

from __future__ import annotations

import numpy as np

from ..grid import GridSpec
from ..schemas import Cell, GridMeta
from .field_nowcast import generate_continuous_probability_field


def meta_to_spec(g: GridMeta) -> GridSpec:
    return GridSpec(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                    nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)


def paint_probability(p_cell: dict[str, float], cells: list[Cell], grid: GridSpec,
                      background_p: float, base_field: np.ndarray | None = None,
                      footprint_dilation: int = 1) -> np.ndarray:
    """Generate smooth continuous 2D probability field without rectangular step artifacts."""
    return generate_continuous_probability_field(
        cells=cells,
        p_cell=p_cell,
        grid=grid,
        background_p=background_p,
        base_unet_field=base_field,
    )
