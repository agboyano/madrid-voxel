"""How well a grid rotation fits the city: the share of facade length that runs along the grid's axes.

A wall within a few degrees of a grid axis becomes a straight voxel wall; one at an angle becomes a staircase. For each
candidate rotation (counter-clockwise from east, mod 90) this measures, over the Catastro building outlines of the
AOI, the share of facade length within TOL degrees of the grid, and prints the bearing (mod 90) of the named streets
given on the command line, from OSM, weighted by length.

usage: PYTHONPATH=scripts uv run python scripts/rotation_report.py ["Gran Vía" "Paseo del Prado" ...]
"""
import json
import sys

import numpy as np
from shapely.geometry import shape

from aoi import AREA, to_world

TOL = 3.0  # degrees
CANDIDATES = range(0, 90, 1)


def facade_angles():
    feats = json.load(open(AREA / "catastro" / "buildings.geojson"))["features"]
    ang, w = [], []
    for f in feats:
        for poly in shape(f["geometry"]).geoms:
            xy = np.array(poly.exterior.coords)
            d = np.diff(xy, axis=0)
            L = np.hypot(*d.T)
            keep = L > 2
            ang.append(np.degrees(np.arctan2(d[keep, 1], d[keep, 0])) % 90)
            w.append(L[keep])
    return np.concatenate(ang), np.concatenate(w)


def aligned(ang, w, theta):
    d = np.abs((ang - theta + 45) % 90 - 45)
    return float(w[d <= TOL].sum() / w.sum() * 100)


def street_bearing(name):
    """Length-weighted mean bearing mod 90 of the OSM ways with that name (world frame), as a circular mean."""
    from osm import OSM
    osm = OSM()
    vecs = []
    for _, t, line in osm.lines:
        if t.get("name") != name or "highway" not in t:
            continue
        xy = np.array([to_world(x, y) for x, y in line.coords])
        d = np.diff(xy, axis=0)
        a = np.arctan2(d[:, 1], d[:, 0]) * 4  # x4: mod 90 degrees on the circle
        L = np.hypot(*d.T)
        vecs.append(np.c_[L * np.cos(a), L * np.sin(a)].sum(0))
    if not vecs:
        return None
    v = np.sum(vecs, 0)
    return float(np.degrees(np.arctan2(v[1], v[0])) / 4 % 90)


def main():
    ang, w = facade_angles()
    scores = {t: aligned(ang, w, t) for t in CANDIDATES}
    best = max(scores, key=lambda t: scores[t])
    print(f"{len(ang)} facade edges, {w.sum() / 1000:.1f} km; share within {TOL} deg of the grid:")
    for t in sorted({0, best}):
        print(f"  rotation {t:2d} deg: {scores[t]:5.1f} %")
    for name in sys.argv[1:]:
        b = street_bearing(name)
        if b is None:
            print(f"  {name}: not in the AOI's OSM")
            continue
        r = round(b) % 90
        print(f"  {name}: bearing {b:.1f} deg mod 90 -> rotation {r} deg: {scores[r]:5.1f} % of facades aligned")


if __name__ == "__main__":
    main()
