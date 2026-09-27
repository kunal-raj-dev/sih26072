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


def apply_isotonic(mapping: dict, x: np.ndarray, method: str = "linear") -> np.ndarray:
    """Apply isotonic calibration mapping to raw forecast probabilities.

    Supports:
    - method="linear": Piecewise linear interpolation between threshold knots,
      eliminating discrete step-staircase jumps and ensuring smooth, calibrated probabilities.
    - method="step": Classical nearest left/step-function assignment.
    """
    x_arr = np.asarray(x, dtype=float)
    th = np.asarray(mapping.get("thresholds", []), dtype=float)
    vals = np.asarray(mapping.get("values", []), dtype=float)
    if th.size == 0 or vals.size == 0:
        return np.clip(x_arr, 0.0, 1.0)

    if method == "linear":
        out = np.interp(x_arr, th, vals, left=vals[0], right=vals[-1])
    else:
        idx = np.searchsorted(th, x_arr, side="left")
        out = np.where(idx < vals.size, vals[np.minimum(idx, vals.size - 1)], vals[-1])

    return np.clip(out, 0.0, 1.0)


def compute_calibration_diagnostics(
    p_calibrated: np.ndarray,
    y_true: np.ndarray,
    n_bins: int = 10,
) -> dict[str, float]:
    """Compute calibration metrics including Expected Calibration Error (ECE) and linear slope/intercept.

    Returns
    -------
    dict with 'ece', 'slope', 'intercept', 'brier_score'
    """
    p = np.clip(np.asarray(p_calibrated, dtype=float), 0.0, 1.0)
    y = np.clip(np.asarray(y_true, dtype=float), 0.0, 1.0)
    if len(p) == 0:
        return {"ece": 0.0, "slope": 1.0, "intercept": 0.0, "brier_score": 0.0}

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    bin_centers: list[float] = []
    observed_freqs: list[float] = []

    for i in range(n_bins):
        b0, b1 = bin_edges[i], bin_edges[i + 1]
        mask = (p >= b0) & (p <= b1 if i == n_bins - 1 else p < b1)
        if np.any(mask):
            p_mean = float(np.mean(p[mask]))
            y_mean = float(np.mean(y[mask]))
            weight = float(np.sum(mask)) / len(p)
            ece += weight * abs(p_mean - y_mean)
            bin_centers.append(p_mean)
            observed_freqs.append(y_mean)

    if len(bin_centers) >= 2:
        poly = np.polyfit(bin_centers, observed_freqs, 1)
        slope = float(poly[0])
        intercept = float(poly[1])
    else:
        slope = 1.0
        intercept = 0.0

    brier = float(np.mean((p - y) ** 2))
    return {
        "ece": round(float(ece), 4),
        "slope": round(float(slope), 4),
        "intercept": round(float(intercept), 4),
        "brier_score": round(float(brier), 4),
    }
