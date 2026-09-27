"""Canonical schemas. Every observation, forecast, alert and health object in the
system flows through these typed models so that honesty fields (mode, quality,
fallback rung, provenance) cannot be silently dropped."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class DataMode(str, Enum):
    LIVE = "LIVE"                # verified fresh data from a real source
    REPLAY = "REPLAY"            # real historical data, replayed
    SIMULATION = "SIMULATION"    # synthetic data, generated deterministically
    UNAVAILABLE = "UNAVAILABLE"  # no data; never silently substituted


class Modality(str, Enum):
    RADAR = "radar"
    SATELLITE = "satellite"
    LIGHTNING = "lightning"
    MODEL = "model"
    SURFACE = "surface"


class QualityStatus(str, Enum):
    OK = "OK"
    SUSPECT = "SUSPECT"
    BAD = "BAD"
    MISSING = "MISSING"


class FallbackRung(str, Enum):
    FULL_FUSION = "FULL_FUSION"
    REDUCED_MODALITY = "REDUCED_MODALITY"
    PHYSICS_BASELINE = "PHYSICS_BASELINE"
    PERSISTENCE = "PERSISTENCE"
    CLIMATOLOGY = "CLIMATOLOGY"


class QualityInfo(BaseModel):
    status: QualityStatus = QualityStatus.OK
    missing_fraction: float = 0.0
    stale: bool = False
    message: str = ""


class GridMeta(BaseModel):
    name: str
    lat0: float
    lon0: float
    dlat: float
    dlon: float
    nlat: int
    nlon: int
    geolocation: Literal["exact", "approximate"] = "exact"


class ObsFrameMeta(BaseModel):
    """Metadata for one observation frame. Array data travels out-of-band (npz)."""

    source: str
    modality: Modality
    variable: str
    units: str
    time: datetime
    grid: GridMeta
    quality: QualityInfo = Field(default_factory=QualityInfo)
    mode: DataMode
    note: str = ""


class ObsFrame:
    """In-memory observation frame: metadata + optional 2-D field or point list."""

    __slots__ = ("meta", "field", "points")

    def __init__(
        self,
        meta: ObsFrameMeta,
        field: np.ndarray | None = None,
        points: np.ndarray | None = None,
    ) -> None:
        if field is None and points is None:
            raise ValueError("ObsFrame needs a 2-D field or a point array")
        if field is not None and field.shape != (meta.grid.nlat, meta.grid.nlon):
            raise ValueError(
                f"field shape {field.shape} does not match grid {(meta.grid.nlat, meta.grid.nlon)}"
            )
        self.meta = meta
        self.field = field
        self.points = points  # (N, 3): lat, lon, value

    def with_meta(self, **updates: Any) -> "ObsFrame":
        m = self.meta.model_copy(update=updates)
        return ObsFrame(m, self.field, self.points)


class Cell(BaseModel):
    id: str
    time: datetime
    centroid_lat: float
    centroid_lon: float
    bbox: list[float] = Field(description="minlon, minlat, maxlon, maxlat")
    area_px: int
    max_intensity: float
    mean_intensity: float
    track_age_steps: int = 0
    motion_dlat: float = 0.0   # deg per cycle
    motion_dlon: float = 0.0
    flash_count_history: int = 0
    intensity_units: str = "raw"
    velocity_kmh: float = 0.0
    heading_deg: float = 0.0
    projected_track: list[list[float]] = Field(default_factory=list)  # [[lon, lat], ...]
    uncertainty_cone: list[list[float]] = Field(default_factory=list) # polygon [[lon, lat], ...]
    dbz_max: float = 0.0
    core_area_km2: float = 0.0


class CICandidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    centroid_lat: float
    centroid_lon: float
    bbox: list[float]  # [min_lon, min_lat, max_lon, max_lat]
    cooling_rate_k_per_15m: float
    ir_brightness_temp_k: float
    ir_wv_diff_k: float
    p_initiation: float
    estimated_lead_min: int = 30  # typical lead time to first flash: 15-45 min
    area_km2: float = 0.0
    polygon: list[list[float]] = Field(default_factory=list)  # [[lon, lat], ...]


class ForecastStep(BaseModel):
    valid_time: datetime
    lead_minutes: int
    p_flash_max: float
    risk_band: str
    field_ref: str = ""          # path/URL of rendered field artifact (PNG/npz)
    uncertainty_p_mean: float = 0.0
    cells: list[Cell] = Field(default_factory=list)


class Forecast(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_id: str = ""                # inference run this forecast belongs to
    event_id: str
    issued_at: datetime = Field(default_factory=utcnow)
    replay_time: datetime
    mode: DataMode
    fallback_rung: FallbackRung
    model_version: str
    grid: GridMeta | None = None
    modalities_used: list[Modality]
    data_quality: dict[str, str] = Field(default_factory=dict)  # modality -> status
    steps: list[ForecastStep] = Field(default_factory=list)
    confidence: float = 0.0      # 0..1 overall confidence for this cycle (documented heuristic)
    notes: list[str] = Field(default_factory=list)
    ci_candidates: list[CICandidate] = Field(default_factory=list)


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_id: str = ""
    event_id: str
    issued_at: datetime = Field(default_factory=utcnow)
    valid_from: datetime
    valid_until: datetime
    severity: Literal["ADVISORY", "WATCH", "WARNING"]
    hazard: Literal["LIGHTNING", "THUNDERSTORM"]
    region_name: str
    bbox: list[float]
    probability: float
    confidence: float
    lead_minutes: int
    preset: str
    reason: str
    contributing_signals: dict[str, float] = Field(default_factory=dict)
    model_version: str
    mode: DataMode
    data_quality: dict[str, str] = Field(default_factory=dict)
    recommended_action: str = ""
    affected_districts: list[str] = Field(default_factory=list)
    affected_blocks: list[str] = Field(default_factory=list)
    population_exposed: int = 0
    imd_stage: Literal["GREEN", "YELLOW", "ORANGE", "RED"] = "YELLOW"
    cap_severity: Literal["Minor", "Moderate", "Severe", "Extreme"] = "Moderate"
    urgency: Literal["Immediate", "Expected", "Future", "Past", "Unknown"] = "Expected"
    certainty: Literal["Observed", "Likely", "Possible", "Unlikely", "Unknown"] = "Likely"
    headline: str = ""
    is_update: bool = False
    supersedes_id: str = ""

    def to_cap_xml(self) -> str:
        from .cap import build_cap_12_xml
        return build_cap_12_xml(self)

    def to_cap_json(self) -> dict:
        from .cap import build_cap_12_json
        return build_cap_12_json(self)


class DataHealth(BaseModel):
    source: str
    modality: Modality
    status: DataMode
    last_success: datetime | None = None
    latency_s: float | None = None
    message: str = ""


class ModelHealth(BaseModel):
    active_model: str
    model_version: str
    trained_on: str               # dataset provenance string
    inference_latency_ms: float | None = None
    errors_last_hour: int = 0
    fallback_frequency: dict[str, int] = Field(default_factory=dict)
    message: str = ""


class InferenceRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    event_id: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    cycles: int = 0
    forecasts: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class Event(BaseModel):
    id: str
    title: str
    mode: DataMode
    domain: str                   # grid name / domain description
    time_start: datetime
    time_end: datetime
    source: str
    provenance: dict[str, Any] = Field(default_factory=dict)
