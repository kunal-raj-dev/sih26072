"""NWP / environmental providers for Project Vajra."""

from __future__ import annotations

from .gfs import (
    GfsNomadsProvider,
    apply_thermodynamic_gating,
    compute_bulk_richardson_number,
    compute_bulk_wind_shear_0_6km,
    create_mock_gfs_grib2,
    decode_grib2_messages,
    encode_grib2_message,
    resample_gfs_to_grid,
    thermodynamic_gating_factor,
)

# Backwards compatibility alias
GfsNcepProvider = GfsNomadsProvider

__all__ = [
    "GfsNcepProvider",
    "GfsNomadsProvider",
    "apply_thermodynamic_gating",
    "compute_bulk_richardson_number",
    "compute_bulk_wind_shear_0_6km",
    "create_mock_gfs_grib2",
    "decode_grib2_messages",
    "encode_grib2_message",
    "resample_gfs_to_grid",
    "thermodynamic_gating_factor",
]
