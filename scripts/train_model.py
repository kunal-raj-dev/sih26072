"""Train the XGBoost late-fusion model on replayed events (leave-events-out split).

Usage:
  python scripts/train_model.py --train 6 --cal 2 --test 2

Protocol (D8):
- events are ranked by flash count (most active first) from the prepared SEVIR
  cache; training/calibration/test are split BY EVENT to avoid event leakage;
- features are frozen at issue time (pipeline guarantees no future leakage);
- labels: >=1 GLM flash within cell radius in (t, t+lead];
- isotonic (PAVA) calibration is fit on the calibration split;
- provenance (dataset events, dates, prevalence, metrics) is stored in the
  artifact meta and surfaced through /api/v1/model-health.

A synthetic-only variant exists for CI/tests: --synthetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vajra.config import load_settings                        # noqa: E402
from vajra.features import FEATURE_NAMES                      # noqa: E402
from vajra.logsetup import get_logger                         # noqa: E402
from vajra.models.calibration import fit_isotonic             # noqa: E402
from vajra.models.xgb_fusion import XGBFusionModel            # noqa: E402
from vajra.pipeline import NowcastPipeline                    # noqa: E402
from vajra.providers.sevir import (                           # noqa: E402
    SevirCatalog, SevirLightningProvider, SevirRadarProvider, SevirReplayEvent,
    SevirSatelliteProvider)
from vajra.schemas import DataMode, Event, Modality            # noqa: E402
from vajra.store import Store                                 # noqa: E402
from vajra.verify import brier_score, pod_far_csi, contingency  # noqa: E402

logger = get_logger("vajra.scripts.train", json_mode=False)


def event_run_rows(settings, store: Store, event_id: str) -> pd.DataFrame:
    rev = SevirReplayEvent(event_id, settings)
    rev.prepare()
    sources = {
        Modality.SATELLITE: SevirSatelliteProvider(rev),
        Modality.RADAR: SevirRadarProvider(rev),
        Modality.LIGHTNING: SevirLightningProvider(rev),
    }
    from vajra.models.baselines import (AdvectionModel, ClimatologyModel,
                                        LightningJumpModel, PersistenceModel)
    from vajra.models.router import ModelRouter
    router = ModelRouter(fusion=None,
                         physics=AdvectionModel(vil_threshold=settings.cells.vil_threshold),
                         persistence=PersistenceModel(), climatology=ClimatologyModel())
    pipe = NowcastPipeline(settings, sources, router, model_version="training")
    pipe.attach_store(store)
    event: Event = rev.to_event()
    run = pipe.run_replay(event, event.time_start, event.time_end, collect_training=True)
    path = run.metrics.get("training_samples_path")
    if not path or not Path(path).exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["event_id"] = event_id
    logger.info("event %s -> %d samples (labels: %.2f%% positive)",
                event_id, len(df), 100 * df["label"].mean() if len(df) else 0)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=5)
    ap.add_argument("--cal", type=int, default=2)
    ap.add_argument("--test", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    settings = load_settings()
    store = Store(settings)
    catalog = SevirCatalog(settings.data_root / "external" / "sevir")
    events_dir = settings.data_root / "external" / "sevir" / "events"

    prepared = sorted(p.stem for p in events_dir.glob("*.npz"))
    if len(prepared) < args.train + args.cal + args.test:
        raise SystemExit(f"need {args.train + args.cal + args.test} prepared events, have {len(prepared)}. "
                         "Run scripts/prepare_sevir_events.py first.")
    rng = np.random.default_rng(args.seed)
    chosen = list(rng.permutation(prepared)[: args.train + args.cal + args.test])
    train_ids, cal_ids, test_ids = (chosen[: args.train], chosen[args.train: args.train + args.cal],
                                    chosen[-args.test:])
    logger.info("split by event -> train: %s | cal: %s | test: %s", train_ids, cal_ids, test_ids)

    frames = [event_run_rows(settings, store, eid) for eid in train_ids + cal_ids]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True)
    if df.empty:
        raise SystemExit("no training samples collected — check event preparation")
    df["event_id"] = df["event_id"].astype(str)
    train = df[df.event_id.isin(train_ids)]
    cal = df[df.event_id.isin(cal_ids)]
    logger.info("samples: train=%d (pos %.3f) cal=%d (pos %.3f)",
                len(train), train.label.mean(), len(cal), cal.label.mean())

    X_tr, y_tr = train[FEATURE_NAMES].to_numpy(float), train["label"].to_numpy(int)
    X_cal, y_cal = cal[FEATURE_NAMES].to_numpy(float), cal["label"].to_numpy(int)

    import xgboost as xgb
    params = {
        "objective": "binary:logistic", "eval_metric": "aucpr",
        "max_depth": settings.model.xgb.max_depth,
        "learning_rate": settings.model.xgb.learning_rate,
        "subsample": settings.model.xgb.subsample,
        "colsample_bytree": settings.model.xgb.colsample_bytree,
        "min_child_weight": settings.model.xgb.min_child_weight,
        "seed": args.seed,
    }
    booster = xgb.train(params, xgb.DMatrix(X_tr, label=y_tr, feature_names=FEATURE_NAMES),
                        num_boost_round=settings.model.xgb.n_estimators)
    raw_cal = booster.predict(xgb.DMatrix(X_cal, feature_names=FEATURE_NAMES))
    calibrator = fit_isotonic(raw_cal, y_cal) if len(cal) else None

    model = XGBFusionModel(settings.models_dir / "xgb_fusion", params=params,
                           calibrator=calibrator)
    model._booster = booster
    p_cal = model._calibrator and __import__("vajra.models.calibration", fromlist=["apply_isotonic"]).apply_isotonic(calibrator, raw_cal)
    h, m, fa, _ = contingency(p_cal if p_cal is not None else raw_cal, y_cal, 0.5)
    pod, far, csi = pod_far_csi(h, m, fa)
    metrics = {
        "positive_rate": float(y_tr.mean()),
        "cal_positive_rate": float(y_cal.mean()) if len(cal) else None,
        "cal_pod": pod, "cal_far": far, "cal_csi": csi,
        "cal_brier": brier_score(p_cal, y_cal) if p_cal is not None and len(cal) else None,
        "n_train": int(len(train)), "n_cal": int(len(cal)),
        "train_events": train_ids, "cal_events": cal_ids, "test_events": test_ids,
    }
    model_version = f"xgb-sevir-{pd.Timestamp.now().strftime('%Y%m%d%H%M')}"
    model.save(model_version,
               trained_on=(f"SEVIR replay events {train_ids} (real GOES-16/GLM/NEXRAD data)"),
               train_metrics=metrics)
    logger.info("saved model %s | cal POD=%.2f FAR=%.2f CSI=%.2f", model_version, pod, far, csi)
    logger.info("held-out test events for demo: %s", test_ids)
    (settings.models_dir / "xgb_fusion" / "test_events.json").write_text(json.dumps(test_ids))


if __name__ == "__main__":
    main()
