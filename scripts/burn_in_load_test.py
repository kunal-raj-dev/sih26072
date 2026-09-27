"""Continuous Operational Burn-In & Latency Load Test (EPIC 11 / TASK-11.2).

Usage:
    python scripts/burn_in_load_test.py [--cycles 72] [--event bihar_squall_2026]

Simulates consecutive operational nowcasting cycles to benchmark:
1. End-to-end cycle execution latency (SLA target: < 1000 ms per 10-min cycle).
2. Memory stability and leak diagnostics (tracemalloc & memory differential).
3. Zero-crash pipeline resilience under continuous load.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from vajra.api.app import _ensure_pipeline, _register_available_events
from vajra.case_studies import get_case_study
from vajra.config import load_settings
from vajra.store import Store


def run_burn_in_test(event_id: str = "bihar_squall_2026", n_cycles: int = 72) -> dict:
    """Executes consecutive nowcast cycles, tracking memory and latency."""
    print("=" * 76)
    print(f"Starting Project Vajra Continuous Operational Burn-In Test")
    print(f"Target Event: {event_id} | Consecutive Cycles: {n_cycles}")
    print("=" * 76)

    settings = load_settings()
    store = Store(settings)
    _register_available_events(settings, store)

    cs = get_case_study(event_id)
    if not cs:
        raise ValueError(f"Unknown case study: {event_id}")

    state: dict = {}
    pipeline, event, _ = _ensure_pipeline(cs.event_id, settings, store, state)

    # Start memory tracking
    gc.collect()
    tracemalloc.start()
    mem_start_current, mem_start_peak = tracemalloc.get_traced_memory()

    latencies_ms = []
    t_curr = event.time_start
    step_delta = timedelta(minutes=settings.replay.cycle_minutes)

    print(f"\nCycle | Issue Time (UTC)   | Cells | Alerts | Latency (ms) | Memory Current (MB)")
    print("-" * 76)

    for i in range(1, n_cycles + 1):
        t0 = time.perf_counter()
        forecast, alerts = pipeline.run_cycle(t_curr, event.id, event.mode)
        t_elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(t_elapsed_ms)

        # Store forecast
        store.put_forecast(forecast, {})
        store.put_alerts(alerts)

        curr_mem, peak_mem = tracemalloc.get_traced_memory()
        curr_mb = curr_mem / (1024 * 1024)

        if i % 6 == 0 or i == 1 or i == n_cycles:
            n_cells = len(forecast.steps[0].cells) if forecast.steps else 0
            print(f"{i:5d} | {t_curr.strftime('%Y-%m-%d %H:%M')} | {n_cells:5d} | {len(alerts):6d} | {t_elapsed_ms:10.1f}ms | {curr_mb:15.2f} MB")

        t_curr += step_delta

    gc.collect()
    mem_final_current, mem_final_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    lat_arr = np.array(latencies_ms)
    p50 = float(np.percentile(lat_arr, 50))
    p95 = float(np.percentile(lat_arr, 95))
    p99 = float(np.percentile(lat_arr, 99))
    max_lat = float(np.max(lat_arr))
    mean_lat = float(np.mean(lat_arr))

    mem_growth_mb = (mem_final_current - mem_start_current) / (1024 * 1024)
    peak_mb = mem_final_peak / (1024 * 1024)

    print("\n" + "=" * 76)
    print("BURN-IN BENCHMARK RESULTS")
    print("=" * 76)
    print(f"Total Cycles Completed:   {n_cycles}")
    print(f"Mean Cycle Latency:       {mean_lat:.1f} ms  (Target: < 1000 ms)  -> {'PASS' if mean_lat < 1000 else 'FAIL'}")
    print(f"p50 Latency:              {p50:.1f} ms")
    print(f"p95 Latency:              {p95:.1f} ms")
    print(f"p99 Latency:              {p99:.1f} ms")
    print(f"Max Cycle Latency:        {max_lat:.1f} ms")
    print(f"Peak Traced Memory:       {peak_mb:.2f} MB")
    print(f"Net Memory Growth:        {mem_growth_mb:+.2f} MB  (Target: < 50 MB)  -> {'PASS' if mem_growth_mb < 50 else 'FAIL'}")
    print("=" * 76)

    success = (mean_lat < 1000.0) and (mem_growth_mb < 50.0)
    print(f"Burn-In Evaluation Status: {'✓ PASS (Production Stable)' if success else '✗ FAILED'}\n")

    return {
        "cycles": n_cycles,
        "mean_latency_ms": mean_lat,
        "p95_latency_ms": p95,
        "max_latency_ms": max_lat,
        "peak_memory_mb": peak_mb,
        "memory_growth_mb": mem_growth_mb,
        "success": success,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Project Vajra Burn-In Load Test")
    ap.add_argument("--cycles", type=int, default=72, help="Number of consecutive cycles (default 72 = 12 hours)")
    ap.add_argument("--event", type=str, default="bihar_squall_2026", help="Case study ID")
    args = ap.parse_args()

    res = run_burn_in_test(event_id=args.event, n_cycles=args.cycles)
    if not res["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
