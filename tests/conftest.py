from __future__ import annotations

from pathlib import Path

import pytest

from vajra.config import load_settings
from vajra.providers import default_bihar_event
from vajra.schemas import Modality


@pytest.fixture()
def settings(tmp_path: Path):
    s = load_settings()
    s.paths.data_root = str(tmp_path / "data")
    s.paths.models_dir = str(tmp_path / "models")
    s.paths.store_dir = str(tmp_path / "store")
    s.paths.web_dist = str(tmp_path / "web")  # no web mount in unit tests
    # Fast cycles keep tests quick
    s.replay.cycle_minutes = 10
    s.replay.history_minutes = 60
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture()
def bihar_event(settings):
    return default_bihar_event()


@pytest.fixture()
def synthetic_sources(settings, bihar_event):
    from vajra.providers import SyntheticProvider

    return {
        Modality.SATELLITE: SyntheticProvider(bihar_event, settings, Modality.SATELLITE),
        Modality.RADAR: SyntheticProvider(bihar_event, settings, Modality.RADAR),
        Modality.LIGHTNING: SyntheticProvider(bihar_event, settings, Modality.LIGHTNING),
    }
