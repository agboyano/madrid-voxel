"""Area of interest shared by all pipeline steps.

Centre, size and rotation of the Madrid grid are the parameters below. The names exported to the rest of the
pipeline (CX, CY, THETA, W, D, I0, J0, RAW, EU, EV, to_grid, to_world, world_bounds) keep the Warsaw interface;
the cache path, lon/lat helpers, corners and the raster affine are adapted from dtla-voxel's aoi.py and
fetch_dem.py (https://github.com/sigman78/dtla-voxel, MIT, see LICENSE-dtla-voxel).

World coords: EPSG:25830 (ETRS89 / UTM 30N), x = easting, y = northing.
Grid coords: (i, j) continuous in cells of VOXEL_SIZE metres; i = column (along EU), j = row (along EV, growing
roughly south); cell (c, r) spans [c, c+1) x [r, r+1). With THETA = 0, +i is east and +j is south, so row 0 is the
northern edge.
"""
import math
import os
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import Transformer

# Edge of one voxel in metres. The single definition for pipeline and viewer (written to meta.json).
VOXEL_SIZE = 1.0

CRS = "EPSG:25830"
# Puerta del Sol: centre of the OSM square (relation 7424032, wikidata Q427163).
CX, CY = 440316.4, 4474264.1
THETA = math.radians(0.0)  # grid rotation, counter-clockwise from east
SIZE_X, SIZE_Y = 500.0, 500.0  # metres along +i and +j: the Phase 1 test area

W, D = round(SIZE_X / VOXEL_SIZE), round(SIZE_Y / VOXEL_SIZE)
I0, J0 = W / 2, D / 2  # grid position of the centre

ROOT = Path(__file__).resolve().parent.parent
# Raw downloads and big intermediates live outside the repository.
CACHE = Path(os.environ.get("MADRID_CACHE", Path.home() / "data" / "madrid-voxel-cache"))
RAW = str(CACHE / "raw")
WEB_DATA = ROOT / "web" / "public" / "data"

EU = np.array([math.cos(THETA), math.sin(THETA)])   # grid +i in world
EV = np.array([math.sin(THETA), -math.cos(THETA)])  # grid +j in world

_to_crs = Transformer.from_crs(4326, CRS, always_xy=True)
_from_crs = Transformer.from_crs(CRS, 4326, always_xy=True)


def to_grid(x, y):
    dx, dy = np.asarray(x) - CX, np.asarray(y) - CY
    return I0 + (dx * EU[0] + dy * EU[1]) / VOXEL_SIZE, J0 + (dx * EV[0] + dy * EV[1]) / VOXEL_SIZE


def to_world(i, j):
    u, v = (np.asarray(i) - I0) * VOXEL_SIZE, (np.asarray(j) - J0) * VOXEL_SIZE
    return CX + u * EU[0] + v * EV[0], CY + u * EU[1] + v * EV[1]


def corners(margin=0.0):
    """World (x, y) of the grid corners, clockwise from cell (0, 0), pushed out by margin metres."""
    m = margin / VOXEL_SIZE
    return list(zip(*to_world(np.array([-m, W + m, W + m, -m]), np.array([-m, -m, D + m, D + m]))))


def world_bounds(margin=0):
    xs, ys = zip(*corners())
    return float(min(xs)) - margin, float(min(ys)) - margin, float(max(xs)) + margin, float(max(ys)) + margin


def lonlat_to_grid(lon, lat):
    return to_grid(*_to_crs.transform(lon, lat))


def grid_to_lonlat(i, j):
    return _from_crs.transform(*to_world(i, j))


def bbox_lonlat(margin=0.0):
    """(south, west, north, east) covering the rotated rectangle pushed out by margin metres."""
    lons, lats = _from_crs.transform(*zip(*corners(margin)))
    return min(lats), min(lons), max(lats), max(lons)


def grid_transform(cell=VOXEL_SIZE):
    """Affine from (col, row) of a raster with square cells of `cell` metres on the rotated grid to EPSG:25830."""
    x0, y0 = to_world(0, 0)  # corner of cell (0, 0)
    return Affine(cell * EU[0], cell * EV[0], x0, cell * EU[1], cell * EV[1], y0)


if __name__ == "__main__":
    s, w, n, e = bbox_lonlat()
    print(f"centre {CX:.1f} {CY:.1f} ({CRS}), rotation {math.degrees(THETA):.1f} deg, "
          f"{W} x {D} cells of {VOXEL_SIZE} m")
    print("world bounds", tuple(round(v, 1) for v in world_bounds()))
    print(f"lon/lat bbox S {s:.6f} W {w:.6f} N {n:.6f} E {e:.6f}")
    print("cache", CACHE)
