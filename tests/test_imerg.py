"""Offline unit tests for the IMERG provider's parsing logic (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from vajra.config import Settings, load_settings
from vajra.providers.imerg import ImergProvider, FILE_RE


def test_file_regex_matches_gesdisc_naming():
    html = ('href="3B-HHR-E.MS.MRG.3IMERG.20260926-S163000-E165959.0990.V07C.HDF5"'
            ' href="3B-HHR-E.MS.MRG.3IMERG.20260926-S163000-E165959.0990.V07C.HDF5.xml"'
            ' href="3B-HHR.MS.MRG.3IMERG.20250101-S113000-E115959.1140.V07B.HDF5"')
    matches = [(m.group(1), m.group(2), m.group(3)) for m in FILE_RE.finditer(html)]
    assert len(matches) == 2  # the .xml variant must not match
    assert matches[0][1] == "20260926" and matches[0][2] == "163000"
    assert matches[1][1] == "20250101"


def test_slot_parsing_from_filename(tmp_path):
    p = tmp_path / "3B-HHR-E.MS.MRG.3IMERG.20260926-S163000-E165959.0990.V07C.HDF5"
    p.write_bytes(b"\x89HDF\r\n")
    # _parse_india needs a real HDF5 file; here we only verify the regex path.
    import re
    m = re.search(r"3IMERG\.(\d{8})-S(\d{6})", p.name)
    slot = datetime.strptime(m.group(1) + m.group(2)[:4], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    assert slot == datetime(2026, 9, 26, 16, 30, tzinfo=timezone.utc)


def test_unconfigured_credentials_reported_honestly(tmp_path):
    s = Settings(paths__data_root=str(tmp_path)) if False else None
    settings = load_settings()
    settings.earthdata.username = ""
    settings.earthdata.password = ""
    provider = ImergProvider(settings)
    assert provider.health().status.value == "UNAVAILABLE"
    assert "credentials" in provider.health().message.lower()
    assert provider.get_history(datetime.now(timezone.utc), 60) == []


def test_validate_url_blocks_non_nasa():
    from vajra.providers.imerg import _validate_url

    _validate_url("https://gpm1.gesdisc.eosdis.nasa.gov/data/x")
    _validate_url("https://urs.earthdata.nasa.gov/oauth/authorize")
    for bad in ["http://gpm1.gesdisc.eosdis.nasa.gov/data",          # plain http
                "https://evil.example.com/data",                     # wrong host
                "https://gpm1.gesdisc.eosdis.nasa.gov.evil.com/x"]:  # suffix spoof
        with pytest.raises(ValueError):
            _validate_url(bad)
