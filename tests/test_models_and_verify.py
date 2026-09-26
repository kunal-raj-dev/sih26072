import numpy as np
import pytest

from vajra.grid import india_grid
from vajra.models.baselines import (AdvectionModel, ClimatologyModel,
                                    LightningJumpModel, PersistenceModel)
from vajra.models.calibration import apply_isotonic, fit_isotonic
from vajra.models.base import CycleContext
from vajra.verify import (brier_score, brier_skill_score, contingency, fss,
                          pod_far_csi, reliability_curve)


def test_poisson_persistence_zero_activity_zero_probability():
    m = PersistenceModel()
    assert m.predict(_ctx(flash_cnt_10=0.0), 60).p_cell["C1"] == 0.0
    # 6 flashes/10min for 60 min -> P(>=1) ~ 1-exp(-36) ~ 1
    assert m.predict(_ctx(flash_cnt_10=6.0), 60).p_cell["C1"] > 0.99


def test_climatology_fit_prevalence():
    m = ClimatologyModel()
    m.fit([0, 1, 1, 0, 1])
    assert abs(m.base_rate - 0.6) < 1e-9


def test_isotonic_is_monotone_and_calibrates():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 1, 400)
    y = (rng.uniform(0, 1, 400) < x).astype(float)  # well-specified
    mapping = fit_isotonic(x, y)
    grid = np.linspace(0, 1, 21)
    out = apply_isotonic(mapping, grid)
    assert np.all(np.diff(out) >= -1e-9)  # monotone non-decreasing
    assert out[0] <= out[-1]


def test_jump_rule_fires_on_rate_burst():
    m = LightningJumpModel()
    assert m._has_jump([0, 0, 0, 0, 1, 0, 9, 9]) is True
    assert m._has_jump([5, 5, 5, 5, 5, 5, 5, 5]) is False


def test_advection_shifts_field_east():
    m = AdvectionModel(vil_threshold=74.0)
    ctx = _ctx(with_field=True, motion=(0.0, 0.5))  # 0.5 deg/cycle ≈ 55 km/h
    out = m.predict(ctx, 60)
    assert out.p_grid is not None
    g = ctx.grid
    assert int(np.unravel_index(out.p_grid.argmax(), out.p_grid.shape)[1]) > 76  # col of 85.0E


def test_contingency_and_scores():
    p = np.array([0.9, 0.9, 0.1, 0.1])
    y = np.array([1, 0, 0, 1])
    h, misses, fa, cn = contingency(p, y, 0.5)
    assert (h, misses, fa, cn) == (1, 1, 1, 1)
    pod, far, csi = pod_far_csi(h, misses, fa)
    assert abs(pod - 0.5) < 1e-9 and abs(far - 0.5) < 1e-9 and abs(csi - 1 / 3) < 1e-9
    assert abs(brier_score(p, y) - 0.41) < 1e-9
    ref = np.full(4, 0.5)
    assert brier_skill_score(p, y, ref) < 0  # this forecast is worse than 0.5 climatology


def test_reliability_curve_bins():
    p = np.array([0.05, 0.15, 0.5, 0.95])
    y = np.array([0, 0, 1, 1])
    curve = reliability_curve(p, y, n_bins=5)
    assert curve[0]["n"] == 2 and curve[-1]["n"] == 1


def test_fss_perfect_and_useless():
    a = np.zeros((10, 10))
    a[2:5, 2:5] = 1
    assert fss(a, a, window=5) == 1.0
    b = np.zeros((10, 10))
    b[7:10, 7:10] = 1
    assert fss(a, b, window=5) < 0.5


def _ctx(flash_cnt_10=0.0, with_field=False, motion=(0.0, 0.0)):
    from datetime import datetime, timezone
    from vajra.features import FEATURE_NAMES
    import pandas as pd

    t = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    g = india_grid(0.25)
    row = {k: np.nan for k in FEATURE_NAMES}
    row.update({"flash_cnt_10": flash_cnt_10, "_cell_id": "C1",
                "_centroid_lat": 25.0, "_centroid_lon": 85.0, "_bbox": "84,24,86,26"})
    cells = [type("C", (), {"id": "C1", "motion_dlat": motion[0],
                            "motion_dlon": motion[1], "centroid_lat": 25.0,
                            "centroid_lon": 85.0})()]
    radar_frames = []
    if with_field:
        blob = np.zeros((g.nlat, g.nlon), dtype=np.float32)
        for i, lat in enumerate(g.lats):
            for j, lon in enumerate(g.lons):
                blob[i, j] = 255 * np.exp(-(((lat - 25.0) ** 2 + (lon - 85.0) ** 2)))
        radar_frames = [type("F", (), {"field": blob})()]
    return CycleContext(
        t=t, grid=g, cells=cells,
        features=pd.DataFrame([row]),
        radar_frames=radar_frames, satellite_frames=[], lightning_frames=[],
        modalities_available={"radar": with_field, "satellite": False, "lightning": True},
    )
