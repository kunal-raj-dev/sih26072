from __future__ import annotations

from .baselines import AdvectionModel, ClimatologyModel, LightningJumpModel, PersistenceModel
from .base import CycleContext, ModelOutput, NowcastModel
from .calibration import apply_isotonic, compute_calibration_diagnostics, fit_isotonic
from .router import ModelRouter, RoutedForecast
from .xgb_fusion import XGBFusionModel
from .ci import (
    detect_convective_initiation,
    extract_ci_candidates_from_cycle,
    generate_ci_probability_grid,
    track_ci_candidates,
)
from .dataset import (
    SpatiotemporalGridDataset,
    generate_synthetic_spatiotemporal_sample,
    split_events_blocked,
)
from .field_nowcast import (
    ThreeTierUncertainty,
    compute_spatial_uncertainty_field,
    compute_three_tier_uncertainty,
    extrapolate_lagrangian_advection,
    generate_continuous_probability_field,
    get_lifecycle_tau_decay,
    render_uncertainty_png,
)
from .tensor_builder import (
    build_spatiotemporal_tensor,
    generate_synthetic_spatiotemporal_tensor,
    normalize_channel,
)
from .unet import (
    BinaryFocalLoss,
    CombinedFocalDiceLoss,
    CrossModalAttentionUNet,
    LightningCastUNetModel,
    MultiTaskOutput,
    MultiTaskSpatiotemporalUNet,
    ResidualDoubleConv,
    SoftDiceLoss,
    SpatialAttentionGate,
    SpatiotemporalUNet,
    build_multimodal_tensor,
)

__all__ = [
    "AdvectionModel",
    "BinaryFocalLoss",
    "ClimatologyModel",
    "CombinedFocalDiceLoss",
    "CrossModalAttentionUNet",
    "CycleContext",
    "LightningCastUNetModel",
    "LightningJumpModel",
    "ModelOutput",
    "ModelRouter",
    "MultiTaskOutput",
    "MultiTaskSpatiotemporalUNet",
    "NowcastModel",
    "PersistenceModel",
    "ResidualDoubleConv",
    "RoutedForecast",
    "SoftDiceLoss",
    "SpatialAttentionGate",
    "SpatiotemporalGridDataset",
    "SpatiotemporalUNet",
    "ThreeTierUncertainty",
    "XGBFusionModel",
    "apply_isotonic",
    "build_multimodal_tensor",
    "build_spatiotemporal_tensor",
    "compute_calibration_diagnostics",
    "compute_spatial_uncertainty_field",
    "compute_three_tier_uncertainty",
    "detect_convective_initiation",
    "extract_ci_candidates_from_cycle",
    "extrapolate_lagrangian_advection",
    "fit_isotonic",
    "generate_ci_probability_grid",
    "generate_continuous_probability_field",
    "generate_synthetic_spatiotemporal_sample",
    "generate_synthetic_spatiotemporal_tensor",
    "get_lifecycle_tau_decay",
    "normalize_channel",
    "render_uncertainty_png",
    "split_events_blocked",
    "track_ci_candidates",
]
