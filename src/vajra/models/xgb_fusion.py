"""Late-fusion ML model (ProbSevere-pattern): XGBoost on per-cell features.

This is the MVP model selected by the research (MASTER.md §7, Decision D5):
- object-based (per storm cell), not pixel-based;
- late fusion: per-modality features join in one feature row — modular, ablatable,
  and naturally degradable (missing modality -> missing feature -> XGBoost NaN);
- calibrated with isotonic PAVA before probabilities are exposed.

Training data provenance is recorded in the artifact and surfaced via ModelHealth.
Training (synthetic sandbox vs real SEVIR events) is kept separate from inference
per the brief; see scripts/train_model.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..features import FEATURE_NAMES
from ..providers.gfs import apply_thermodynamic_gating
from .base import CycleContext, ModelOutput, NowcastModel
from .calibration import apply_isotonic


class XGBFusionModel(NowcastModel):
    name = "xgb_late_fusion"

    def __init__(self, artifact_dir: Path, params: dict | None = None,
                 calibrator: dict | None = None):
        self.artifact_dir = Path(artifact_dir)
        self.params = params or {}
        self._booster = None
        self._calibrator = calibrator
        self._meta: dict = {}

    # -- artifact management --------------------------------------------------
    @property
    def model_version(self) -> str:
        return self._meta.get("model_version", "unloaded")

    def load(self) -> None:
        import xgboost as xgb
        mpath = self.artifact_dir / "model.json"
        cpath = self.artifact_dir / "calibration.json"
        jpath = self.artifact_dir / "meta.json"
        if not mpath.exists():
            raise FileNotFoundError(f"model artifact missing: {mpath}")
        booster = xgb.Booster()
        booster.load_model(str(mpath))
        self._booster = booster
        self._calibrator = json.loads(cpath.read_text()) if cpath.exists() else None
        self._meta = json.loads(jpath.read_text()) if jpath.exists() else {}
        self.version = self._meta.get("model_version", "unknown")
        self.trained_on = self._meta.get("trained_on", "unknown")

    def save(self, model_version: str, trained_on: str, train_metrics: dict) -> None:
        import xgboost as xgb
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        assert self._booster is not None
        self._booster.save_model(str(self.artifact_dir / "model.json"))
        if self._calibrator is not None:
            (self.artifact_dir / "calibration.json").write_text(json.dumps(self._calibrator))
        meta = {
            "model_version": model_version,
            "trained_on": trained_on,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "features": FEATURE_NAMES,
            "xgb_params": {k: self._booster.attr(k) for k in []} or self.params,
            "train_metrics": train_metrics,
        }
        (self.artifact_dir / "meta.json").write_text(json.dumps(meta, indent=1))

    # -- inference -------------------------------------------------------------
    def available(self, ctx: CycleContext) -> bool:
        return self._booster is not None and ctx.features is not None and len(ctx.features) > 0

    def _feature_matrix(self, ctx: CycleContext) -> tuple[np.ndarray, list[str]]:
        df = ctx.features
        feat_cols = self._meta.get("features", FEATURE_NAMES)
        missing = [c for c in feat_cols if c not in df.columns]
        if missing:
            raise ValueError(f"feature contract violated; missing {missing}")
        return df[feat_cols].to_numpy(dtype=np.float64), list(df["_cell_id"])

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        assert self._booster is not None
        import xgboost as xgb
        feat_cols = self._meta.get("features", FEATURE_NAMES)
        X, cell_ids = self._feature_matrix(ctx)
        dmat = xgb.DMatrix(X, feature_names=feat_cols)
        raw = self._booster.predict(dmat)
        p = apply_isotonic(self._calibrator, raw) if self._calibrator else np.clip(raw, 0, 1)

        p_dict = dict(zip(cell_ids, map(float, p)))
        # Apply thermodynamic gating when environmental features are present in CycleContext
        if ctx.features is not None and len(ctx.features):
            df = ctx.features
            for cid in cell_ids:
                crow = df[df["_cell_id"] == cid]
                if not crow.empty:
                    cape = crow.get("cape_jkg", crow.get("env_cape", pd.Series([np.nan]))).values[0]
                    cin = crow.get("cin_jkg", pd.Series([np.nan])).values[0]
                    shear = crow.get("shear_0_6km_ms", crow.get("env_shear", pd.Series([np.nan]))).values[0]
                    if np.isfinite(cape) or np.isfinite(cin):
                        p_dict[cid] = apply_thermodynamic_gating(p_dict[cid], cape=cape, cin=cin, shear=shear)

        return ModelOutput(p_cell=p_dict,
                           background_p=self._meta.get("background_p", 0.0),
                           notes=[f"xgb late fusion v{self.model_version} lead={lead_minutes}min"])

    # -- training (used by scripts/train_model.py, never at inference time) -----
    def fit(self, X: np.ndarray, y: np.ndarray, params: dict) -> dict:
        import xgboost as xgb
        dtrain = xgb.DMatrix(X, label=y, feature_names=FEATURE_NAMES)
        self.params = params
        self._booster = xgb.train(params, dtrain, num_boost_round=params.get("n_estimators", 300))
        return {}
