"""Ground steps along the roads: how often the ground under a carriageway jumps between neighbouring cells.

Adapted from portland-voxel (https://github.com/matt0x6F/portland-voxel, commit 69c55f9, MIT), itself built on
warsaw-vibe-voxel. Portland also levels the ground under its roads where the DTM keeps pier footings and abutments;
Madrid keeps only the measurement, as the area showed too few steps to need it, most of them on car-park ramps
(DECISIONS.md, 2026-11-20; scripts/deck_road_report.py).

Distances are in metres and converted to cells with VOXEL_SIZE; heights g are in voxels.
"""
import numpy as np

from aoi import VOXEL_SIZE

JUMP = 1.5  # m between neighbouring samples of the DTM along a way's centre line: where Portland levels the road
STEP = 2.0  # m: a ground step along a road that steps() counts


def samples(line):
    """points every cell along a centre line (grid coordinates: x = column, y = row)"""
    n = max(2, int(line.length) + 1)
    return np.array([line.interpolate(v).coords[0] for v in np.linspace(0, line.length, n)])


def steps_per_way(g, ways):
    """for each way (line, ...), the ground steps of STEP or more between neighbouring samples along its centre line"""
    D, W = g.shape
    lim = STEP / VOXEL_SIZE
    each = []
    for line, *_ in ways:
        P = samples(line)
        r, c = P[:, 1].astype(int), P[:, 0].astype(int)
        k = (r >= 0) & (r < D) & (c >= 0) & (c < W)
        each.append(int((np.abs(np.diff(g[r[k], c[k]].astype(int))) >= lim).sum()))
    return each


def steps(g, ways):
    """ground steps of STEP or more along all the ways' centre lines"""
    return sum(steps_per_way(g, ways))
