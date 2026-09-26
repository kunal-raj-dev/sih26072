"""Pure-numpy replacements for the handful of scipy.ndimage functions we need.

scipy compiled extensions are blocked by this machine's Windows Application
Control policy (see IMPLEMENTATION_STATUS.md), so the few operations the system
needs are implemented here: connected-component labelling (run-based union-find),
separable smoothing, and binary dilation. Deterministic, no compiled deps.
"""

from __future__ import annotations

import numpy as np


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connectivity connected-component labelling of a boolean mask.

    Returns (label_image with 0 = background, n_components). Components are
    numbered 1..n in row-major order of their first pixel.
    """
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int64)
    parent: list[int] = [0]  # parent[i] for provisional label i

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    starts_mat = (diff == 1)
    ends_mat = (diff == -1)

    prev_runs: list[tuple[int, int, int]] = []
    for i in range(h):
        starts = np.flatnonzero(starts_mat[i])
        ends = np.flatnonzero(ends_mat[i])
        cur: list[tuple[int, int, int]] = []
        for s, e in zip(starts, ends):
            new = len(parent)
            parent.append(new)
            labels[i, s:e] = new
            cur.append((int(s), int(e), new))
        for s, e, l in cur:
            for ps, pe, pl in prev_runs:
                if s < pe and ps < e:  # column overlap (4-connectivity)
                    union(l, pl)
        prev_runs = cur

    # Resolve roots and renumber compactly (1..n).
    out = np.zeros((h, w), dtype=np.int64)
    root_to_final: dict[int, int] = {}
    provisional = np.unique(labels[labels > 0])
    for p in provisional:
        root = find(int(p))
        if root not in root_to_final:
            root_to_final[root] = len(root_to_final) + 1
    if root_to_final:
        lut = np.zeros(len(parent), dtype=np.int64)
        for p in provisional:
            lut[p] = root_to_final[find(int(p))]
        out = lut[labels]
    return out, len(root_to_final)


def _box_blur_1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r <= 0:
        return a
    n = 2 * r + 1
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode="edge").astype(np.float64)
    c = np.cumsum(ap, axis=axis, dtype=np.float64)
    # prepend zeros so out[x] = c[x+n] - c[x] for x in [0, L)
    zshape = list(c.shape)
    zshape[axis] = 1
    c2 = np.concatenate([np.zeros(zshape), c], axis=axis)
    sl_hi = [slice(None)] * a.ndim
    sl_lo = [slice(None)] * a.ndim
    sl_hi[axis] = slice(n, None)         # c2[x+n]
    sl_lo[axis] = slice(0, -n)           # c2[x]
    return (c2[tuple(sl_hi)] - c2[tuple(sl_lo)]) / n


def smooth(a: np.ndarray, sigma: float, passes: int = 2) -> np.ndarray:
    """Approximate Gaussian smoothing via repeated box blurs (separable)."""
    r = max(1, int(round(sigma * 1.5)))
    out = a.astype(np.float64)
    for _ in range(passes):
        out = _box_blur_1d(out, r, axis=0)
        out = _box_blur_1d(out, r, axis=1)
    return out


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Square-kernel binary dilation via shifted maximum."""
    if radius <= 0:
        return mask.copy()
    out = mask.copy()
    for di in range(-radius, radius + 1):
        for dj in range(-radius, radius + 1):
            shifted = np.full_like(mask, False)
            si, sj = max(0, di), max(0, dj)
            ei = mask.shape[0] + min(0, di)
            ej = mask.shape[1] + min(0, dj)
            if ei <= si or ej <= sj:
                continue
            shifted[si:ei, sj:ej] = mask[si - di:ei - di, sj - dj:ej - dj]
            out |= shifted
    return out
