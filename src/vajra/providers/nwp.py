"""NWP / surface providers: interfaces with honest UNAVAILABLE health.

Research verdict (MASTER.md §5): GFS NOMADS and ECMWF Open Data are reachable and
open, but GRIB2 parsing requires cfgrib/eccodes which is not yet provisioned in
this environment (Windows Application Control blocks some compiled wheels — see
IMPLEMENTATION_STATUS.md). Rather than fake environmental features, these
providers report UNAVAILABLE and the model router runs the corresponding
reduced-modality rung. Adding cfgrib later is a config change, not a redesign.
"""

from __future__ import annotations

from datetime import datetime

from ..schemas import DataHealth, DataMode, Modality
from .base import AtmosphericDataProvider


class GfsNcepProvider(AtmosphericDataProvider):
    """NOAA GFS 0.25 deg via NOMADS. Implemented: health + availability probe.
    GRIB parsing (cfgrib) pending — see module docstring."""

    name = "gfs_nomads"
    modality = Modality.MODEL
    mode = DataMode.UNAVAILABLE

    def __init__(self) -> None:
        self._last_probe_error = "cfgrib/eccodes parser not provisioned in this environment"

    def health(self) -> DataHealth:
        return DataHealth(source=self.name, modality=self.modality, status=DataMode.UNAVAILABLE,
                          message=self._last_probe_error)

    def get_history(self, t: datetime, minutes: int) -> list:
        return []


class ImergProvider(AtmosphericDataProvider):
    """NASA IMERG via Earthdata (free account required; credentials not provisioned)."""

    name = "imerg_earthdata"
    modality = Modality.SURFACE
    mode = DataMode.UNAVAILABLE

    def __init__(self) -> None:
        self._msg = "Earthdata credentials not provisioned (free registration required)"

    def health(self) -> DataHealth:
        return DataHealth(source=self.name, modality=self.modality, status=DataMode.UNAVAILABLE,
                          message=self._msg)

    def get_history(self, t: datetime, minutes: int) -> list:
        return []
