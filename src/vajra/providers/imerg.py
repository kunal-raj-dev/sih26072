"""NASA IMERG half-hourly precipitation via GES DISC (Earthdata Login). REAL data.

Research verification (MASTER.md §5 / Deliverable 2): IMERG V07 Early Run is free
with an Earthdata account, ~4 h latency, 0.1 deg, half-hourly, full India coverage.
This provider makes it the system's first REAL India-domain observation:

- DataMode.LIVE (near-real-time; the ~4 h latency is stated in health.message)
- auth: Earthdata basic-auth redirect flow; redirect hosts restricted to *.nasa.gov
- files cached under data/external/imerg/ so replays run offline afterwards

Notes: IMERG is a satellite-derived precipitation product (not gauge truth) and is
documented as such wherever it is displayed or used as an evaluation proxy.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import numpy as np

from ..config import Settings
from ..grid import GridSpec, make_india_grid
from ..schemas import (
    DataHealth,
    DataMode,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
    GridMeta,
)
from ..logsetup import get_logger, log_event
from .base import AtmosphericDataProvider

logger = get_logger("vajra.providers.imerg")

GES_DISC_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov"
# Early run = near-real-time (~4 h); Final run = research-grade, lags months.
IMERG_DATASETS = ("GPM_3IMERGHHE.07", "GPM_3IMERGHH.07")
ALLOWED_HOST_SUFFIX = "nasa.gov"          # URS + GES DISC both resolve here
INDIA_WINDOW = {"lat_min": 6.0, "lat_max": 38.0, "lon_min": 66.0, "lon_max": 98.0}
FILE_RE = re.compile(
    r'href="(3B-HHR[^"]*\.MS\.MRG\.3IMERG\.(\d{8})-S(\d{6})-E(\d{6})\.\d{4}\.V[^"]*\.HDF5)"')


def _validate_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https":
        raise ValueError(f"scheme '{u.scheme}' not allowed")
    host = u.hostname or ""
    if not (host == ALLOWED_HOST_SUFFIX or host.endswith("." + ALLOWED_HOST_SUFFIX)):
        raise ValueError(f"host '{host}' outside allowed domain {ALLOWED_HOST_SUFFIX}")


class ImergProvider(AtmosphericDataProvider):
    """IMERG V07 half-hourly precipitation, India window, Earthdata-authenticated."""

    name = "imerg_earthdata"
    modality = Modality.SURFACE
    mode = DataMode.LIVE

    def __init__(self, settings: Settings, timeout_s: float = 60.0):
        self.settings = settings
        self.timeout_s = timeout_s
        self._client: httpx.Client | None = None
        self._serving_dataset = ""
        self._last_success: datetime | None = None
        self._last_error = "" if settings.earthdata.configured else "Earthdata credentials not configured (.env: EARTHDATA_USERNAME/PASSWORD)"
        self.cache = settings.data_root / "external" / "imerg"
        self.cache.mkdir(parents=True, exist_ok=True)

    # ---- auth ---------------------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            ed = self.settings.earthdata
            if not ed.configured:
                raise RuntimeError("Earthdata credentials not configured")
            self._client = httpx.Client(auth=(ed.username, ed.password),
                                        timeout=self.timeout_s)
        return self._client

    def _get(self, url: str) -> httpx.Response:
        """GET with manual redirects restricted to nasa.gov hosts (SSRF hardening)."""
        _validate_url(url)
        client = self._http()
        resp = client.get(url, follow_redirects=False)
        for _ in range(5):
            if resp.is_redirect:
                nxt = urljoin(url, resp.headers.get("location", ""))
                _validate_url(nxt)
                url, resp = nxt, client.get(nxt, follow_redirects=False)
                continue
            break
        resp.raise_for_status()
        return resp

    # ---- health --------------------------------------------------------------
    def health(self) -> DataHealth:
        if self._last_success is not None:
            return DataHealth(source=self.name, modality=self.modality, status=DataMode.LIVE,
                              last_success=self._last_success,
                              message=f"IMERG {self._serving_dataset or 'Early'} (~4 h NRT for Early run), Earthdata-authenticated")
        return DataHealth(source=self.name, modality=self.modality, status=DataMode.UNAVAILABLE,
                          message=self._last_error or "not fetched yet")

    # ---- file discovery -------------------------------------------------------
    def _day_listing(self, day: datetime) -> tuple[list[tuple[datetime, str]], str]:
        """(slot_start, file_url) for one UTC day; Early run first, Final fallback."""
        last_err: Exception | None = None
        for ds in IMERG_DATASETS:
            # GES DISC layout: dataset/<year>/<day-of-year DDD>/
            url = f"{GES_DISC_BASE}/data/GPM_L3/{ds}/{day:%Y}/{day:%j}/"
            try:
                html = self._get(url).text
            except httpx.HTTPStatusError as exc:
                last_err = exc
                continue  # e.g. 404 for months not yet published in this dataset
            out: list[tuple[datetime, str]] = []
            for m in FILE_RE.finditer(html):
                ymd = datetime.strptime(m.group(2), "%Y%m%d").date()
                hh, mm = int(m.group(3)[0:2]), int(m.group(3)[2:4])
                start = datetime(ymd.year, ymd.month, ymd.day, hh, mm, tzinfo=timezone.utc)
                out.append((start, urljoin(url, m.group(1))))
            if out:
                return sorted(out), ds
        if last_err is not None:
            raise last_err
        return [], IMERG_DATASETS[-1]

    def _slot_file(self, slot: datetime) -> str | None:
        day = slot.replace(hour=0, minute=0, second=0, microsecond=0)
        listing, ds = self._day_listing(day)
        self._serving_dataset = ds
        for start, url in listing:
            if start <= slot < start + timedelta(minutes=30):
                return url
        return None

    # ---- download + parse -------------------------------------------------------
    def _fetch_file(self, url: str) -> Path:
        name = url.rsplit("/", 1)[-1]
        local = self.cache / name
        if local.exists() and local.stat().st_size > 1_000_000:
            return local
        log_event(logger, 20, "downloading IMERG file", url=url)
        resp = self._get(url)
        local.write_bytes(resp.content)
        return local

    @staticmethod
    def _parse_india(path: Path) -> tuple[np.ndarray, GridSpec, datetime]:
        import h5py

        # Slot start time from the file name:
        # 3B-HHR-E.MS.MRG.3IMERG.YYYYMMDD-SHHMMSS-EHHMMSS.MMMM.Vxx.HDF5
        m = re.search(r"3IMERG\.(\d{8})-S(\d{6})", path.name)
        if not m:
            raise ValueError(f"unrecognized IMERG file name: {path.name}")
        slot = datetime.strptime(m.group(1) + m.group(2)[:4], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)

        with h5py.File(path, "r") as f:
            grid = f["Grid"]
            var = next((v for v in ("precipitation", "precipitationCal") if v in grid))
            d = grid[var]
            # V07C stores (time, lon, lat); older layouts may store (time, lat, lon)
            if d.ndim == 4:
                data = d[0, 0, :, :]
            elif d.ndim == 3:
                data = d[0, :, :]
            else:
                data = d[:, :]
            data = np.asarray(data, dtype=np.float32)          # mm/hr
            lats = grid["lat"][:].astype(float)
            lons = grid["lon"][:].astype(float)
            if data.shape != (len(lats), len(lons)):           # orient to (lat, lon)
                data = data.T
        # India window slice
        i0 = max(0, int(np.searchsorted(lats, INDIA_WINDOW["lat_min"])) - 1)
        i1 = int(np.searchsorted(lats, INDIA_WINDOW["lat_max"])) + 1
        j0 = max(0, int(np.searchsorted(lons, INDIA_WINDOW["lon_min"])) - 1)
        j1 = int(np.searchsorted(lons, INDIA_WINDOW["lon_max"])) + 1
        win = data[i0:i1, j0:j1]
        step = 0.1
        g = GridSpec(name="imerg_0p1_india", lat0=float(lats[i0]),
                     lon0=float(lons[j0]), dlat=step, dlon=step,
                     nlat=int(win.shape[0]), nlon=int(win.shape[1]), geolocation="exact")
        return win, g, slot

    # ---- provider contract ------------------------------------------------------
    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        """IMERG frames in (t - minutes, t] at 30-min cadence (India window)."""
        if not self.settings.earthdata.configured:
            return []
        frames: list[ObsFrame] = []
        slot0 = t - timedelta(minutes=minutes)
        slot = slot0.replace(second=0, microsecond=0)
        if slot.minute % 30:
            slot += timedelta(minutes=30 - slot.minute % 30)
        try:
            while slot <= t:
                url = self._slot_file(slot)
                if url is not None:
                    path = self._fetch_file(url)
                    win, g, _ = self._parse_india(path)
                    gm = GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat,
                                  dlon=g.dlon, nlat=g.nlat, nlon=g.nlon, geolocation="exact")
                    meta = ObsFrameMeta(
                        source=self.name, modality=Modality.SURFACE,
                        variable="precipitation", units="mm/hr", time=slot, grid=gm,
                        mode=DataMode.LIVE, quality=QualityInfo(status=QualityStatus.OK),
                        note="IMERG V07 Early — satellite-derived precipitation (NRT ~4 h); not gauge truth")
                    frames.append(ObsFrame(meta, field=win))
                    self._last_success = datetime.now(timezone.utc)
                    self._last_error = ""
                slot += timedelta(minutes=30)
        except Exception as exc:  # noqa: BLE001 — provider boundary: record honestly
            self._last_error = f"{type(exc).__name__}: {exc}"
            log_event(logger, 30, "imerg fetch failed", error=self._last_error)
        return frames


def make_imerg_highres_grid(
    lat_min: float = 6.0,
    lat_max: float = 38.0,
    lon_min: float = 66.0,
    lon_max: float = 98.0,
    step_deg: float = 0.02,
) -> GridSpec:
    """Create a 0.02° high-resolution Cartesian GridSpec covering the Indian domain."""
    nlat = int(round((lat_max - lat_min) / step_deg))
    nlon = int(round((lon_max - lon_min) / step_deg))
    return GridSpec(
        name="india_0p02",
        lat0=lat_min,
        lon0=lon_min,
        dlat=step_deg,
        dlon=step_deg,
        nlat=nlat,
        nlon=nlon,
        geolocation="exact",
    )


def regrid_imerg(
    field: np.ndarray,
    src_grid: GridSpec,
    target_grid: GridSpec,
) -> np.ndarray:
    """Bilinear / nearest regridding of an IMERG rainfall field onto any target GridSpec (e.g. 0.1° or 0.02°)."""
    if field.shape == (target_grid.nlat, target_grid.nlon) and src_grid == target_grid:
        return field.astype(np.float32)

    target_lats = target_grid.lats
    target_lons = target_grid.lons

    lat_frac = (target_lats[:, None] - src_grid.lat0) / max(src_grid.dlat, 1e-6)
    lon_frac = (target_lons[None, :] - src_grid.lon0) / max(src_grid.dlon, 1e-6)

    i0 = np.clip(np.floor(lat_frac).astype(int), 0, src_grid.nlat - 2)
    j0 = np.clip(np.floor(lon_frac).astype(int), 0, src_grid.nlon - 2)
    i1 = i0 + 1
    j1 = j0 + 1

    di = np.clip(lat_frac - i0, 0.0, 1.0)
    dj = np.clip(lon_frac - j0, 0.0, 1.0)

    top = (1.0 - dj) * field[i0, j0] + dj * field[i0, j1]
    bot = (1.0 - dj) * field[i1, j0] + dj * field[i1, j1]
    regridded = (1.0 - di) * top + di * bot

    # Clamp bounds outside source domain to 0
    min_lat, max_lat = src_grid.lat_edges
    min_lon, max_lon = src_grid.lon_edges
    in_lat = (target_lats[:, None] >= min_lat) & (target_lats[:, None] <= max_lat)
    in_lon = (target_lons[None, :] >= min_lon) & (target_lons[None, :] <= max_lon)
    in_bounds = in_lat & in_lon
    regridded = np.where(in_bounds, regridded, 0.0)

    return np.clip(regridded, 0.0, 500.0).astype(np.float32)


def parse_imerg_hdf5(
    path: Path,
    target_grid: GridSpec | None = None,
) -> tuple[ObsFrame, np.ndarray, GridSpec]:
    """Parse an IMERG HDF5 file and return calibrated ObsFrame and regridded array."""
    raw_win, raw_grid, slot = ImergProvider._parse_india(path)
    grid = target_grid or raw_grid
    if grid != raw_grid:
        data = regrid_imerg(raw_win, raw_grid, grid)
    else:
        data = raw_win

    gm = GridMeta(
        name=grid.name,
        lat0=grid.lat0,
        lon0=grid.lon0,
        dlat=grid.dlat,
        dlon=grid.dlon,
        nlat=grid.nlat,
        nlon=grid.nlon,
        geolocation="exact",
    )
    meta = ObsFrameMeta(
        source="imerg_earthdata",
        modality=Modality.SURFACE,
        variable="precipitation",
        units="mm/hr",
        time=slot,
        grid=gm,
        mode=DataMode.LIVE,
        quality=QualityInfo(status=QualityStatus.OK),
        note=f"IMERG V07 Early regridded to {grid.name} ({data.shape[0]}x{data.shape[1]})",
    )
    frame = ObsFrame(meta, field=data)
    return frame, data, grid

