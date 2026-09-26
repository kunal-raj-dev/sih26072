"""Verification metrics — the honest scoreboard (MASTER.md §8, D8).

Implemented per the research validation standard:
- detection at a pre-registered probability threshold: POD, FAR, CSI;
- probabilistic: Brier score, Brier Skill Score vs climatology;
- reliability diagram bins;
- FSS (fractions skill score) for gridded fields (Roberts & Lean 2008 lineage);
- lead-time curves are assembled by the caller from per-lead results.

Every function is deliberately simple, deterministic and unit-tested. No metric
is reported anywhere in the product unless computed by this module.
"""

from __future__ import annotations

import numpy as np


def contingency(p: np.ndarray, y: np.ndarray, threshold: float) -> tuple[int, int, int, int]:
    """(hits, misses, false_alarms, correct_negatives) at a probability threshold."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y).astype(bool)
    fc = p >= threshold
    hits = int((fc & y).sum())
    misses = int((~fc & y).sum())
    fa = int((fc & ~y).sum())
    cn = int((~fc & ~y).sum())
    return hits, misses, fa, cn


def pod_far_csi(hits: int, misses: int, false_alarms: int) -> tuple[float, float, float]:
    pod = hits / (hits + misses) if (hits + misses) else float("nan")
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) else float("nan")
    denom = hits + misses + false_alarms
    csi = hits / denom if denom else float("nan")
    return pod, far, csi


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def brier_skill_score(p: np.ndarray, y: np.ndarray, p_ref: np.ndarray) -> float:
    """BSS vs a reference (usually climatology). <=0 means no skill vs reference."""
    bs = brier_score(p, y)
    bs_ref = brier_score(p_ref, y)
    if bs_ref == 0:
        return float("nan")
    return 1.0 - bs / bs_ref


def reliability_curve(p: np.ndarray, y: np.ndarray, n_bins: int = 5) -> list[dict]:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for k in range(n_bins):
        lo, hi = edges[k], edges[k + 1]
        sel = (p >= lo) & (p < hi) if k < n_bins - 1 else (p >= lo) & (p <= hi)
        n = int(sel.sum())
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "n": n,
            "forecast_mean": float(p[sel].mean()) if n else None,
            "observed_freq": float(y[sel].mean()) if n else None,
        })
    return out


def fss(p_fc: np.ndarray, p_obs: np.ndarray, window: int = 5) -> float:
    """Fractions Skill Score for two fields of event indicators (0..1 window fractions)."""
    p_fc = (np.asarray(p_fc, dtype=float) >= 0.5).astype(float)
    p_obs = (np.asarray(p_obs, dtype=float) >= 0.5).astype(float)
    num = _window_mean((p_fc - p_obs) ** 2, window)
    den = _window_mean(p_fc ** 2, window) + _window_mean(p_obs ** 2, window)
    if den.size == 0 or np.all(den == 0):
        return float("nan")
    return float(1.0 - np.mean(num) / np.mean(den))


def _window_mean(a: np.ndarray, w: int) -> np.ndarray:
    """Non-overlapping window means (truncating edges)."""
    h, hh = a.shape[0] // w, a.shape[1] // w
    a = a[: h * w, : hh * w]
    return a.reshape(h, w, hh, w).mean(axis=(1, 3))
