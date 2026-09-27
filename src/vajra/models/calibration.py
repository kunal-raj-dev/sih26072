"""Isotonic (PAVA) calibration — pure numpy replacement for sklearn's IsotonicRegression.

Calibration is a first-class component (MASTER.md §8): raw model scores are mapped
to observed frequencies on a held-out calibration split before any probability is
displayed. The mapping is serialized with the model version it belongs to.
"""

from __future__ import annotations

import numpy as np


def fit_isotonic(x: np.ndarray, y: np.ndarray) -> dict:
    """Pool-adjacent-violators on (score x in [0,1], binary y). Returns step mapping."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    order = np.argsort(x, kind="stable")
    xs, ys = x[order], y[order]
    # PAVA on ys with weights (all 1); merge adjacent violating blocks.
    blocks: list[list[float]] = []  # [sum_y, count, mean, x_right]
    for xi, yi in zip(xs, ys):
        blocks.append([yi, 1.0, yi, xi])
        while len(blocks) >= 2 and blocks[-2][2] >= blocks[-1][2] + 1e-12:
            s2, c2, _, xr2 = blocks.pop()
            s1, c1, _, _ = blocks.pop()
            blocks.append([s1 + s2, c1 + c2, (s1 + s2) / (c1 + c2), xr2])
    # Deduplicate x ties: keep last mean per unique x.
    thresholds, values = [], []
    seen = set()
    for _, _, mean, xr in blocks:
        key = round(xr, 12)
        if key in seen:
            values[-1] = mean
            continue
        seen.add(key)
        thresholds.append(xr)
        values.append(mean)
    return {"thresholds": [float(t) for t in thresholds], "values": [float(v) for v in values]}


def apply_isotonic(mapping: dict, x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    th = np.asarray(mapping["thresholds"], dtype=float)
    vals = np.asarray(mapping["values"], dtype=float)
    if th.size == 0:
        return np.clip(x, 0.0, 1.0)
    idx = np.searchsorted(th, x, side="left")
    out = np.where(idx < vals.size, vals[np.minimum(idx, vals.size - 1)], vals[-1])
    return np.clip(out, 0.0, 1.0)
