"""Configuration loading: YAML defaults + VAJRA_* environment overrides.

No secrets ever live in YAML; anything credential-shaped comes from the environment
(e.g. VAJRA_MOSDAC__USERNAME) or from a git-ignored .env-style file loaded by the
deployer. See docs/DATA.md for the credential inventory.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"


@dataclass
class GridConfig:
    name: str = "india_0p1"
    lat_min: float = 6.0
    lat_max: float = 38.0
    lon_min: float = 66.0
    lon_max: float = 98.0
    step_deg: float = 0.1
    sevir_center_lat: float = 37.5
    sevir_center_lon: float = -97.5
    sevir_km_per_px: float = 2.0
    sevir_n: int = 384


@dataclass
class PathsConfig:
    data_root: str = "data"
    models_dir: str = "models"
    store_dir: str = "store"
    web_dist: str = "web"

    def resolve(self, base: Path) -> dict[str, Path]:
        return {k: (base / v) for k, v in self.__dict__.items()}


@dataclass
class CellsConfig:
    vil_threshold: float = 74.0
    min_area_px: int = 12
    max_track_speed_km_h: float = 180.0
    flash_radius_km: float = 12.0


@dataclass
class ReplayConfig:
    lead_minutes: list[int] = field(default_factory=lambda: [30, 60])
    cycle_minutes: int = 10
    history_minutes: int = 60


@dataclass
class XGBConfig:
    n_estimators: int = 300
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.9
    colsample_bytree: float = 0.9
    min_child_weight: int = 5


@dataclass
class ModelConfig:
    xgb: XGBConfig = field(default_factory=XGBConfig)
    calibration_bins: int = 10


@dataclass
class RiskBand:
    name: str
    max: float


@dataclass
class RiskConfig:
    bands: list[RiskBand] = field(
        default_factory=lambda: [
            RiskBand("LOW", 0.20),
            RiskBand("MODERATE", 0.40),
            RiskBand("ELEVATED", 0.60),
            RiskBand("HIGH", 0.80),
            RiskBand("SEVERE", 1.01),
        ]
    )


@dataclass
class AlertPreset:
    p_threshold: float
    min_confidence: float


@dataclass
class AlertsConfig:
    presets: dict[str, AlertPreset] = field(
        default_factory=lambda: {
            "protective": AlertPreset(0.30, 0.20),
            "operational": AlertPreset(0.50, 0.35),
        }
    )
    validity_minutes: int = 60
    suppression_minutes: int = 30


@dataclass
class BasemapsConfig:
    """Map basemap provider settings. Keys are public tile-access tokens; they still
    come from the environment (VAJRA_BASEMAPS__CARTO_KEY) or git-ignored .env, never
    from YAML or source, and are served to the frontend only via /api/v1/config."""

    carto_key: str = ""


@dataclass
class ApiConfig:
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8000"]
    )


@dataclass
class EarthdataConfig:
    """NASA Earthdata Login credentials. Read from env/.env only — never hardcoded."""

    username: str = ""
    password: str = ""
    host: str = "urs.earthdata.nasa.gov"

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)


@dataclass
class MosdacConfig:
    """ISRO MOSDAC credentials for INSAT-3D/3DR/3DS. Read from env/.env only."""

    username: str = ""
    password: str = ""
    host: str = "www.mosdac.gov.in"

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)


@dataclass
class Settings:
    grid: GridConfig = field(default_factory=GridConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    cells: CellsConfig = field(default_factory=CellsConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    basemaps: BasemapsConfig = field(default_factory=BasemapsConfig)
    earthdata: EarthdataConfig = field(default_factory=EarthdataConfig)
    mosdac: MosdacConfig = field(default_factory=MosdacConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    config_path: Path | None = None

    @property
    def data_root(self) -> Path:
        return (REPO_ROOT / self.paths.data_root).resolve()

    @property
    def models_dir(self) -> Path:
        return (REPO_ROOT / self.paths.models_dir).resolve()

    @property
    def store_dir(self) -> Path:
        return (REPO_ROOT / self.paths.store_dir).resolve()

    @property
    def web_dist(self) -> Path:
        return (REPO_ROOT / self.paths.web_dist).resolve()


def _deep_set(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split("__")
    node = d
    for p in parts[:-1]:
        node = node.setdefault(p.lower(), {})
    node[parts[-1].lower()] = value


def _apply_overrides(raw: dict, section: str, target: Any) -> Any:
    """Build a dataclass instance from the raw dict merged with VAJRA_* env vars."""
    prefix = f"VAJRA_{section.upper()}__"
    overrides = {k[len(prefix):]: v for k, v in os.environ.items() if k.startswith(prefix)}
    data = dict(raw.get(section, {}) or {})
    for k, v in overrides.items():
        data[k.lower()] = v
    kwargs: dict[str, Any] = {}
    for f in target.__dataclass_fields__.values():  # type: ignore[attr-defined]
        if f.name not in data:
            continue
        val = data[f.name]
        ftype = f.type if isinstance(f.type, str) else type(f.type)
        if f.name == "presets" and isinstance(val, dict):
            val = {k: AlertPreset(**v) for k, v in val.items()}
        elif f.name == "bands" and isinstance(val, list):
            val = [RiskBand(**b) for b in val]
        elif f.name == "xgb" and isinstance(val, dict):
            val = XGBConfig(**val)
        kwargs[f.name] = val
    return target(**kwargs)


def load_settings(config_path: Path | None = None) -> Settings:
    # Git-ignored .env (if present) feeds VAJRA_* overrides; python-dotenv ships with
    # uvicorn[standard], but loading must stay optional for bare environments.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass
    path = config_path or DEFAULT_CONFIG
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = copy.deepcopy(raw)
    s = Settings(config_path=path)
    s.grid = _apply_overrides(raw, "grid", GridConfig)
    s.paths = _apply_overrides(raw, "paths", PathsConfig)
    s.cells = _apply_overrides(raw, "cells", CellsConfig)
    s.replay = _apply_overrides(raw, "replay", ReplayConfig)
    s.model = _apply_overrides(raw, "model", ModelConfig)
    s.risk = _apply_overrides(raw, "risk", RiskConfig)
    s.alerts = _apply_overrides(raw, "alerts", AlertsConfig)
    s.basemaps = _apply_overrides(raw, "basemaps", BasemapsConfig)
    s.earthdata = _apply_overrides(raw, "earthdata", EarthdataConfig)
    # Conventional NASA env-var names also work (e.g. from .env or the shell).
    if not s.earthdata.username:
        s.earthdata.username = os.environ.get("EARTHDATA_USERNAME", "")
    if not s.earthdata.password:
        s.earthdata.password = os.environ.get("EARTHDATA_PASSWORD", "")
    s.mosdac = _apply_overrides(raw, "mosdac", MosdacConfig)
    if not s.mosdac.username:
        s.mosdac.username = os.environ.get("MOSDAC_USERNAME", "")
    if not s.mosdac.password:
        s.mosdac.password = os.environ.get("MOSDAC_PASSWORD", "")
    s.api = _apply_overrides(raw, "api", ApiConfig)
    return s
