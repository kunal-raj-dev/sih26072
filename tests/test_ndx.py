import numpy as np

from vajra.ndx import dilate, label, smooth


def test_label_finds_two_components():
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    mask[7:9, 7:9] = True
    lab, n = label(mask)
    assert n == 2
    assert set(np.unique(lab[lab > 0])) == {1, 2}


def test_label_merges_diagonal_free_4_connectivity():
    mask = np.zeros((5, 5), dtype=bool)
    mask[0, 0] = True
    mask[1, 1] = True  # diagonal: NOT connected under 4-connectivity
    lab, n = label(mask)
    assert n == 2


def test_label_union_of_offset_rows():
    mask = np.zeros((6, 8), dtype=bool)
    mask[0, 0:3] = True
    mask[1, 1:4] = True  # overlapping run -> same component
    mask[3, 0:2] = True  # separate
    lab, n = label(mask)
    assert n == 2
    assert lab[0, 0] == lab[1, 2] != 0


def test_dilate_radius():
    mask = np.zeros((7, 7), dtype=bool)
    mask[3, 3] = True
    d = dilate(mask, 1)
    assert d.sum() == 9
    assert d[2, 2] and d[3, 3] and not d[0, 0]


def test_smooth_reduces_variance():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, (40, 40))
    s = smooth(a, sigma=2.0)
    assert s.std() < a.std()
    assert s.shape == a.shape
