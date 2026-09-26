"""Provider abstraction: the rest of the system never knows where data came from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from ..schemas import DataHealth, DataMode, Modality, ObsFrame


class AtmosphericDataProvider(ABC):
    """One modality of atmospheric observation for one domain/event.

    Contract:
    - `get_history(t, minutes)` returns frames with time <= t, oldest first.
    - Frames carry full metadata: source, mode, quality, grid, units.
    - Providers NEVER fabricate data to hide an outage; they report health instead.
    """

    name: str = "abstract"
    modality: Modality
    mode: DataMode = DataMode.UNAVAILABLE

    @abstractmethod
    def health(self) -> DataHealth: ...

    @abstractmethod
    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        """Observation frames in (t - minutes, t], oldest first."""

    def last_frame_before(self, t: datetime, minutes: int) -> ObsFrame | None:
        frames = self.get_history(t, minutes)
        return frames[-1] if frames else None


def clip_history_window(t: datetime, minutes: int) -> tuple[datetime, datetime]:
    return (t - timedelta(minutes=minutes), t)
