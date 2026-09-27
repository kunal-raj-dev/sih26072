"""Provider package: data-source adapters behind one interface."""

from __future__ import annotations

from .base import AtmosphericDataProvider, clip_history_window
from .imd_radar import ImradarGifProvider, STATION_PRODUCT_PATHS
from .imerg import (
    ImergProvider,
    make_imerg_highres_grid,
    parse_imerg_hdf5,
    regrid_imerg,
)
from .lis import (
    LisProvider,
    create_mock_lis_hdf5,
    parse_lis_hdf5,
    verify_lightning_against_convective_cores,
)
from .mosdac import (
    MosdacProvider,
    compute_btd_ir_wv,
    compute_cooling_rate,
    compute_split_window_btd,
    counts_to_kelvin,
    create_mock_mosdac_hdf5,
    detect_convective_initiation,
    kelvin_to_radiance,
    load_processed_satellite_frame,
    radiance_to_kelvin,
    resample_to_india_grid,
    save_processed_satellite_frame,
)
from .gfs import (
    GfsProvider,
    apply_thermodynamic_gating,
    compute_bulk_richardson_number,
    compute_bulk_wind_shear_0_6km,
    create_mock_gfs_grib2,
    decode_grib2_messages,
    encode_grib2_message,
    extract_thermodynamic_sounding,
    resample_gfs_to_grid,
    thermodynamic_gating_factor,
)
from .nwp import (
    GfsNcepProvider,
    GfsNomadsProvider,
)
from .radar_mosaic import (
    RADAR_STATIONS,
    RadarMosaicEngine,
    RadarPolarSweep,
    RadarStation,
    RadarVolumeScan,
    polar_sweep_to_cartesian,
    simulate_synthetic_polar_sweep,
    simulate_synthetic_radar_scan,
    volume_to_maxz,
)
from .sevir import SevirCatalog, SevirReplayEvent, pick_event_with_most_flashes
from .synthetic import (
    SyntheticEvent,
    SyntheticProvider,
    StormCellSpec,
    default_bihar_event,
)

__all__ = [
    "AtmosphericDataProvider",
    "clip_history_window",
    "compute_btd_ir_wv",
    "compute_cooling_rate",
    "counts_to_kelvin",
    "create_mock_lis_hdf5",
    "create_mock_mosdac_hdf5",
    "create_mock_gfs_grib2",
    "detect_convective_initiation",
    "apply_thermodynamic_gating",
    "compute_bulk_richardson_number",
    "compute_bulk_wind_shear_0_6km",
    "GfsNcepProvider",
    "GfsNomadsProvider",
    "ImergProvider",
    "ImradarGifProvider",
    "thermodynamic_gating_factor",
    "kelvin_to_radiance",
    "LisProvider",
    "load_processed_satellite_frame",
    "MosdacProvider",
    "parse_lis_hdf5",
    "pick_event_with_most_flashes",
    "RADAR_STATIONS",
    "RadarMosaicEngine",
    "RadarStation",
    "RadarVolumeScan",
    "radiance_to_kelvin",
    "resample_to_india_grid",
    "save_processed_satellite_frame",
    "SevirCatalog",
    "SevirReplayEvent",
    "simulate_synthetic_radar_scan",
    "StormCellSpec",
    "SyntheticEvent",
    "SyntheticProvider",
    "default_bihar_event",
    "verify_lightning_against_convective_cores",
]

