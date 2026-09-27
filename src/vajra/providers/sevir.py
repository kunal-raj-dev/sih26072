"""SEVIR historical replay provider (REAL data, mode=REPLAY).

Data: Storm Event ImagE Record — GOES-16 ABI + GLM lightning + NEXRAD-derived VIL
(MIT Lincoln Lab, AWS Open Data, "no restrictions on use"). Verified 2026-09-27.

Access strategy (verified empirically):
- CATALOG.csv (33.8 MB) maps every event to its source h5 file, row index,
  per-type lat/lon corners and projection. Event ids are the `id` column.
- Grid files (VIL 12-17 GB) are NEVER fully downloaded: h5py + s3fs perform
  HTTP range reads of single event slabs (~14 MB for VIL 384x384x49).
- Lightning monthlies are small (3-33 MB) and cached fully.

All extracted events are cached under data/external/sevir/events/<event_id>.npz
so replays run offline. Provenance travels in Event.provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import s3fs

from ..config import Settings
from ..grid import GridSpec
from ..schemas import (
    DataHealth,
    DataMode,
    Event,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
    GridMeta,
)
from .base import AtmosphericDataProvider
from ..logsetup import get_logger, log_event

logger = get_logger("vajra.providers.sevir")

S3_BUCKET = "sevir"
REGION = "us-east-1"
CATALOG_KEY = "CATALOG.csv"
from ..qc import sevir_ir_to_kelvin

# SEVIR VIL is stored as uint8 on the raw SEVIR scale (0-255). Published SEVIR
# nowcasting work uses raw-scale thresholds (16/74/133/...); we follow that
# convention and never claim physical VIL units.
VIL_UNITS = "SEVIR VIL raw scale (0-255)"
IR107_UNITS = "Kelvin (calibrated from SEVIR raw scale)"


def _fs() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        anon=True,
        client_kwargs={"region_name": REGION},
        config_kwargs={"read_timeout": 90, "connect_timeout": 15, "retries": {"max_attempts": 3}},
        default_fill_cache=False,
    )


@dataclass
class SevirEventBundle:
    event_id: str
    time_center: datetime
    minute_offsets: list[int]
    vil: np.ndarray          # (T, 384, 384) uint8
    ir107: np.ndarray        # (T2, 192, 192) uint8  (T2 may differ from T)
    flashes: np.ndarray      # (N, 5) float32: [t_offset_s?, lat, lon, a, b]
    grids: dict[str, GridSpec]
    provenance: dict

    @property
    def frame_times(self) -> list[datetime]:
        return [self.time_center + timedelta(minutes=m) for m in self.minute_offsets]


class SevirCatalog:
    def __init__(self, cache_dir: Path):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path = self.cache / "CATALOG.csv"
        if not self.path.exists():
            log_event(logger, 20, "downloading SEVIR catalog", size_mb=33.8)
            fs = _fs()
            fs.get(f"{S3_BUCKET}/{CATALOG_KEY}", str(self.path))
        self.df = pd.read_csv(self.path, low_memory=False, dtype=str)
        self.df["file_index_int"] = pd.to_numeric(self.df["file_index"], errors="coerce").astype("Int64")

    def rows_for(self, event_id: str) -> pd.DataFrame:
        return self.df[self.df["id"] == event_id]

    def event_ids_with_modalities(self, year: str, month_prefix: str,
                                  types: tuple[str, ...] = ("vil", "ir107", "lght")) -> list[str]:
        """Event ids present in the catalog for all requested types in a period.

        lght files are monthly ALLEVENTS; year match alone is enough for them.
        """
        d = self.df
        sets = []
        for t in types:
            m = (d["img_type"] == t) & (d["file_name"].str.contains(year, na=False))
            if t != "lght" and month_prefix:
                m &= d["file_name"].str.contains(month_prefix, na=False)
            sets.append(set(d.loc[m, "id"]))
        return sorted(set.intersection(*sets)) if sets else []


class SevirReplayEvent:
    """One prepared SEVIR event with cached arrays and provider views."""

    def __init__(self, event_id: str, settings: Settings, catalog: SevirCatalog | None = None):
        self.event_id = event_id
        self.settings = settings
        self.catalog = catalog or SevirCatalog(settings.data_root / "external" / "sevir")
        self.cache_dir = settings.data_root / "external" / "sevir" / "events"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bundle: SevirEventBundle | None = None

    # ---- preparation (network) --------------------------------------------
    def prepare(self) -> SevirEventBundle:
        npz_path = self.cache_dir / f"{self.event_id}.npz"
        meta_path = self.cache_dir / f"{self.event_id}.json"
        if npz_path.exists() and meta_path.exists():
            return self._load_cached(npz_path, meta_path)

        rows = self.catalog.rows_for(self.event_id)
        if rows.empty:
            raise ValueError(f"event {self.event_id} not in catalog")
        fs = _fs()

        def slab(img_type: str) -> tuple[np.ndarray, pd.Series]:
            r = rows[rows.img_type == img_type].iloc[0]
            s3key = f"{S3_BUCKET}/data/{r['file_name']}"
            log_event(logger, 20, "range-reading SEVIR slab", img_type=img_type, key=s3key,
                      file_index=int(r["file_index_int"]))
            with fs.open(s3key, "rb") as f:
                with h5py.File(f, "r") as h:
                    ds_keys = [k for k in h.keys() if h[k].dtype.kind in "fiu"]
                    ds = h[ds_keys[0]]
                    slab = ds[int(r["file_index_int"])]
            return np.asarray(slab), r

        vil, r_vil = slab("vil")
        ir107, r_ir = slab("ir107")
        # h5 slabs are (H, W, T); the system expects (T, H, W).
        vil = np.ascontiguousarray(vil.transpose(2, 0, 1))
        ir107 = np.ascontiguousarray(ir107.transpose(2, 0, 1))
        flashes = self._load_flashes(fs, rows)

        time_center = pd.Timestamp(rows.iloc[0]["time_utc"]).to_pydatetime().replace(tzinfo=timezone.utc)
        offsets = [int(x) for x in rows.iloc[0]["minute_offsets"].split(":")]

        grids = {
            "vil": self._grid_from_row(r_vil),
            "ir107": self._grid_from_row(r_ir),
        }
        prov = {
            "source": "SEVIR (MIT Lincoln Lab) via AWS Open Data, s3://sevir",
            "license": "No restrictions on use (AWS Open Data registry)",
            "accessed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "catalog_row_time_utc": rows.iloc[0]["time_utc"],
            "vil_file": rows[rows.img_type == "vil"].iloc[0]["file_name"],
            "ir107_file": rows[rows.img_type == "ir107"].iloc[0]["file_name"],
            "geolocation": "per-event laea corners from catalog; linear lat/lon interpolation (<0.1% local error)",
        }
        np.savez_compressed(npz_path, vil=vil, ir107=ir107, flashes=flashes)
        meta = {
            "event_id": self.event_id,
            "time_center": time_center.isoformat(),
            "minute_offsets": offsets,
            "grids": {k: v.__dict__ for k, v in grids.items()},
            "provenance": prov,
        }
        meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        self.bundle = SevirEventBundle(self.event_id, time_center, offsets,
                                       vil, ir107, flashes, grids, prov)
        return self.bundle

    def _load_flashes(self, fs: s3fs.S3FileSystem, rows: pd.DataFrame) -> np.ndarray:
        r = rows[rows.img_type == "lght"].iloc[0]
        local = self.cache_dir.parent / Path(r["file_name"]).name
        if not local.exists():
            fs.get(f"{S3_BUCKET}/data/{r['file_name']}", str(local))
        with h5py.File(local, "r") as h:
            if self.event_id in h:
                return np.asarray(h[self.event_id], dtype=np.float32)
            log_event(logger, 30, "event has no flashes in lght file", event_id=self.event_id)
            return np.zeros((0, 5), dtype=np.float32)

    @staticmethod
    def _grid_from_row(r: pd.Series) -> GridSpec:
        """Catalog corners -> grid. Image row 0 is the NORTH edge (urcrnr), so
        latitude DESCENDS with row index — critical for flash/cell alignment."""
        nlat, nlon = int(r["size_y"]), int(r["size_x"])
        ll_lat, ll_lon = float(r["llcrnrlat"]), float(r["llcrnrlon"])
        ur_lat, ur_lon = float(r["urcrnrlat"]), float(r["urcrnrlon"])
        step_lat = (ur_lat - ll_lat) / nlat
        step_lon = (ur_lon - ll_lon) / nlon
        return GridSpec(name=f"sevir_{r['img_type']}", lat0=ur_lat - step_lat / 2,
                        lon0=ll_lon + step_lon / 2, dlat=-step_lat, dlon=step_lon,
                        nlat=nlat, nlon=nlon, geolocation="approximate")

    # ---- cached load --------------------------------------------------------
    def _load_cached(self, npz_path: Path, meta_path: Path) -> SevirEventBundle:
        z = np.load(npz_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        grids = {k: GridSpec(**v) for k, v in meta["grids"].items()}
        self.bundle = SevirEventBundle(
            event_id=meta["event_id"],
            time_center=datetime.fromisoformat(meta["time_center"]),
            minute_offsets=meta["minute_offsets"],
            vil=z["vil"], ir107=z["ir107"], flashes=z["flashes"],
            grids=grids, provenance=meta["provenance"],
        )
        return self.bundle

    # ---- provider views ------------------------------------------------------
    def to_event(self) -> Event:
        b = self.bundle
        assert b is not None, "call prepare() first"
        return Event(
            id=f"SEVIR_{self.event_id}",
            title=f"SEVIR replay {self.event_id} @ {b.time_center:%Y-%m-%d %H:%M} UTC",
            mode=DataMode.REPLAY,
            domain=b.grids["vil"].name,
            time_start=b.frame_times[0],
            time_end=b.frame_times[-1],
            source="SEVIR/AWS Open Data",
            provenance=b.provenance,
        )

    def satellite_frames(self, t: datetime, minutes: int) -> list[ObsFrame]:
        return self._field_frames(t, minutes, "ir107", Modality.SATELLITE, "bt_ir107", IR107_UNITS)

    def radar_frames(self, t: datetime, minutes: int) -> list[ObsFrame]:
        return self._field_frames(t, minutes, "vil", Modality.RADAR, "vil", VIL_UNITS)

    def _field_frames(self, t: datetime, minutes: int, kind: str,
                      mod: Modality, var: str, units: str) -> list[ObsFrame]:
        b = self.bundle
        assert b is not None
        g = b.grids[kind]
        gm = GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                      nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)
        arr = b.vil if kind == "vil" else b.ir107
        out: list[ObsFrame] = []
        for k, m in enumerate(b.minute_offsets):
            ft = b.time_center + timedelta(minutes=m)
            if ft > t or ft < t - timedelta(minutes=minutes):
                continue
            meta = ObsFrameMeta(source="sevir", modality=mod, variable=var, units=units,
                                time=ft, grid=gm, mode=DataMode.REPLAY,
                                quality=QualityInfo(status=QualityStatus.OK),
                                note=f"SEVIR event {self.event_id} frame {k}")
            field_val = sevir_ir_to_kelvin(arr[k]) if kind == "ir107" else arr[k].astype(np.float32)
            out.append(ObsFrame(meta, field=field_val))
        return out

    def lightning_frames(self, t: datetime, minutes: int) -> list[ObsFrame]:
        """One frame per window with points (N,4): lat, lon, energy, epoch_s."""
        b = self.bundle
        assert b is not None
        t0 = t - timedelta(minutes=minutes)
        # SEVIR lght col0 = seconds from the event window start (= center - 120 min).
        epoch0 = (b.time_center - timedelta(minutes=120)).timestamp()
        epoch_abs = epoch0 + b.flashes[:, 0]
        rel_min = (epoch_abs - b.time_center.timestamp()) / 60.0
        sel = (rel_min >= (t0 - b.time_center).total_seconds() / 60.0) & \
              (rel_min <= (t - b.time_center).total_seconds() / 60.0)
        pts = np.stack([b.flashes[sel, 1], b.flashes[sel, 2], b.flashes[sel, 3],
                        epoch_abs[sel]], axis=1) if sel.any() else np.zeros((0, 4), np.float32)
        g = b.grids["vil"]
        gm = GridMeta(name=g.name, lat0=g.lat0, lon0=g.lon0, dlat=g.dlat, dlon=g.dlon,
                      nlat=g.nlat, nlon=g.nlon, geolocation=g.geolocation)
        meta = ObsFrameMeta(source="sevir_glm", modality=Modality.LIGHTNING, variable="flash",
                            units="flash (lat,lon,energy,epoch_s)", time=t, grid=gm,
                            mode=DataMode.REPLAY, quality=QualityInfo(status=QualityStatus.OK),
                            note="GOES-16 GLM flashes, SEVIR processing")
        return [ObsFrame(meta, points=pts.astype(np.float32))]


def pick_event_with_most_flashes(catalog: SevirCatalog, events_dir: Path,
                                 lght_file: str = "lght/2019/SEVIR_LGHT_ALLEVENTS_2019_0301_0401.h5",
                                 top: int = 12) -> list[str]:
    """Rank candidate events in a cached lght file by flash count (verification-friendly)."""
    local = events_dir.parent / Path(lght_file).name
    with h5py.File(local, "r") as h:
        ids = [k for k in h.keys() if k != "id"]
        counts = sorted(((len(h[k]), k) for k in ids), reverse=True)
    cat = catalog.df
    out = []
    for n, eid in counts:
        rows = cat[cat["id"] == eid]
        if len(rows) and {"vil", "ir107", "lght"}.issubset(set(rows["img_type"])):
            out.append(eid)
        if len(out) >= top:
            break
    log_event(logger, 20, "ranked events by flash count", top=out[:5])
    return out


class _SevirBase:
    """Shared plumbing for SEVIR replay adapters (REAL historical data)."""

    def __init__(self, rev: SevirReplayEvent):
        self.rev = rev
        self.mode = DataMode.REPLAY

    def health(self) -> DataHealth:
        ok = self.rev.bundle is not None
        return DataHealth(source=f"sevir_{self.modality.value}", modality=self.modality,
                          status=DataMode.REPLAY if ok else DataMode.UNAVAILABLE,
                          last_success=self.rev.bundle.time_center if ok else None,
                          message=("real historical SEVIR event cached locally (REPLAY)"
                                   if ok else "event not prepared"))


class SevirRadarProvider(_SevirBase):
    """SEVIR NEXRAD-derived VIL — radar-structure proxy for replay."""

    name = "sevir_vil"
    modality = Modality.RADAR

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        if self.rev.bundle is None:
            return []
        return self.rev.radar_frames(t, minutes)


class SevirSatelliteProvider(_SevirBase):
    name = "sevir_ir107"
    modality = Modality.SATELLITE

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        if self.rev.bundle is None:
            return []
        return self.rev.satellite_frames(t, minutes)


class SevirLightningProvider(_SevirBase):
    name = "sevir_glm"
    modality = Modality.LIGHTNING

    def get_history(self, t: datetime, minutes: int) -> list[ObsFrame]:
        if self.rev.bundle is None:
            return []
        return self.rev.lightning_frames(t, minutes)
