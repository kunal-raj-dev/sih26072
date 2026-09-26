"""Prepare SEVIR replay events: range-read real event slabs into the local cache.

Usage:
  python scripts/prepare_sevir_events.py [--n 8]

Picks the events with the most GLM flashes from the cached March-2019 lightning
file (verification-friendly), requires vil+ir107+lght catalog rows, and caches
each event under data/external/sevir/events/<id>.npz (≈16-20 MB per event).
Only single-event slabs are transferred — the 12-17 GB monthly grid files are
never downloaded (h5py+s3fs HTTP range reads; verified 2026-09-27).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vajra.config import load_settings                      # noqa: E402
from vajra.logsetup import get_logger, log_event            # noqa: E402
from vajra.providers.sevir import (                         # noqa: E402
    SevirCatalog, SevirReplayEvent, pick_event_with_most_flashes)

logger = get_logger("vajra.scripts.prepare", json_mode=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    settings = load_settings()
    catalog = SevirCatalog(settings.data_root / "external" / "sevir")
    events_dir = settings.data_root / "external" / "sevir" / "events"
    lght_local = settings.data_root / "external" / "sevir" / "SEVIR_LGHT_ALLEVENTS_2019_0301_0401.h5"
    if not lght_local.exists():
        raise SystemExit("March-2019 lightning file not cached; it is downloaded on first use — re-run.")

    ranked = pick_event_with_most_flashes(catalog, events_dir, top=args.n)
    log_event(logger, 20, "candidates", events=ranked)
    for eid in ranked:
        try:
            bundle = SevirReplayEvent(eid, settings, catalog).prepare()
            flashes = 0 if bundle.flashes.size == 0 else int(bundle.flashes.shape[0])
            print(f"OK  {eid}: {len(bundle.minute_offsets)} frames, "
                  f"vil {bundle.vil.shape}, ir107 {bundle.ir107.shape}, "
                  f"{flashes} flashes, center {bundle.time_center:%Y-%m-%d %H:%M} UTC")
        except Exception as exc:  # noqa: BLE001 — continue over individual failures
            print(f"ERR {eid}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
