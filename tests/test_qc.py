from datetime import datetime, timedelta, timezone

import numpy as np

from vajra.grid import india_grid
from vajra.qc import modality_health, validate_frame
from vajra.schemas import DataMode, GridMeta, Modality, ObsFrame, ObsFrameMeta, QualityInfo, QualityStatus


def meta(variable="vil", mode=DataMode.REPLAY, t=None):
    from vajra.grid import GridSpec

    g = GridSpec(name="test_grid", lat0=26.0, lon0=83.0, dlat=-0.1, dlon=0.1,
                 nlat=5, nlon=5)
    return ObsFrameMeta(
        source="test", modality=Modality.RADAR, variable=variable, units="x",
        time=t or datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
        grid=GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                      nlat=g.nlat, nlon=g.nlon),
        mode=mode)


def test_in_range_field_passes():
    field = np.arange(25, dtype=float).reshape(5, 5) + 100.0  # varied, in range
    out = validate_frame(ObsFrame(meta(), field=field))
    assert out.meta.quality.status == QualityStatus.OK


def test_out_of_range_flagged():
    f = ObsFrame(meta(), field=np.full((5, 5), 300.0))  # > 255
    out = validate_frame(f)
    assert out.meta.quality.status == QualityStatus.SUSPECT
    assert "outside" in out.meta.quality.message


def test_missing_values_flagged():
    field = np.full((5, 5), 100.0)
    field[:4, :] = np.nan  # 80% missing -> MISSING
    out = validate_frame(ObsFrame(meta(), field=field))
    assert out.meta.quality.status == QualityStatus.MISSING
    assert out.meta.quality.missing_fraction > 0.5


def test_future_live_timestamp_flagged():
    now = datetime.now(timezone.utc)
    f = ObsFrame(meta(mode=DataMode.LIVE, t=now + timedelta(hours=2)), field=np.full((5, 5), 10.0))
    out = validate_frame(f, now=now)
    assert "future" in out.meta.quality.message


def test_stale_live_flagged_but_replay_not():
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=3)
    f_live = ObsFrame(meta(mode=DataMode.LIVE, t=old), field=np.full((5, 5), 10.0))
    assert validate_frame(f_live, now=now).meta.quality.stale
    f_rep = ObsFrame(meta(mode=DataMode.REPLAY, t=old), field=np.full((5, 5), 10.0))
    assert not validate_frame(f_rep, now=now).meta.quality.stale


def test_invalid_flash_coordinates_dropped():
    pts = np.array([[25.0, 85.0, 10.0, 0.0], [999.0, 85.0, 10.0, 0.0]], dtype=np.float32)
    out = validate_frame(ObsFrame(meta(variable="flash", mode=DataMode.REPLAY), points=pts))
    assert out.points.shape[0] == 1
    assert "invalid coordinates" in out.meta.quality.message


def test_modality_health_aggregation():
    ok = validate_frame(ObsFrame(meta(), field=np.arange(25, dtype=float).reshape(5, 5) + 100.0))
    all_missing = validate_frame(ObsFrame(meta(), field=np.full((5, 5), np.nan)))
    assert modality_health([ok]) == "OK"
    assert modality_health([ok, all_missing]) == "SUSPECT"  # degraded, not absent
    assert modality_health([all_missing]) == "MISSING"
    assert modality_health([]) == "MISSING"
