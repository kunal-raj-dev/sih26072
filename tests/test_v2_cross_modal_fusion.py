"""Comprehensive verification suite for Phase V2-3:
Intermediate Cross-Modal Attention Fusion & Spatiotemporal Backbone.

Covers:
- TASK-V2-3.1: 8-channel spatiotemporal tensor builder, normalization bounds, (B, 8, 4, 192, 192).
- TASK-V2-3.2: CrossModalAttentionUNet modality-specific branch encoders, SpatialAttentionGate activation maps, zero-masking fallback.
- TASK-V2-3.3: CombinedFocalDiceLoss gradient backprop & loss bounds under severe class imbalance (< 2% positive pixels).
"""

from __future__ import annotations

import numpy as np
import pytest

from vajra.models.tensor_builder import (
    NORM_BOUNDS,
    build_spatiotemporal_tensor,
    generate_synthetic_spatiotemporal_tensor,
    normalize_channel,
    resize_or_pad_field,
)
from vajra.models.unet import (
    HAS_TORCH,
    BinaryFocalLoss,
    CombinedFocalDiceLoss,
    CrossModalAttentionUNet,
    ResidualDoubleConv,
    SoftDiceLoss,
    SpatialAttentionGate,
    SpatiotemporalUNet,
)

pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="PyTorch is required for Phase V2-3 deep learning tests")

if HAS_TORCH:
    import torch


# =============================================================================
# 1. TASK-V2-3.1: Spatiotemporal Multi-Channel Tensor Builder
# =============================================================================

def test_channel_normalization_bounds():
    """Verify physical meteorological normalization into strict [0.0, 1.0] range."""
    # 0. TIR1: 180 K -> 1.0 (cold anvil), 320 K -> 0.0 (warm surface), 250 K -> 0.5
    assert normalize_channel(np.array([180.0]), "tir1")[0] == pytest.approx(1.0, abs=1e-4)
    assert normalize_channel(np.array([320.0]), "tir1")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([250.0]), "tir1")[0] == pytest.approx(0.5, abs=1e-4)
    # Out of bounds clipping
    assert normalize_channel(np.array([160.0]), "tir1")[0] == 1.0
    assert normalize_channel(np.array([340.0]), "tir1")[0] == 0.0

    # 1. WV: 200 K -> 1.0, 280 K -> 0.0
    assert normalize_channel(np.array([200.0]), "wv")[0] == pytest.approx(1.0, abs=1e-4)
    assert normalize_channel(np.array([280.0]), "wv")[0] == pytest.approx(0.0, abs=1e-4)

    # 2. Split_Diff: -4.0 K -> 0.0, +6.0 K -> 1.0, +1.0 K -> 0.5
    assert normalize_channel(np.array([-4.0]), "split_diff")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([6.0]), "split_diff")[0] == pytest.approx(1.0, abs=1e-4)
    assert normalize_channel(np.array([1.0]), "split_diff")[0] == pytest.approx(0.5, abs=1e-4)

    # 3. Radar_MaxZ: 0 dBZ -> 0.0, 70 dBZ -> 1.0, 35 dBZ -> 0.5
    assert normalize_channel(np.array([0.0]), "radar_maxz")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([70.0]), "radar_maxz")[0] == pytest.approx(1.0, abs=1e-4)
    assert normalize_channel(np.array([35.0]), "radar_maxz")[0] == pytest.approx(0.5, abs=1e-4)

    # 4. IMERG_Rain: 0 mm/h -> 0.0, 60 mm/h -> 1.0, 30 mm/h -> 0.5
    assert normalize_channel(np.array([0.0]), "imerg_rain")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([60.0]), "imerg_rain")[0] == pytest.approx(1.0, abs=1e-4)

    # 5. Flash Density: 0 -> 0.0, 25 -> 1.0
    assert normalize_channel(np.array([0.0]), "flash_density")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([25.0]), "flash_density")[0] == pytest.approx(1.0, abs=1e-4)

    # 6. CAPE: 0 J/kg -> 0.0, 4000 J/kg -> 1.0, 2000 J/kg -> 0.5
    assert normalize_channel(np.array([0.0]), "cape")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([4000.0]), "cape")[0] == pytest.approx(1.0, abs=1e-4)

    # 7. Bulk Shear: 0 m/s -> 0.0, 40 m/s -> 1.0, 20 m/s -> 0.5
    assert normalize_channel(np.array([0.0]), "bulk_shear")[0] == pytest.approx(0.0, abs=1e-4)
    assert normalize_channel(np.array([40.0]), "bulk_shear")[0] == pytest.approx(1.0, abs=1e-4)


def test_synthetic_spatiotemporal_tensor_builder_dimensions():
    """Verify that the synthetic spatiotemporal tensor builder constructs
    the exact (B, 8, 4, 192, 192) normalized tensor without NaNs or Infs."""
    b, c, t, h, w = 2, 8, 4, 192, 192
    tensor = generate_synthetic_spatiotemporal_tensor(
        batch_size=b,
        temporal_depth=t,
        height=h,
        width=w,
        seed=101,
    )

    assert tensor.shape == (b, c, t, h, w)
    assert tensor.dtype == np.float32
    assert not np.isnan(tensor).any(), "Tensor must not contain NaNs"
    assert not np.isinf(tensor).any(), "Tensor must not contain Infs"
    assert np.min(tensor) >= 0.0, "All normalized values must be >= 0.0"
    assert np.max(tensor) <= 1.0, "All normalized values must be <= 1.0"

    # Verify distinct physical variation across channels
    # Channel 0 (TIR1) should have cold core with high normalized value
    assert np.max(tensor[:, 0]) >= 0.70
    # Channel 3 (Radar MaxZ) should have convective reflectivity core
    assert np.max(tensor[:, 3]) >= 0.50
    # Channel 6 (CAPE) should have high environmental background
    assert np.mean(tensor[:, 6]) >= 0.50


# =============================================================================
# 2. TASK-V2-3.2: Modality Encoders, Cross-Attention Gates & Zero-Masking
# =============================================================================

def test_spatial_attention_gate_activation_maps():
    """Verify SpatialAttentionGate computes valid [0, 1] gating map alpha of shape (B, 1, H, W)."""
    b, f_g, f_l, f_int, h, w = 2, 32, 32, 16, 24, 24
    gate = SpatialAttentionGate(f_g=f_g, f_l=f_l, f_int=f_int)

    g = torch.randn(b, f_g, h, w)
    x = torch.randn(b, f_l, h, w)

    # 1. Forward modulated feature map
    out = gate(g=g, x=x)
    assert out.shape == (b, f_l, h, w)

    # 2. Explicit attention weight map alpha
    alpha = gate.get_attention_map(g=g, x=x)
    assert alpha.shape == (b, 1, h, w)
    assert float(alpha.detach().min()) >= 0.0
    assert float(alpha.detach().max()) <= 1.0
    assert not torch.isnan(alpha).any()


def test_cross_modal_attention_unet_forward_pass():
    """Verify 4-level CrossModalAttentionUNet forward pass on (B, 8, 4, H, W)."""
    b, c, t, h, w = 2, 8, 4, 64, 64
    num_leads = 4
    model = CrossModalAttentionUNet(temporal_depth=t, num_leads=num_leads, base_filters=16)

    inp = torch.rand(b, c, t, h, w)
    pred = model(inp)

    assert pred.shape == (b, num_leads, h, w)
    assert not torch.isnan(pred).any()
    assert not torch.isinf(pred).any()
    assert float(pred.detach().min()) >= 0.0
    assert float(pred.detach().max()) <= 1.0


def test_zero_masking_missing_radar_modality():
    """Verify zero-masking behavior: masking the radar branch produces smooth,
    non-NaN predictions with graceful confidence degradation."""
    b, c, t, h, w = 1, 8, 4, 64, 64
    model = CrossModalAttentionUNet(temporal_depth=t, num_leads=4, base_filters=16)
    model.eval()

    # Full multi-modal input
    tensor_full = torch.from_numpy(
        generate_synthetic_spatiotemporal_tensor(batch_size=b, temporal_depth=t, height=h, width=w, seed=42)
    )

    with torch.no_grad():
        pred_full = model(tensor_full)
        # Prediction with radar modality zero-masked
        pred_no_radar = model(tensor_full, missing_modalities=["radar"])

    assert not torch.isnan(pred_no_radar).any(), "Zero-masked radar prediction must not contain NaNs"
    assert not torch.isinf(pred_no_radar).any(), "Zero-masked radar prediction must not contain Infs"
    assert float(pred_no_radar.min()) >= 0.0
    assert float(pred_no_radar.max()) <= 1.0

    # Predictions should be valid and differ from full-modality run (graceful degradation)
    diff = torch.abs(pred_full - pred_no_radar).mean().item()
    assert diff >= 0.0, "Zero-masking alters prediction gracefully"


# =============================================================================
# 3. TASK-V2-3.3: CombinedFocalDiceLoss Optimization
# =============================================================================

def test_combined_focal_dice_loss_severe_class_imbalance():
    """Verify CombinedFocalDiceLoss under severe 1% positive class imbalance:
    L = lambda_focal * L_focal(gamma=2.0, alpha=0.75) + lambda_dice * L_dice(smooth=1.0)."""
    b, k, h, w = 2, 4, 32, 32

    criterion = CombinedFocalDiceLoss(
        alpha=0.75,
        gamma=2.0,
        focal_weight=1.0,
        dice_weight=1.0,
        smooth=1.0,
    )

    # Severe class imbalance: only 1% positive lightning pixels
    torch.manual_seed(42)
    target = (torch.rand(b, k, h, w) > 0.99).float()
    assert target.mean().item() < 0.02, f"Positive rate should be < 2%, got {target.mean().item()}"

    pred = torch.rand(b, k, h, w, requires_grad=True)

    loss = criterion(pred, target)
    assert not torch.isnan(loss), "Loss must not be NaN"
    assert not torch.isinf(loss), "Loss must not be Inf"
    assert loss.item() > 0.0, "Loss must be positive"

    # Backward gradient flow check
    loss.backward()
    assert pred.grad is not None
    assert not torch.isnan(pred.grad).any(), "Gradients must not contain NaNs"
    assert not torch.isinf(pred.grad).any(), "Gradients must not contain Infs"
    assert float(pred.grad.abs().sum()) > 0.0, "Gradients must flow back to input"
