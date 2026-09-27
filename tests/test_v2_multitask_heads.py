"""Verification suite for Phase V2-4:
Decoupled Multi-Task Predictive Heads & Lightning Jump Detection.

Covers:
- TASK-V2-4.1:
  - MultiTaskSpatiotemporalUNet architecture & 3 specialized prediction heads:
    * Head 1 (Lightning Electrification): (B, 4, H, W) for tau in {15, 30, 45, 60 min}.
    * Head 2 (Severe Thunderstorm Hazards): (B, 2, H, W) for wind gusts > 50 km/h and rain >= 20 mm/h.
    * Head 3 (Convective Initiation Plume): (B, 2, H, W) for pre-radar lead times 30m, 60m.
  - MultiTaskOutput container (dataclass attributes, dict indexing, tuple unpacking).
  - Missing modality zero-masking fallbacks and graceful degradation.
  - Gradient flow across all three predictive heads and shared backbone.

- TASK-V2-4.2:
  - Schulz et al. (2009, 2011) 2-Sigma Lightning Jump Detection algorithm with Poisson noise floor (>= 6 flashes/min).
  - Kinematic storm acceleration computation a = Delta v / Delta t in km/h^2.
  - CellTracker integration populating acceleration_kmh2 and acceleration_vector.
  - Cell schema serialization with acceleration and lightning jump times.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vajra.cells import (
    CellTracker,
    compute_kinematic_acceleration,
    detect_cells,
    detect_lightning_jump,
)
from vajra.config import CellsConfig
from vajra.grid import india_grid
from vajra.models.unet import (
    HAS_TORCH,
    MultiTaskOutput,
    MultiTaskSpatiotemporalUNet,
)
from vajra.schemas import Cell

pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="PyTorch is required for MultiTask UNet tests")

if HAS_TORCH:
    import torch


# =============================================================================
# 1. TASK-V2-4.1: MultiTaskOutput Container & Ergonomics
# =============================================================================

def test_multitask_output_container():
    """Verify MultiTaskOutput dataclass attributes, dict indexing, and tuple unpacking."""
    b, h, w = 2, 32, 32
    ltg = torch.zeros(b, 4, h, w)
    sev = torch.zeros(b, 2, h, w)
    ci = torch.zeros(b, 2, h, w)

    out = MultiTaskOutput(lightning=ltg, severe=sev, ci=ci)

    # 1. Attribute access
    assert out.lightning is ltg
    assert out.severe is sev
    assert out.ci is ci

    # 2. Integer index access
    assert out[0] is ltg
    assert out[1] is sev
    assert out[2] is ci

    # 3. String key access
    assert out["lightning"] is ltg
    assert out["severe"] is sev
    assert out["ci"] is ci

    # 4. Tuple unpacking
    l_unpack, s_unpack, c_unpack = out
    assert l_unpack is ltg
    assert s_unpack is sev
    assert c_unpack is ci

    # 5. Invalid index / key raises KeyError
    with pytest.raises(KeyError):
        _ = out["unknown_key"]
    with pytest.raises(KeyError):
        _ = out[99]


# =============================================================================
# 2. TASK-V2-4.1: MultiTaskSpatiotemporalUNet Forward Pass & Heads
# =============================================================================

def test_multitask_unet_5d_forward_pass():
    """Verify MultiTaskSpatiotemporalUNet on 5D tensor (B, 8, 4, H, W)."""
    torch.manual_seed(42)
    b, c, t, h, w = 2, 8, 4, 32, 32
    inp = torch.rand(b, c, t, h, w, dtype=torch.float32)

    model = MultiTaskSpatiotemporalUNet(temporal_depth=4, base_filters=16)
    model.eval()

    with torch.no_grad():
        out = model(inp)

    # Head 1: Lightning Electrification across 4 horizons (15, 30, 45, 60 min)
    assert isinstance(out, MultiTaskOutput)
    assert out.lightning.shape == (b, 4, h, w)
    assert float(out.lightning.min()) >= 0.0
    assert float(out.lightning.max()) <= 1.0
    assert not torch.isnan(out.lightning).any()
    assert not torch.isinf(out.lightning).any()

    # Head 2: Severe Thunderstorm Hazards (wind gust >50 km/h, intense rain >=20 mm/h)
    assert out.severe.shape == (b, 2, h, w)
    assert float(out.severe.min()) >= 0.0
    assert float(out.severe.max()) <= 1.0
    assert not torch.isnan(out.severe).any()
    assert not torch.isinf(out.severe).any()

    # Head 3: Convective Initiation Candidate Plumes (30m, 60m)
    assert out.ci.shape == (b, 2, h, w)
    assert float(out.ci.min()) >= 0.0
    assert float(out.ci.max()) <= 1.0
    assert not torch.isnan(out.ci).any()
    assert not torch.isinf(out.ci).any()


def test_multitask_unet_4d_flattened_forward_pass():
    """Verify MultiTaskSpatiotemporalUNet compatibility with 4D tensor (B, 8*T, H, W)."""
    b, total_ch, h, w = 2, 32, 32, 32  # 8 channels * 4 timesteps = 32 channels
    inp_4d = torch.rand(b, total_ch, h, w, dtype=torch.float32)

    model = MultiTaskSpatiotemporalUNet(temporal_depth=4, base_filters=16)
    model.eval()

    with torch.no_grad():
        out = model(inp_4d)

    assert out.lightning.shape == (b, 4, h, w)
    assert out.severe.shape == (b, 2, h, w)
    assert out.ci.shape == (b, 2, h, w)


def test_multitask_unet_missing_modalities_masking():
    """Verify missing modality zero-masking produces valid, bounded predictions with no NaNs."""
    b, c, t, h, w = 1, 8, 4, 32, 32
    inp = torch.rand(b, c, t, h, w, dtype=torch.float32)

    model = MultiTaskSpatiotemporalUNet(temporal_depth=4, base_filters=16)
    model.eval()

    scenarios = [
        ["radar"],
        ["satellite"],
        ["lightning"],
        ["nwp"],
        ["radar", "satellite"],
        ["radar", "lightning", "nwp"],
    ]

    for missing in scenarios:
        with torch.no_grad():
            out = model(inp, missing_modalities=missing)
            assert out.lightning.shape == (b, 4, h, w)
            assert out.severe.shape == (b, 2, h, w)
            assert out.ci.shape == (b, 2, h, w)
            assert not torch.isnan(out.lightning).any(), f"NaN in lightning with missing {missing}"
            assert not torch.isnan(out.severe).any(), f"NaN in severe with missing {missing}"
            assert not torch.isnan(out.ci).any(), f"NaN in ci with missing {missing}"


def test_multitask_unet_gradient_flow_all_heads():
    """Verify multi-task loss backward pass updates all three heads and shared backbone."""
    b, c, t, h, w = 1, 8, 4, 32, 32
    inp = torch.rand(b, c, t, h, w, dtype=torch.float32)

    model = MultiTaskSpatiotemporalUNet(temporal_depth=4, base_filters=16)
    model.train()

    out = model(inp)

    # Multi-task loss combination
    loss = (
        out.lightning.mean() * 1.0 +
        out.severe.mean() * 0.5 +
        out.ci.mean() * 0.5
    )
    loss.backward()

    # Check gradients on Head 1 (lightning)
    assert model.head_lightning[0].weight.grad is not None
    assert torch.isfinite(model.head_lightning[0].weight.grad).all()

    # Check gradients on Head 2 (severe)
    assert model.head_severe[0].weight.grad is not None
    assert torch.isfinite(model.head_severe[0].weight.grad).all()

    # Check gradients on Head 3 (ci)
    assert model.head_ci[0].weight.grad is not None
    assert torch.isfinite(model.head_ci[0].weight.grad).all()

    # Check gradients on shared multimodal fusion backbone
    assert model.fuse_conv.conv[0].weight.grad is not None
    assert torch.isfinite(model.fuse_conv.conv[0].weight.grad).all()


# =============================================================================
# 3. TASK-V2-4.2: Schulz et al. 2-Sigma Lightning Jump Detection
# =============================================================================

def test_lightning_jump_standard_surge():
    """Verify standard 2-sigma jump triggers when Delta F >= 2 * sigma_hist and F_recent >= 6."""
    # Past: [2, 2, 2] -> mean=2.0 -> sigma_hist=sqrt(2) ≈ 1.414 -> threshold = 2 * 1.414 ≈ 2.83
    # Recent: 14 -> Delta F = 12.0 >= 2.83, and 14 >= 6
    history = [2.0, 2.0, 2.0, 14.0]
    is_jump, delta_f, req_thresh = detect_lightning_jump(history, min_flash_rate=6.0, sigma_threshold=2.0)
    assert is_jump is True
    assert delta_f == 12.0
    assert req_thresh == pytest.approx(2.83, abs=0.05)


def test_lightning_jump_floor_suppression():
    """Verify Poisson noise floor (recent >= 6 flashes/min) suppresses low-count jumps."""
    # Past: [1, 1, 1] -> mean=1.0 -> sigma_hist=1.0 -> threshold = 2.0
    # Recent: 5 -> Delta F = 4.0 >= 2.0, BUT recent 5 < 6.0
    # Must NOT trigger jump
    history = [1.0, 1.0, 1.0, 5.0]
    is_jump, delta_f, req_thresh = detect_lightning_jump(history, min_flash_rate=6.0, sigma_threshold=2.0)
    assert is_jump is False
    assert delta_f == 0.0
    assert req_thresh == 0.0


def test_lightning_jump_calm_conditions():
    """Verify non-jump when surge does not exceed 2 * sigma_hist."""
    # Past: [10, 10, 10] -> mean=10.0 -> sigma_hist=sqrt(10) ≈ 3.16 -> threshold = 2 * 3.16 ≈ 6.32
    # Recent: 14 -> Delta F = 4.0 < 6.32
    history = [10.0, 10.0, 10.0, 14.0]
    is_jump, delta_f, req_thresh = detect_lightning_jump(history, min_flash_rate=6.0, sigma_threshold=2.0)
    assert is_jump is False
    assert delta_f == 4.0
    assert req_thresh == pytest.approx(6.32, abs=0.05)


def test_lightning_jump_elevated_surge():
    """Verify jump triggers in high background rate when Delta F >= 2 * sigma_hist."""
    # Past: [16, 16, 16] -> mean=16.0 -> sigma_hist=sqrt(16) = 4.0 -> threshold = 8.0
    # Recent: 26 -> Delta F = 10.0 >= 8.0, and 26 >= 6
    history = [16.0, 16.0, 16.0, 26.0]
    is_jump, delta_f, req_thresh = detect_lightning_jump(history, min_flash_rate=6.0, sigma_threshold=2.0)
    assert is_jump is True
    assert delta_f == 10.0
    assert req_thresh == 8.0


def test_lightning_jump_edge_cases():
    """Verify empty, short, or invalid history edge cases."""
    # Empty history
    assert detect_lightning_jump([]) == (False, 0.0, 0.0)

    # Below floor single item
    assert detect_lightning_jump([4.0]) == (False, 0.0, 0.0)

    # Above floor single item (immediate high detection)
    is_j, d_f, th = detect_lightning_jump([12.0])
    assert is_j is True
    assert d_f == 12.0
    assert th == 0.0


# =============================================================================
# 4. TASK-V2-4.2: Kinematic Storm Acceleration & CellTracker Integration
# =============================================================================

def test_compute_kinematic_acceleration_constant_velocity():
    """Zero acceleration when velocity remains constant."""
    dt_h = 10.0 / 60.0  # 10 minutes
    a_dlat, a_dlon, a_mag, a_vec = compute_kinematic_acceleration(
        current_vel=(0.5, 0.5),
        prev_vel=(0.5, 0.5),
        dt_hours=dt_h,
        lat=20.0,
    )
    assert a_dlat == 0.0
    assert a_dlon == 0.0
    assert a_mag == 0.0
    assert a_vec == [0.0, 0.0]


def test_compute_kinematic_acceleration_accelerating_cell():
    """Kinematic acceleration vector and magnitude for accelerating cell."""
    dt_h = 0.5  # 30 min = 0.5 h
    # Accelerating north: 0 deg/h -> 1 deg/h in lat
    a_dlat, a_dlon, a_mag, a_vec = compute_kinematic_acceleration(
        current_vel=(1.0, 0.0),
        prev_vel=(0.0, 0.0),
        dt_hours=dt_h,
        lat=0.0,  # equator for simple geometry
    )
    assert a_dlat == pytest.approx(2.0, abs=1e-3)  # (1 - 0) / 0.5 = 2 deg/h^2
    assert a_dlon == 0.0
    # ay = 2 * 111.12 = 222.24 km/h^2
    assert a_mag == pytest.approx(222.24, abs=0.5)
    assert a_vec[0] == 0.0
    assert a_vec[1] == pytest.approx(222.24, abs=0.5)


def test_cell_tracker_populates_acceleration_and_schema():
    """Verify CellTracker tracks acceleration across time steps and populates Cell schema."""
    grid = india_grid(0.25)
    cfg = CellsConfig(vil_threshold=50.0, min_area_px=2, max_track_speed_km_h=200.0)
    tracker = CellTracker(grid, cfg, cycle_minutes=10)

    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)
    t2 = t0 + timedelta(minutes=20)

    def make_field(c_lat: float, c_lon: float) -> np.ndarray:
        f = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
        idx = grid.index_of(c_lat, c_lon)
        assert idx is not None
        i, j = idx
        f[max(0, i - 1):min(grid.nlat, i + 2), max(0, j - 1):min(grid.nlon, j + 2)] = 60.0
        return f

    # Step 1: initial detection
    cells_t0 = tracker.step(t0, make_field(20.0, 80.0))
    assert len(cells_t0) == 1
    assert cells_t0[0].acceleration_kmh2 == 0.0
    assert cells_t0[0].acceleration_vector == [0.0, 0.0]

    # Step 2: cell moves slowly (0.05 deg east)
    cells_t1 = tracker.step(t1, make_field(20.0, 80.05))
    assert len(cells_t1) == 1
    assert cells_t1[0].id == cells_t0[0].id
    # has_initial_vel flag is now primed for acceleration calculation on next step

    # Step 3: cell accelerates eastward sharply (0.15 deg east in next step)
    cells_t2 = tracker.step(t2, make_field(20.0, 80.20))
    assert len(cells_t2) == 1
    cell2 = cells_t2[0]
    assert cell2.id == cells_t0[0].id

    # Kinematic acceleration fields must be populated
    assert hasattr(cell2, "acceleration_kmh2")
    assert hasattr(cell2, "acceleration_vector")
    assert cell2.acceleration_kmh2 > 0.0
    assert len(cell2.acceleration_vector) == 2

    # Verify Cell schema serialization
    cell_dict = cell2.dict()
    assert "acceleration_kmh2" in cell_dict
    assert "acceleration_vector" in cell_dict
    assert "lightning_jump_times" in cell_dict
    assert isinstance(cell_dict["acceleration_vector"], list)
