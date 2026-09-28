"""Forecast/event store: SQLite metadata + npz/PNG artifacts on disk.

SQLite (stdlib) keeps the demo deployable with zero services; the schema mirrors
the entities the brief requires (events, runs, forecasts, alerts, health) and can
move to PostgreSQL/PostGIS later without touching callers — all access goes
through this module.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import Settings
from .schemas import Alert, DataHealth, Event, Forecast, InferenceRun

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, cycles INTEGER DEFAULT 0, metrics TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS forecasts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event_id TEXT NOT NULL,
  issued_at TEXT NOT NULL, replay_time TEXT NOT NULL, mode TEXT NOT NULL,
  rung TEXT NOT NULL, model_version TEXT NOT NULL, grid TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS forecast_fields (
  forecast_id TEXT NOT NULL, lead_minutes INTEGER NOT NULL,
  npz_path TEXT NOT NULL, png_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event_id TEXT NOT NULL,
  issued_at TEXT NOT NULL, severity TEXT NOT NULL, preset TEXT NOT NULL,
  region_name TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_health (
  ts TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verification (
  run_id TEXT PRIMARY KEY, metrics TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_forecasts_run ON forecasts(run_id);
CREATE INDEX IF NOT EXISTS idx_alerts_run ON alerts(run_id);
"""


class Store:
    def __init__(self, settings: Settings):
        self.dir = settings.store_dir
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.artifacts = self.dir / "artifacts"
        try:
            self.artifacts.mkdir(exist_ok=True)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.dir / "vajra.db", check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- events ---------------------------------------------------------------
    def put_event(self, event: Event) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO events (id, json, created_at) VALUES (?,?,?)",
                (event.id, event.model_dump_json(), datetime.utcnow().isoformat()))
            self._conn.commit()

    def get_event(self, event_id: str) -> Event | None:
        with self._lock:
            row = self._conn.execute("SELECT json FROM events WHERE id=?", (event_id,)).fetchone()
            return Event.model_validate_json(row["json"]) if row else None

    def list_events(self) -> list[Event]:
        with self._lock:
            rows = self._conn.execute("SELECT json FROM events ORDER BY created_at DESC").fetchall()
            return [Event.model_validate_json(r["json"]) for r in rows]

    # -- runs -------------------------------------------------------------------
    def put_run(self, run: InferenceRun) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (id, event_id, started_at, finished_at, cycles, metrics, mode) "
                "VALUES (?,?,?,?,?,?,?)",
                (run.id, run.event_id, run.started_at.isoformat(),
                 run.finished_at.isoformat() if run.finished_at else None,
                 run.cycles, json.dumps(run.metrics), ""))
            self._conn.commit()

    def get_run(self, run_id: str) -> InferenceRun | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            return InferenceRun(
                id=row["id"], event_id=row["event_id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                cycles=row["cycles"], metrics=json.loads(row["metrics"] or "{}"))

    def list_runs(self) -> list[InferenceRun]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
            runs = []
            for row in rows:
                try:
                    runs.append(InferenceRun(
                        id=row["id"], event_id=row["event_id"],
                        started_at=datetime.fromisoformat(row["started_at"]),
                        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                        cycles=row["cycles"], metrics=json.loads(row["metrics"] or "{}")))
                except Exception:
                    continue
            return runs

    # -- forecasts ---------------------------------------------------------------
    def put_forecast(self, forecast: Forecast, fields: dict[int, tuple[np.ndarray, bytes]],
                     obs_png: bytes | None = None,
                     uncertainty_png: bytes | None = None) -> None:
        """fields: lead -> (p_grid, png_bytes). obs_png: grayscale detection-field render."""
        fdir = self.artifacts / forecast.id
        try:
            fdir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if obs_png:
            (fdir / "obs.png").write_bytes(obs_png)
        if uncertainty_png:
            (fdir / "uncertainty.png").write_bytes(uncertainty_png)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO forecasts (id, run_id, event_id, issued_at, replay_time,"
                " mode, rung, model_version, grid, json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (forecast.id, forecast.run_id or forecast.id, forecast.event_id,
                 forecast.issued_at.isoformat(),
                 forecast.replay_time.isoformat(), forecast.mode.value, forecast.fallback_rung.value,
                 forecast.model_version,
                 forecast.grid.model_dump_json() if forecast.grid else "{}",
                 forecast.model_dump_json()))
            for lead, (grid, png) in fields.items():
                npz = fdir / f"p_grid_{lead}min.npz"
                pngp = fdir / f"p_{lead}min.png"
                np.savez_compressed(npz, p_grid=grid)
                pngp.write_bytes(png)
                self._conn.execute(
                    "INSERT OR REPLACE INTO forecast_fields (forecast_id, lead_minutes, npz_path, png_path)"
                    " VALUES (?,?,?,?)", (forecast.id, lead, str(npz), str(pngp)))
            self._conn.commit()

    def get_forecast(self, forecast_id: str) -> Forecast | None:
        with self._lock:
            row = self._conn.execute("SELECT json FROM forecasts WHERE id=?", (forecast_id,)).fetchone()
            return Forecast.model_validate_json(row["json"]) if row else None

    def list_forecasts(self, run_id: str | None = None, event_id: str | None = None) -> list[Forecast]:
        q = "SELECT json FROM forecasts"
        conds, args = [], []
        if run_id:
            conds.append("run_id=?"); args.append(run_id)
        if event_id:
            conds.append("event_id=?"); args.append(event_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY replay_time"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
            return [Forecast.model_validate_json(r["json"]) for r in rows]

    def get_field_paths(self, forecast_id: str, lead: int) -> tuple[Path, Path] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT npz_path, png_path FROM forecast_fields WHERE forecast_id=? AND lead_minutes=?",
                (forecast_id, lead)).fetchone()
            return (Path(row["npz_path"]), Path(row["png_path"])) if row else None

    def get_uncertainty_png_path(self, forecast_id: str) -> Path | None:
        p = self.artifacts / forecast_id / "uncertainty.png"
        return p if p.exists() else None

    # -- alerts -------------------------------------------------------------------
    def put_alerts(self, alerts: list[Alert]) -> None:
        with self._lock:
            for a in alerts:
                self._conn.execute(
                    "INSERT OR REPLACE INTO alerts (id, run_id, event_id, issued_at, severity,"
                    " preset, region_name, json) VALUES (?,?,?,?,?,?,?,?)",
                    (a.id, a.run_id, a.event_id, a.issued_at.isoformat(), a.severity,
                     a.preset, a.region_name, a.model_dump_json()))
            self._conn.commit()

    def get_alert(self, alert_id: str) -> Alert | None:
        with self._lock:
            row = self._conn.execute("SELECT json FROM alerts WHERE id=?", (alert_id,)).fetchone()
            return Alert.model_validate_json(row["json"]) if row else None

    def list_alerts(self, run_id: str | None = None, event_id: str | None = None,
                    severity: str | None = None) -> list[Alert]:
        q = "SELECT json FROM alerts"
        conds, args = [], []
        if run_id:
            conds.append("run_id=?"); args.append(run_id)
        if event_id:
            conds.append("event_id=?"); args.append(event_id)
        if severity:
            conds.append("severity=?"); args.append(severity)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY issued_at"
        with self._lock:
            return [Alert.model_validate_json(r["json"]) for r in self._conn.execute(q, args).fetchall()]

    # -- health & verification ------------------------------------------------
    def put_data_health(self, items: list[DataHealth]) -> None:
        with self._lock:
            ts = datetime.utcnow().isoformat()
            for it in items:
                self._conn.execute("INSERT INTO data_health (ts, json) VALUES (?,?)",
                                   (ts, it.model_dump_json()))
            self._conn.commit()

    def latest_data_health(self) -> list[DataHealth]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT json FROM data_health WHERE ts = (SELECT MAX(ts) FROM data_health)").fetchall()
            return [DataHealth.model_validate_json(r["json"]) for r in rows]

    def put_verification(self, run_id: str, metrics: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO verification (run_id, metrics) VALUES (?,?)",
                               (run_id, json.dumps(metrics)))
            self._conn.commit()

    def get_verification(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT metrics FROM verification WHERE run_id=?", (run_id,)).fetchone()
            return json.loads(row["metrics"]) if row else None

    def put_training_samples(self, run_id: str, rows: list[dict]) -> Path:
        p_csv = self.artifacts / f"training_samples_{run_id}.csv"
        try:
            import pandas as pd
            p_parquet = self.artifacts / f"training_samples_{run_id}.parquet"
            pd.DataFrame(rows).to_parquet(p_parquet, index=False)
            return p_parquet
        except Exception:
            try:
                import csv
                if rows:
                    keys = list(rows[0].keys())
                    with open(p_csv, "w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=keys)
                        w.writeheader()
                        w.writerows(rows)
            except Exception:
                pass
            return p_csv
