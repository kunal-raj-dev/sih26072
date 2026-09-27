"""Provider package: data-source adapters behind one interface."""

from __future__ import annotations

from .base import AtmosphericDataProvider, clip_history_window
from .imd_radar import ImradarGifProvider, STATION_PRODUCT_PATHS
from .imerg import ImergProvider
from .nwp import GfsNcepProvider
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
    "GfsNcepProvider",
    "ImergProvider",
    "ImradarGifProvider",
    "SevirCatalog",
    "SevirReplayEvent",
    "pick_event_with_most_flashes",
    "StormCellSpec",
    "SyntheticEvent",
    "SyntheticProvider",
    "default_bihar_event",
]
