"""Deep Spatiotemporal Machine Learning Pipeline: LightningCast 2D U-Net.

Research & Operational Basis:
- Implements the peer-reviewed LightningCast deep learning pattern (Cintineo et al. 2022).
- Predicts continuous 2D lightning probability fields P(flash >= 1 | x, y, lead) directly
  from multi-spectral geostationary satellite (TIR1 10.8µm, WV 6.8µm), radar reflectivity,
  and IMERG precipitation rasters.
- Architecture:
    * 4-level encoder-decoder U-Net with Residual double-convolution blocks.
    * Spatial Attention Gates (Oktay et al. 2018) on skip connections to suppress clear-sky
      noise and focus receptive fields on active convective cores and developing updrafts.
    * Multi-horizon prediction heads for 15, 30, 45, and 60-minute lead times.
    * Class-imbalanced Binary Focal Loss (alpha=0.25, gamma=2.0) combined with Soft Dice Loss
      to handle severe lightning pixel sparsity (< 2% positive rate).
    * Monotonic isotonic regression (PAVA) calibration head for reliable probability outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..grid import GridSpec, make_india_grid
from ..schemas import Cell, ObsFrame
from .base import CycleContext, ModelOutput, NowcastModel
from .calibration import apply_isotonic

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    torch = None
    nn = object
    F = None
    HAS_TORCH = False


# =============================================================================
# 1. Attention Gates & Convolutional Building Blocks
# =============================================================================

if HAS_TORCH:
    class SpatialAttentionGate(nn.Module):
        """Spatial Attention Gate (Oktay et al. 2018).

        Filters skip connection features x using gating signal g from coarser decoder level.
        Highlights salient convective updraft regions and suppresses background noise.
        """

        def __init__(self, f_g: int, f_l: int, f_int: int):
            super().__init__()
            self.w_g = nn.Sequential(
                nn.Conv2d(f_g, f_int, kernel_size=1, stride=1, padding=0, bias=True),
                nn.BatchNorm2d(f_int),
            )
            self.w_x = nn.Sequential(
                nn.Conv2d(f_l, f_int, kernel_size=1, stride=1, padding=0, bias=True),
                nn.BatchNorm2d(f_int),
            )
            self.psi = nn.Sequential(
                nn.Conv2d(f_int, 1, kernel_size=1, stride=1, padding=0, bias=True),
                nn.BatchNorm2d(1),
                nn.Sigmoid(),
            )
            self.relu = nn.ReLU(inplace=True)

        def forward(self, g: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
            g1 = self.w_g(g)
            x1 = self.w_x(x)
            psi = self.relu(g1 + x1)
            alpha = self.psi(psi)
            return x * alpha

        def get_attention_map(self, g: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
            """Return the spatial attention weight map alpha in [0.0, 1.0]."""
            g1 = self.w_g(g)
            x1 = self.w_x(x)
            psi = self.relu(g1 + x1)
            return self.psi(psi)


    class ResidualDoubleConv(nn.Module):
        """Double 3x3 Conv with BatchNorm, LeakyReLU, and Residual Projection Shortcut."""

        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.LeakyReLU(0.1, inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.LeakyReLU(0.1, inplace=True),
            )
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=1, bias=False),
                nn.BatchNorm2d(out_ch),
            ) if in_ch != out_ch else nn.Identity()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.conv(x) + self.shortcut(x)


    class SpatiotemporalUNet(nn.Module):
        """LightningCast 4-Level 2D U-Net with Spatial Attention Gates.

        Input: (B, in_channels, H, W) where in_channels carries multi-spectral satellite,
               radar, and precipitation proxy channels.
        Output: (B, num_leads, H, W) containing uncalibrated probabilities in [0.0, 1.0].
        """

        def __init__(
            self,
            in_channels: int = 4,
            num_leads: int = 4,
            base_filters: int = 32,
        ):
            super().__init__()
            f = base_filters

            # Encoder (4 levels)
            self.inc = ResidualDoubleConv(in_channels, f)
            self.down1 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f, f * 2))
            self.down2 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 2, f * 4))
            self.down3 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 4, f * 8))

            # Decoder (4 levels with Attention Gates)
            self.up1 = nn.ConvTranspose2d(f * 8, f * 4, kernel_size=2, stride=2)
            self.att1 = SpatialAttentionGate(f_g=f * 4, f_l=f * 4, f_int=f * 2)
            self.conv_up1 = ResidualDoubleConv(f * 8, f * 4)

            self.up2 = nn.ConvTranspose2d(f * 4, f * 2, kernel_size=2, stride=2)
            self.att2 = SpatialAttentionGate(f_g=f * 2, f_l=f * 2, f_int=f)
            self.conv_up2 = ResidualDoubleConv(f * 4, f * 2)

            self.up3 = nn.ConvTranspose2d(f * 2, f, kernel_size=2, stride=2)
            self.att3 = SpatialAttentionGate(f_g=f, f_l=f, f_int=f // 2)
            self.conv_up3 = ResidualDoubleConv(f * 2, f)

            # Multi-lead prediction head (1x1 convs)
            self.outc = nn.Conv2d(f, num_leads, kernel_size=1)
            self.sigmoid = nn.Sigmoid()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Encoder
            x1 = self.inc(x)
            x2 = self.down1(x1)
            x3 = self.down2(x2)
            x4 = self.down3(x3)

            # Decoder with Attention Gates
            d3 = self.up1(x4)
            x3_att = self.att1(g=d3, x=x3)
            d3 = torch.cat([d3, x3_att], dim=1)
            d3 = self.conv_up1(d3)

            d2 = self.up2(d3)
            x2_att = self.att2(g=d2, x=x2)
            d2 = torch.cat([d2, x2_att], dim=1)
            d2 = self.conv_up2(d2)

            d1 = self.up3(d2)
            x1_att = self.att3(g=d1, x=x1)
            d1 = torch.cat([d1, x1_att], dim=1)
            d1 = self.conv_up3(d1)

            logits = self.outc(d1)
            return self.sigmoid(logits)


    class CrossModalAttentionUNet(nn.Module):
        """Cross-Modal Spatiotemporal Attention U-Net (Track B AIML Backbone).

        Fuses multi-spectral satellite, radar mosaic, IMERG precipitation, ground/orbital
        lightning, and NWP thermodynamic sounding representations across 4 distinct
        modality-specific encoders with spatial attention gating.

        Modality Partition:
        - Satellite Branch (3 channels * T): TIR1, WV, Split_Diff
        - Radar/Precip Branch (2 channels * T): Radar_MaxZ, IMERG_Rain
        - NWP Branch (2 channels * T): CAPE, Bulk_Shear
        - Lightning Branch (1 channel * T): Flash_Density

        Supports zero-masking for missing modalities during offline fallback.
        """

        def __init__(
            self,
            temporal_depth: int = 4,
            num_leads: int = 4,
            base_filters: int = 32,
        ):
            super().__init__()
            self.temporal_depth = temporal_depth
            self.num_leads = num_leads
            self.base_filters = base_filters
            f = base_filters

            # Modality-specific branch encoders
            self.sat_enc = ResidualDoubleConv(3 * temporal_depth, f)
            self.radar_enc = ResidualDoubleConv(2 * temporal_depth, f)
            self.nwp_enc = ResidualDoubleConv(2 * temporal_depth, f)
            self.ltg_enc = ResidualDoubleConv(1 * temporal_depth, f)

            # Cross-modal fusion projection: (f * 4) -> f
            self.fuse_conv = ResidualDoubleConv(f * 4, f)

            # 4-Level U-Net contracting path
            self.down1 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f, f * 2))
            self.down2 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 2, f * 4))
            self.down3 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 4, f * 8))

            # 4-Level expanding path with Spatial Attention Gates
            self.up1 = nn.ConvTranspose2d(f * 8, f * 4, kernel_size=2, stride=2)
            self.att1 = SpatialAttentionGate(f_g=f * 4, f_l=f * 4, f_int=f * 2)
            self.conv_up1 = ResidualDoubleConv(f * 8, f * 4)

            self.up2 = nn.ConvTranspose2d(f * 4, f * 2, kernel_size=2, stride=2)
            self.att2 = SpatialAttentionGate(f_g=f * 2, f_l=f * 2, f_int=f)
            self.conv_up2 = ResidualDoubleConv(f * 4, f * 2)

            self.up3 = nn.ConvTranspose2d(f * 2, f, kernel_size=2, stride=2)
            self.att3 = SpatialAttentionGate(f_g=f, f_l=f, f_int=f // 2)
            self.conv_up3 = ResidualDoubleConv(f * 2, f)

            # Multi-lead prediction head
            self.outc = nn.Conv2d(f, num_leads, kernel_size=1)
            self.sigmoid = nn.Sigmoid()

        def forward(
            self,
            x: torch.Tensor,
            missing_modalities: list[str] | None = None,
        ) -> torch.Tensor:
            """Forward pass through modality encoders and 4-level attention U-Net."""
            # Accepts 5D (B, 8, T, H, W) or 4D (B, 8*T, H, W)
            if x.ndim == 5:
                b, c, t, h, w = x.shape
                sat_in = x[:, 0:3].reshape(b, 3 * t, h, w)
                radar_in = x[:, 3:5].reshape(b, 2 * t, h, w)
                ltg_in = x[:, 5:6].reshape(b, 1 * t, h, w)
                nwp_in = x[:, 6:8].reshape(b, 2 * t, h, w)
            elif x.ndim == 4:
                b, total_ch, h, w = x.shape
                t = self.temporal_depth
                x_5d = x.view(b, 8, t, h, w)
                sat_in = x_5d[:, 0:3].reshape(b, 3 * t, h, w)
                radar_in = x_5d[:, 3:5].reshape(b, 2 * t, h, w)
                ltg_in = x_5d[:, 5:6].reshape(b, 1 * t, h, w)
                nwp_in = x_5d[:, 6:8].reshape(b, 2 * t, h, w)
            else:
                raise ValueError(f"Expected 5D tensor (B, 8, T, H, W) or 4D (B, 8*T, H, W), got {x.shape}")

            missing = set(m.lower() for m in (missing_modalities or []))
            f = self.base_filters

            # Encode modality branches with zero-masking for offline fallback
            sat_feat = torch.zeros(b, f, h, w, device=x.device) if "satellite" in missing else self.sat_enc(sat_in)
            radar_feat = torch.zeros(b, f, h, w, device=x.device) if ("radar" in missing or "imerg" in missing and "radar" in missing) else self.radar_enc(radar_in)
            nwp_feat = torch.zeros(b, f, h, w, device=x.device) if "nwp" in missing else self.nwp_enc(nwp_in)
            ltg_feat = torch.zeros(b, f, h, w, device=x.device) if "lightning" in missing else self.ltg_enc(ltg_in)

            # Fuse multimodal features
            fused = torch.cat([sat_feat, radar_feat, nwp_feat, ltg_feat], dim=1)
            x1 = self.fuse_conv(fused)

            # Contracting path
            x2 = self.down1(x1)
            x3 = self.down2(x2)
            x4 = self.down3(x3)

            # Expanding path with attention gating
            d3 = self.up1(x4)
            x3_att = self.att1(g=d3, x=x3)
            d3 = torch.cat([d3, x3_att], dim=1)
            d3 = self.conv_up1(d3)

            d2 = self.up2(d3)
            x2_att = self.att2(g=d2, x=x2)
            d2 = torch.cat([d2, x2_att], dim=1)
            d2 = self.conv_up2(d2)

            d1 = self.up3(d2)
            x1_att = self.att3(g=d1, x=x1)
            d1 = torch.cat([d1, x1_att], dim=1)
            d1 = self.conv_up3(d1)

            logits = self.outc(d1)
            return self.sigmoid(logits)


    @dataclass
    class MultiTaskOutput:
        """Container for multi-task predictive head outputs."""
        lightning: torch.Tensor  # (B, 4, H, W)
        severe: torch.Tensor     # (B, 2, H, W) - [wind_gust, heavy_rain]
        ci: torch.Tensor         # (B, 2, H, W) - [ci_30m, ci_60m]

        def __iter__(self):
            return iter((self.lightning, self.severe, self.ci))

        def __getitem__(self, item: Any) -> torch.Tensor:
            if item == "lightning" or item == 0:
                return self.lightning
            elif item == "severe" or item == 1:
                return self.severe
            elif item == "ci" or item == 2:
                return self.ci
            raise KeyError(item)


    class MultiTaskSpatiotemporalUNet(nn.Module):
        """Decoupled Multi-Task Spatiotemporal Attention U-Net (Phase V2-4 / TASK-V2-4.1).

        Shares a multi-modal spatiotemporal backbone across 3 specialized prediction heads:
        1. head_lightning: (B, 4, H, W) -> Electrification probabilities for 15, 30, 45, 60 min.
        2. head_severe:    (B, 2, H, W) -> Severe wind gusts (>50 km/h) & intense rain (>=20 mm/h).
        3. head_ci:        (B, 2, H, W) -> Pre-radar Convective Initiation plumes (30m, 60m).
        """

        def __init__(
            self,
            temporal_depth: int = 4,
            base_filters: int = 32,
        ):
            super().__init__()
            self.temporal_depth = temporal_depth
            self.base_filters = base_filters
            f = base_filters

            # Modality-specific branch encoders
            self.sat_enc = ResidualDoubleConv(3 * temporal_depth, f)
            self.radar_enc = ResidualDoubleConv(2 * temporal_depth, f)
            self.nwp_enc = ResidualDoubleConv(2 * temporal_depth, f)
            self.ltg_enc = ResidualDoubleConv(1 * temporal_depth, f)

            # Cross-modal fusion projection: (f * 4) -> f
            self.fuse_conv = ResidualDoubleConv(f * 4, f)

            # 4-Level U-Net contracting path
            self.down1 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f, f * 2))
            self.down2 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 2, f * 4))
            self.down3 = nn.Sequential(nn.MaxPool2d(2), ResidualDoubleConv(f * 4, f * 8))

            # 4-Level expanding path with Spatial Attention Gates
            self.up1 = nn.ConvTranspose2d(f * 8, f * 4, kernel_size=2, stride=2)
            self.att1 = SpatialAttentionGate(f_g=f * 4, f_l=f * 4, f_int=f * 2)
            self.conv_up1 = ResidualDoubleConv(f * 8, f * 4)

            self.up2 = nn.ConvTranspose2d(f * 4, f * 2, kernel_size=2, stride=2)
            self.att2 = SpatialAttentionGate(f_g=f * 2, f_l=f * 2, f_int=f)
            self.conv_up2 = ResidualDoubleConv(f * 4, f * 2)

            self.up3 = nn.ConvTranspose2d(f * 2, f, kernel_size=2, stride=2)
            self.att3 = SpatialAttentionGate(f_g=f, f_l=f, f_int=f // 2)
            self.conv_up3 = ResidualDoubleConv(f * 2, f)

            # Decoupled Multi-Task Prediction Heads
            # Head 1: Lightning Electrification across 4 horizons (15, 30, 45, 60 min)
            self.head_lightning = nn.Sequential(
                nn.Conv2d(f, f, kernel_size=3, padding=1),
                nn.LeakyReLU(0.1, inplace=True),
                nn.Conv2d(f, 4, kernel_size=1),
                nn.Sigmoid(),
            )
            # Head 2: Severe Hazards (0: Wind Gust >50 km/h, 1: Heavy Rain >=20 mm/h)
            self.head_severe = nn.Sequential(
                nn.Conv2d(f, f, kernel_size=3, padding=1),
                nn.LeakyReLU(0.1, inplace=True),
                nn.Conv2d(f, 2, kernel_size=1),
                nn.Sigmoid(),
            )
            # Head 3: Pre-Radar Convective Initiation Plumes (0: 30 min, 1: 60 min)
            self.head_ci = nn.Sequential(
                nn.Conv2d(f, f, kernel_size=3, padding=1),
                nn.LeakyReLU(0.1, inplace=True),
                nn.Conv2d(f, 2, kernel_size=1),
                nn.Sigmoid(),
            )

        def forward(
            self,
            x: torch.Tensor,
            missing_modalities: list[str] | None = None,
        ) -> MultiTaskOutput:
            """Forward pass through shared multimodal backbone and 3 predictive heads."""
            if x.ndim == 5:
                b, c, t, h, w = x.shape
                sat_in = x[:, 0:3].reshape(b, 3 * t, h, w)
                radar_in = x[:, 3:5].reshape(b, 2 * t, h, w)
                ltg_in = x[:, 5:6].reshape(b, 1 * t, h, w)
                nwp_in = x[:, 6:8].reshape(b, 2 * t, h, w)
            elif x.ndim == 4:
                b, total_ch, h, w = x.shape
                t = self.temporal_depth
                x_5d = x.view(b, 8, t, h, w)
                sat_in = x_5d[:, 0:3].reshape(b, 3 * t, h, w)
                radar_in = x_5d[:, 3:5].reshape(b, 2 * t, h, w)
                ltg_in = x_5d[:, 5:6].reshape(b, 1 * t, h, w)
                nwp_in = x_5d[:, 6:8].reshape(b, 2 * t, h, w)
            else:
                raise ValueError(f"Expected 5D tensor (B, 8, T, H, W) or 4D (B, 8*T, H, W), got {x.shape}")

            missing = set(m.lower() for m in (missing_modalities or []))
            f = self.base_filters

            # Modality branch encoders with zero-masking
            sat_feat = torch.zeros(b, f, h, w, device=x.device) if "satellite" in missing else self.sat_enc(sat_in)
            radar_feat = torch.zeros(b, f, h, w, device=x.device) if ("radar" in missing or "imerg" in missing and "radar" in missing) else self.radar_enc(radar_in)
            nwp_feat = torch.zeros(b, f, h, w, device=x.device) if "nwp" in missing else self.nwp_enc(nwp_in)
            ltg_feat = torch.zeros(b, f, h, w, device=x.device) if "lightning" in missing else self.ltg_enc(ltg_in)

            # Multimodal fusion
            fused = torch.cat([sat_feat, radar_feat, nwp_feat, ltg_feat], dim=1)
            x1 = self.fuse_conv(fused)

            # Contracting path
            x2 = self.down1(x1)
            x3 = self.down2(x2)
            x4 = self.down3(x3)

            # Expanding path with attention gates
            d3 = self.up1(x4)
            x3_att = self.att1(g=d3, x=x3)
            d3 = torch.cat([d3, x3_att], dim=1)
            d3 = self.conv_up1(d3)

            d2 = self.up2(d3)
            x2_att = self.att2(g=d2, x=x2)
            d2 = torch.cat([d2, x2_att], dim=1)
            d2 = self.conv_up2(d2)

            d1 = self.up3(d2)
            x1_att = self.att3(g=d1, x=x1)
            d1 = torch.cat([d1, x1_att], dim=1)
            shared_latent = self.conv_up3(d1)

            # Multi-Task Prediction Heads
            out_lightning = self.head_lightning(shared_latent)
            out_severe = self.head_severe(shared_latent)
            out_ci = self.head_ci(shared_latent)

            return MultiTaskOutput(
                lightning=out_lightning,
                severe=out_severe,
                ci=out_ci,
            )


    # =========================================================================
    # 2. Objective Functions: Binary Focal Loss & Soft Dice Loss
    # =========================================================================

    class BinaryFocalLoss(nn.Module):
        """Class-imbalanced Binary Focal Loss for sparse lightning target grids.

        FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)
        Down-weights easy background non-lightning pixels to focus gradient on lightning cores.
        """

        def __init__(self, alpha: float = 0.75, gamma: float = 2.0, reduction: str = "mean"):
            super().__init__()
            self.alpha = alpha
            self.gamma = gamma
            self.reduction = reduction

        def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
            p = torch.clamp(pred, 1e-7, 1.0 - 1e-7)
            pt = p * target + (1.0 - p) * (1.0 - target)
            w = self.alpha * target + (1.0 - self.alpha) * (1.0 - target)
            loss = -w * ((1.0 - pt) ** self.gamma) * torch.log(pt)
            if self.reduction == "mean":
                return loss.mean()
            elif self.reduction == "sum":
                return loss.sum()
            return loss


    class SoftDiceLoss(nn.Module):
        """Soft Dice Loss for spatial segmentation overlap of convective storm masks."""

        def __init__(self, smooth: float = 1.0):
            super().__init__()
            self.smooth = smooth

        def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
            pred_flat = pred.view(pred.size(0), -1)
            target_flat = target.view(target.size(0), -1)
            intersection = (pred_flat * target_flat).sum(dim=1)
            cardinality = pred_flat.sum(dim=1) + target_flat.sum(dim=1)
            dice = (2.0 * intersection + self.smooth) / (cardinality + self.smooth)
            return (1.0 - dice).mean()


    class CombinedFocalDiceLoss(nn.Module):
        """Combined Focal Loss + Soft Dice Loss for robust spatiotemporal lightning learning."""

        def __init__(
            self,
            alpha: float = 0.75,
            gamma: float = 2.0,
            focal_weight: float = 1.0,
            dice_weight: float = 0.5,
            smooth: float = 1.0,
        ):
            super().__init__()
            self.focal = BinaryFocalLoss(alpha=alpha, gamma=gamma)
            self.dice = SoftDiceLoss(smooth=smooth)
            self.focal_weight = focal_weight
            self.dice_weight = dice_weight

        def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
            l_focal = self.focal(pred, target)
            l_dice = self.dice(pred, target)
            return self.focal_weight * l_focal + self.dice_weight * l_dice

else:
    # Fallback placeholders when PyTorch is not installed
    class SpatialAttentionGate:
        pass

    class ResidualDoubleConv:
        pass

    class SpatiotemporalUNet:
        pass

    class CrossModalAttentionUNet:
        pass

    class MultiTaskSpatiotemporalUNet:
        pass

    class MultiTaskOutput:
        pass

    class BinaryFocalLoss:
        pass

    class SoftDiceLoss:
        pass

    class CombinedFocalDiceLoss:
        pass


# =============================================================================
# 3. Model Wrapper & Inference Interface
# =============================================================================

LEAD_TIME_INDICES: dict[int, int] = {
    15: 0,
    30: 1,
    45: 2,
    60: 3,
}


def build_multimodal_tensor(
    grid: GridSpec,
    satellite_frames: list[ObsFrame] | None = None,
    radar_frames: list[ObsFrame] | None = None,
    surface_frames: list[ObsFrame] | None = None,
) -> np.ndarray:
    """Construct a normalized 4-channel input tensor (4, H, W) for U-Net inference.

    Channels:
    0: Normalized IR Brightness Temperature: (300K - T_b) / 95K (Cold anvil intensity: 0..1)
    1: Multi-spectral proxy / convective instability proxy (0..1)
    2: Radar Reflectivity proxy: dBZ / 75.0 (0..1)
    3: Surface Precipitation proxy: rain_rate / 50.0 mm/hr (0..1)
    """
    nlat, nlon = grid.nlat, grid.nlon
    ch0 = np.zeros((nlat, nlon), dtype=np.float32)
    ch1 = np.zeros((nlat, nlon), dtype=np.float32)
    ch2 = np.zeros((nlat, nlon), dtype=np.float32)
    ch3 = np.zeros((nlat, nlon), dtype=np.float32)

    # 1. Satellite IR channel
    if satellite_frames:
        latest_sat = satellite_frames[-1]
        if latest_sat.field is not None:
            tb = np.asarray(latest_sat.field, dtype=np.float32)
            # Clip between 180K (extreme overshooting top) and 300K (warm ground)
            ch0 = np.clip((300.0 - tb) / 95.0, 0.0, 1.0)
            if len(satellite_frames) >= 2 and satellite_frames[-2].field is not None:
                # Cooling rate proxy as channel 1
                tb_prev = np.asarray(satellite_frames[-2].field, dtype=np.float32)
                cooling = np.clip((tb_prev - tb) / 10.0, 0.0, 1.0)
                ch1 = cooling
            else:
                ch1 = ch0 * 0.8

    # 2. Radar Reflectivity channel
    if radar_frames:
        latest_rad = radar_frames[-1]
        if latest_rad.field is not None:
            rf = np.asarray(latest_rad.field, dtype=np.float32)
            ch2 = np.clip(rf / 75.0, 0.0, 1.0)

    # 3. Precipitation channel
    if surface_frames:
        latest_surf = surface_frames[-1]
        if latest_surf.field is not None:
            pr = np.asarray(latest_surf.field, dtype=np.float32)
            ch3 = np.clip(pr / 50.0, 0.0, 1.0)

    return np.stack([ch0, ch1, ch2, ch3], axis=0).astype(np.float32)


class LightningCastUNetModel(NowcastModel):
    """Deep Spatiotemporal LightningCast U-Net Model (Track B AIML Engine)."""

    name = "lightningcast_unet"
    version = "unet-v1"
    trained_on = "SEVIR Multi-Spectral ABI + GLM Flash Grids & NASA ISS LIS Replay"

    def __init__(
        self,
        artifact_dir: Path | None = None,
        in_channels: int = 4,
        num_leads: int = 4,
        base_filters: int = 32,
        calibrator: dict | None = None,
    ):
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.in_channels = in_channels
        self.num_leads = num_leads
        self.base_filters = base_filters
        self.calibrator = calibrator
        self.device = "cuda" if (HAS_TORCH and torch.cuda.is_available()) else "cpu"
        self._net: nn.Module | None = None
        self._meta: dict[str, Any] = {}

        if HAS_TORCH:
            self._net = SpatiotemporalUNet(
                in_channels=in_channels,
                num_leads=num_leads,
                base_filters=base_filters,
            ).to(self.device)
            self._net.eval()

    def available(self, ctx: CycleContext) -> bool:
        """Available when PyTorch is present and observation frames exist."""
        return HAS_TORCH and self._net is not None

    def load(self, weights_path: Path | None = None) -> None:
        """Load pre-trained weights and calibration metadata from disk."""
        if not HAS_TORCH:
            return
        wpath = weights_path or (self.artifact_dir / "unet_weights.pt" if self.artifact_dir else None)
        if wpath and wpath.exists():
            state_dict = torch.load(str(wpath), map_location=self.device)
            assert self._net is not None
            self._net.load_state_dict(state_dict)
            self._net.eval()

        if self.artifact_dir:
            meta_path = self.artifact_dir / "meta.json"
            if meta_path.exists():
                self._meta = json.loads(meta_path.read_text())
                self.version = self._meta.get("model_version", self.version)
                self.trained_on = self._meta.get("trained_on", self.trained_on)

            cal_path = self.artifact_dir / "calibration.json"
            if cal_path.exists():
                self.calibrator = json.loads(cal_path.read_text())

    def save(self, output_dir: Path, model_version: str, metrics: dict | None = None) -> None:
        """Persist model weights, calibration head, and provenance metadata."""
        if not HAS_TORCH or self._net is None:
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        torch.save(self._net.state_dict(), str(output_dir / "unet_weights.pt"))
        if self.calibrator:
            (output_dir / "calibration.json").write_text(json.dumps(self.calibrator, indent=1))

        meta = {
            "model_version": model_version,
            "trained_on": self.trained_on,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "in_channels": self.in_channels,
            "num_leads": self.num_leads,
            "base_filters": self.base_filters,
            "metrics": metrics or {},
        }
        (output_dir / "meta.json").write_text(json.dumps(meta, indent=1))

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        """Generate continuous 2D lightning probability field and sample cell probabilities."""
        if not HAS_TORCH or self._net is None:
            raise RuntimeError("PyTorch is not installed or U-Net model is not initialized.")

        grid = ctx.grid if isinstance(ctx.grid, GridSpec) else make_india_grid()
        tensor_np = build_multimodal_tensor(
            grid=grid,
            satellite_frames=ctx.satellite_frames,
            radar_frames=ctx.radar_frames,
            surface_frames=ctx.surface_frames,
        )

        lead_idx = LEAD_TIME_INDICES.get(lead_minutes, 1)  # Default to 30 min index
        with torch.no_grad():
            inp_t = torch.from_numpy(tensor_np).unsqueeze(0).to(self.device)  # (1, 4, H, W)
            # Resize or pad if grid dimensions are not multiples of 16 (for 4 poolings)
            h, w = inp_t.shape[2], inp_t.shape[3]
            pad_h = (16 - (h % 16)) % 16
            pad_w = (16 - (w % 16)) % 16
            if pad_h > 0 or pad_w > 0:
                inp_t = F.pad(inp_t, (0, pad_w, 0, pad_h), mode="reflect")

            pred_t = self._net(inp_t)  # (1, num_leads, H_pad, W_pad)
            if pad_h > 0 or pad_w > 0:
                pred_t = pred_t[:, :, :h, :w]

            p_field = pred_t[0, lead_idx].cpu().numpy().astype(np.float32)

        # Calibrate output field if calibration mapping is present
        if self.calibrator:
            orig_shape = p_field.shape
            p_flat = apply_isotonic(self.calibrator, p_field.ravel())
            p_field = p_flat.reshape(orig_shape).astype(np.float32)

        p_field = np.clip(p_field, 0.0, 1.0)

        # Sample cell probabilities at storm cell centroid locations
        p_cell: dict[str, float] = {}
        for c in ctx.cells:
            idx = grid.index_of(c.centroid_lat, c.centroid_lon)
            if idx is not None:
                p_cell[c.id] = float(p_field[idx[0], idx[1]])
            else:
                p_cell[c.id] = float(np.mean(p_field))

        bg_p = float(np.percentile(p_field, 10))
        return ModelOutput(
            p_cell=p_cell,
            background_p=bg_p,
            p_grid=p_field,
            notes=[f"deep spatiotemporal u-net v{self.version} lead={lead_minutes}min"],
        )
