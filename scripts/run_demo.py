"""Run the demo replay for one event through the API-visible pipeline.

Usage:
  python scripts/run_demo.py --event SIM_BIHAR_001            # labelled SIMULATION
  python scripts/run_demo.py --event SEVIR_S810646            # real historical REPLAY

Prints the run summary + verification scoreboard. The API/UI can then browse
everything (same store).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vajra.config import load_settings                          # noqa: E402
from vajra.store import Store                                   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    args = ap.parse_args()

    from vajra.api.app import _ensure_pipeline

    settings = load_settings()
    store = Store(settings)
    state: dict = {}
    pipeline, event, _sources = _ensure_pipeline(args.event, settings, store, state)
    run = pipeline.run_replay(event, event.time_start, event.time_end)
    store.put_run(run)
    print(json.dumps({
        "run_id": run.id, "event": event.id, "mode": event.mode.value,
        "cycles": run.cycles, "alerts": len(run.alerts),
        "verification": run.metrics.get("metrics", {}),
    }, indent=1))


if __name__ == "__main__":
    main()
