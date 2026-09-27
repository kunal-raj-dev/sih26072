"""Verification suite for Phase 6: Deep Spatiotemporal U-Net & Multi-Modal ML Pipeline.

Covers:
1. Spatial Attention Gate mechanics and feature modulation.
2. Residual double-convolution blocks and gradient flow.
3. 4-level Spatiotemporal U-Net forward pass across multi-lead horizons (15, 30, 45, 60 min).
4. Binary Focal Loss and Soft Dice Loss computation and backpropagation.
5. Spatiotemporal dataset batching, spatial augmentation, and leave-event-out splitting.
6. LightningCastUNetModel lifecycle, weight persistence, and CycleContext inference.
7. Inference latency benchmark (verifying <= 2.0s per grid on CPU).
"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from vajra.config import Settings
from vajra.grid import make_india_grid
from vajra.schemas import (
    Cell, DataMode, Modality, ObsFrame, ObsFrameMeta,
    QualityInfo, QualityStatus, GridMeta,
)
from vajra.models.base import CycleContext
from vajra.models.dataset import (
    SpatiotemporalGridDataset,
    split_events_blocked,
    generate_synthetic_spatiotemporal_sample,
)
from vajra.models.unet import (
    HAS_TORCH,
    BinaryFocalLoss,
    CombinedFocalDiceLoss,
    LightningCastUNetModel,
    ResidualDoubleConv,
    SoftDiceLoss,
    SpatialAttentionGate,
    SpatiotemporalUNet,
    build_multimodal_tensor,
)

# Skip entire suite if torch is not installed
pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="PyTorch is required for Phase 6 U-Net tests")

if HAS_TORCH:
    import torch


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield Path(d)


# =============================================================================
# 1. Spatial Attention Gate & Residual Block Tests
# =============================================================================

def test_spatial_attention_gate():
    """Verify that spatial attention gates preserve spatial dimensions and modulate features."""
    b, f_g, f_l, f_int, h, w = 2, 64, 64, 32, 16, 16
    gate = SpatialAttentionGate(f_g=f_g, f_l=f_l, f_int=f_int)

    g = torch.randn(b, f_g, h, w)
    x = torch.randn(b, f_l, h, w)

    out = gate(g=g, x=x)

    assert out.shape == (b, f_l, h, w)
    assert not torch.isnan(out).any()


def test_residual_double_conv():
    """Verify residual double-convolution block with projection shortcut."""
    b, in_ch, out_ch, h, w = 2, 16, 32, 24, 24
    block = ResidualDoubleConv(in_ch=in_ch, out_ch=out_ch)

    x = torch.randn(b, in_ch, h, w, requires_grad=True)
    out = block(x)

    assert out.shape == (b, out_ch, h, w)
    # Check backward gradient flow
    loss = out.sum()
    loss.backward()
    assert x.grad is not None
    assert not torch.isnan(x.grad).any()


# =============================================================================
# 2. 4-Level U-Net Architecture & Multi-Lead Forward Pass
# =============================================================================

def test_unet_multi_lead_forward_pass():
    """Verify 4-level U-Net forward pass produces valid probabilities across 4 lead horizons."""
    b, in_channels, num_leads, h, w = 2, 4, 4, 64, 64
    unet = SpatiotemporalUNet(in_channels=in_channels, num_leads=num_leads, base_filters=16)

    inp = torch.rand(b, in_channels, h, w)
    out = unet(inp)

    # Output must match (B, num_leads, H, W)
    assert out.shape == (b, num_leads, h, w)
    # Sigmoid bounded in [0.0, 1.0]
    assert float(out.detach().min()) >= 0.0
    assert float(out.detach().max()) <= 1.0
    assert not torch.isnan(out).any()


# =============================================================================
# 3. Loss Functions: Binary Focal Loss & Soft Dice Loss
# =============================================================================

def test_binary_focal_loss_and_dice():
    """Verify Binary Focal Loss and Soft Dice Loss computation on sparse lightning targets."""
    b, k, h, w = 2, 4, 32, 32
    focal = BinaryFocalLoss(alpha=0.25, gamma=2.0)
    dice = SoftDiceLoss()
    combined = CombinedFocalDiceLoss(alpha=0.25, gamma=2.0, dice_weight=0.5)

    pred = torch.rand(b, k, h, w, requires_grad=True)
    # Sparse target: 98% zeros, 2% ones
    target = (torch.rand(b, k, h, w) > 0.98).float()

    l_focal = focal(pred, target)
    l_dice = dice(pred, target)
    l_comb = combined(pred, target)

    assert l_focal.item() > 0.0
    assert l_dice.item() > 0.0
    assert l_comb.item() > 0.0

    # Gradient backpropagation
    l_comb.backward()
    assert pred.grad is not None
    assert not torch.isnan(pred.grad).any()


# =============================================================================
# 4. Spatiotemporal Dataset & Event Splitting
# =============================================================================

def test_dataset_batching_and_augmentation():
    """Verify SpatiotemporalGridDataset batch generation and morphological augmentation."""
    samples = [generate_synthetic_spatiotemporal_sample(height=32, width=32) for _ in range(8)]
    dataset = SpatiotemporalGridDataset(samples, augment=True)

    assert len(dataset) == 8
    inp, target = dataset[0]

    assert inp.shape == (4, 32, 32)
    assert target.shape == (4, 32, 32)
    assert float(inp.min()) >= 0.0
    assert float(inp.max()) <= 1.0


def test_leave_event_out_splitting():
    """Verify strict disjoint partitioning of convective events."""
    events = [f"EVENT_{i:03d}" for i in range(20)]
    splits = split_events_blocked(events, train_frac=0.7, val_frac=0.15)

    train_set = set(splits["train"])
    val_set = set(splits["val"])
    test_set = set(splits["test"])

    # Disjointness checks: zero data leakage across folds
    assert len(train_set.intersection(val_set)) == 0
    assert len(train_set.intersection(test_set)) == 0
    assert len(val_set.intersection(test_set)) == 0
    assert len(train_set) + len(val_set) + len(test_set) == len(events)


# =============================================================================
# 5. LightningCastUNetModel Lifecycle & Inference
# =============================================================================

def test_lightningcast_unet_model_lifecycle(tmp_dir):
    """Verify model initialization, weight persistence, calibration, and inference."""
    grid = make_india_grid()
    model = LightningCastUNetModel(base_filters=16)
    assert model.name == "lightningcast_unet"

    # Synthetic observation frame
    t0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    meta = ObsFrameMeta(
        source="insat",
        modality=Modality.SATELLITE,
        variable="tir1",
        units="K",
        time=t0,
        grid=GridMeta(name=grid.name, lat0=grid.lat0, lon0=grid.lon0, dlat=grid.dlat, dlon=grid.dlon,
                      nlat=grid.nlat, nlon=grid.nlon, geolocation="exact"),
        quality=QualityInfo(status=QualityStatus.OK),
        mode=DataMode.REPLAY,
    )
    sat_field = np.full((grid.nlat, grid.nlon), 230.0, dtype=np.float32)  # Cold cloud
    sat_frame = ObsFrame(meta=meta, field=sat_field)

    cell = Cell(
        id="CELL_101",
        time=t0,
        centroid_lat=25.5,
        centroid_lon=85.0,
        area_px=100,
        max_intensity=50.0,
        mean_intensity=38.0,
        bbox=(84.5, 25.0, 85.5, 26.0),
    )

    ctx = CycleContext(
        t=t0,
        grid=grid,
        cells=[cell],
        satellite_frames=[sat_frame],
    )

    # Run inference for lead=30 min
    out = model.predict(ctx, lead_minutes=30)
    assert out.p_grid is not None
    assert out.p_grid.shape == (grid.nlat, grid.nlon)
    assert "CELL_101" in out.p_cell
    assert 0.0 <= out.p_cell["CELL_101"] <= 1.0

    # Save and reload weights
    save_dir = tmp_dir / "test_unet_save"
    model.save(save_dir, model_version="test-unet-v1")
    assert (save_dir / "unet_weights.pt").exists()
    assert (save_dir / "meta.json").exists()

    reloaded_model = LightningCastUNetModel(artifact_dir=save_dir, base_filters=16)
    reloaded_model.load()
    assert reloaded_model.version == "test-unet-v1"


# =============================================================================
# 6. Inference Latency Benchmark
# =============================================================================

def test_inference_latency_benchmark():
    """Verify that U-Net inference on a full regional grid executes well within operational threshold (<= 2.0s)."""
    grid = make_india_grid()
    model = LightningCastUNetModel(base_filters=16)
    t0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    ctx = CycleContext(t=t0, grid=grid, cells=[])

    # Warmup
    _ = model.predict(ctx, lead_minutes=30)

    # Benchmark timed run
    t_start = time.perf_counter()
    out = model.predict(ctx, lead_minutes=30)
    elapsed_s = time.perf_counter() - t_start

    assert elapsed_s < 2.0, f"Inference took {elapsed_s:.3f}s; exceeded operational limit of 2.0s"
    assert out.p_grid is not None
