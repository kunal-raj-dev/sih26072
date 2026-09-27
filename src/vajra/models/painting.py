"""Grid painting: cell probabilities -> full 2-D probability field.

The forecast product is a gridded probability field (canonical grid). Cell-level
model outputs are painted into the field with a dilated footprint; non-cell areas
carry the model's background (climatological) probability. The painter is shared
by every model so no model can look 'more spatially confident' than it is.
"""

from __future__ import annotations

import numpy as np

from ..ndx import dilate
from ..schemas import Cell, GridMeta
from ..grid import GridSpec


def meta_to_spec(g: GridMeta) -> GridSpec:
    return GridSpec(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                    nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)


def paint_probability(p_cell: dict[str, float], cells: list[Cell], grid: GridSpec,
                      background_p: float, base_field: np.ndarray | None = None,
                      footprint_dilation: int = 1) -> np.ndarray:
    p = np.full((grid.nlat, grid.nlon), float(np.clip(background_p, 0, 1)), dtype=np.float32)
    by_id = {c.id: c for c in cells}
    for cid, prob in p_cell.items():
        cell = by_id.get(cid)
        if cell is None:
            continue
        mask = np.zeros(p.shape, dtype=bool)
        i0 = int(round((cell.bbox[3] - grid.lat0) / grid.dlat))
        j0 = int(round((cell.bbox[0] - grid.lon0) / grid.dlon))
        i1 = int(round((cell.bbox[1] - grid.lat0) / grid.dlat))
        j1 = int(round((cell.bbox[2] - grid.lon0) / grid.dlon))
        i0, i1 = min(i0, i1), max(i0, i1)
        j0, j1 = min(j0, j1), max(j0, j1)
        i0 = max(0, i0); j0 = max(0, j0)
        i1 = min(grid.nlat - 1, i1); j1 = min(grid.nlon - 1, j1)
        if i1 < i0 or j1 < j0:
            continue
        mask[i0:i1 + 1, j0:j1 + 1] = True
        mask = dilate(mask, footprint_dilation)
        p[mask] = np.maximum(p[mask], float(np.clip(prob, 0, 1)))
    if base_field is not None:
        p = np.maximum(p, base_field.astype(np.float32))
    return p
