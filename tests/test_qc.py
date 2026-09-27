from datetime import datetime, timedelta, timezone

import numpy as np

from vajra.grid import india_grid
from vajra.qc import get_range_rule, modality_health, sevir_ir_to_kelvin, validate_frame
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


def test_source_aware_range_rules():
    assert get_range_rule("sevir", "bt_ir107") == (150.0, 350.0)
    assert get_range_rule("sevir_raw_ir", "bt_ir107") == (0.0, 255.0)
    assert get_range_rule("imerg", "precipitation") == (0.0, 500.0)
    assert get_range_rule("unknown_source", "vil") == (0.0, 255.0)
    assert get_range_rule("unknown_source", "unknown_var") == (-np.inf, np.inf)


def test_sevir_ir_to_kelvin_uint8():
    assert abs(sevir_ir_to_kelvin(0.0) - 150.0) < 1e-4
    assert abs(sevir_ir_to_kelvin(255.0) - 350.0) < 1e-4
    mid = sevir_ir_to_kelvin(128.0)
    assert 245.0 < mid < 255.0


def test_sevir_ir_to_kelvin_int16():
    # Cold overshooting top: -70.97 C -> 202.18 K
    k_cold = sevir_ir_to_kelvin(-7097)
    assert abs(k_cold - 202.18) < 0.05
    # Warm surface: +21.83 C -> 294.98 K
    k_warm = sevir_ir_to_kelvin(2183)
    assert abs(k_warm - 294.98) < 0.05
    # Array conversion
    arr = np.array([-7097, -3762, 2183], dtype=np.int16)
    k_arr = sevir_ir_to_kelvin(arr)
    assert k_arr.shape == (3,)
    assert 200.0 < k_arr[0] < 205.0
    assert 230.0 < k_arr[1] < 240.0
    assert 290.0 < k_arr[2] < 300.0


def test_sevir_ir_frame_passes_qc_cleanly():
    # Simulated SEVIR IR frame after Kelvin conversion (e.g. 210 K to 290 K)
    field = np.linspace(210.0, 290.0, 25, dtype=np.float32).reshape(5, 5)
    f = ObsFrame(meta(variable="bt_ir107"), field=field)
    f.meta.source = "sevir"
    f.meta.units = "Kelvin"
    out = validate_frame(f)
    assert out.meta.quality.status == QualityStatus.OK
    assert "outside" not in out.meta.quality.message


def test_sevir_raw_ir_rules():
    field = np.linspace(10.0, 240.0, 25, dtype=np.float32).reshape(5, 5)
    f = ObsFrame(meta(variable="bt_ir107"), field=field)
    f.meta.source = "sevir_raw_ir"
    out = validate_frame(f)
    assert out.meta.quality.status == QualityStatus.OK
    assert "outside" not in out.meta.quality.message


def test_ir_out_of_physical_range_flagged():
    # 100 K is unphysically cold (< 150 K)
    f_cold = ObsFrame(meta(variable="bt_ir107"), field=np.full((5, 5), 100.0))
    f_cold.meta.source = "sevir"
    out = validate_frame(f_cold)
    assert out.meta.quality.status == QualityStatus.SUSPECT
    assert "outside" in out.meta.quality.message

    # 400 K is unphysically hot (> 350 K)
    f_hot = ObsFrame(meta(variable="bt_ir107"), field=np.full((5, 5), 400.0))
    f_hot.meta.source = "sevir"
    out = validate_frame(f_hot)
    assert out.meta.quality.status == QualityStatus.SUSPECT
    assert "outside" in out.meta.quality.message

