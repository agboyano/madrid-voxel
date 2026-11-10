"""PNOA-LiDAR 3rd coverage (NPC02) point cloud tiles covering the AOI.

The Centro de Descargas del CNIG protects downloads with reCAPTCHA, so they cannot be automated (CLAUDE.md rule 5).
This script does not download: it works out which 1 x 1 km tiles the AOI needs, checks the LAZ files placed in
{RAW}/pnoa_lidar/ by reading their headers (not the file names), and prints manual download instructions for
whatever is missing. Exit code 0 when the AOI is covered, 1 otherwise.

CNIG file names give the north-west corner of the tile in km: PNOA_2024_MAD_440-4474_H30_NPC02.LAZ covers
X 440 000-441 000, Y 4 473 000-4 474 000 (checked against the headers).

NPC03 (same files with improved classification) can replace NPC02 when it is published for Madrid: put those files
in the same folder instead; nothing else changes.
"""
import math
import sys
from pathlib import Path

import laspy

from aoi import AREA_NAME, CRS, RAW, bbox_lonlat, world_bounds

MARGIN = 0  # metres around the AOI: none, prep_lidar.py rasterises only the points inside it
TILE = 1000  # metres, the CNIG distribution grid
DIR = Path(RAW) / "pnoa_lidar"
SERIES_URL = "https://centrodedescargas.cnig.es/CentroDescargas/lidar-tercera-cobertura"


def needed_tiles():
    """(x_km, y_km) of the lower-left corners of the 1 km tiles that intersect the AOI plus margin."""
    x0, y0, x1, y1 = world_bounds(MARGIN)
    return [(x, y) for x in range(math.floor(x0 / TILE), math.ceil(x1 / TILE))
            for y in range(math.floor(y0 / TILE), math.ceil(y1 / TILE))]


def cnig_name(tx, ty):
    """Expected CNIG file name for the tile whose lower-left corner is (tx, ty) km."""
    return f"PNOA_2024_MAD_{tx}-{ty + 1}_H30_NPC02.LAZ"


def describe(path):
    with laspy.open(path) as f:
        h = f.header
        crs = h.parse_crs()
        return {"file": path.name, "points": h.point_count, "format": h.point_format.id, "version": str(h.version),
                "mins": h.mins, "maxs": h.maxs, "date": h.creation_date, "crs": crs.to_string() if crs else None}


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in DIR.iterdir() if p.suffix.lower() == ".laz")
    found = [describe(p) for p in files]
    for d in found:
        print(f"{d['file']}: {d['points']:,} points, LAS {d['version']} format {d['format']}, "
              f"x {d['mins'][0]:.0f}-{d['maxs'][0]:.0f}, y {d['mins'][1]:.0f}-{d['maxs'][1]:.0f}, "
              f"created {d['date']}, {d['crs']}")

    missing = []
    for tx, ty in needed_tiles():
        cx, cy = (tx + 0.5) * TILE, (ty + 0.5) * TILE
        if not any(d["mins"][0] <= cx <= d["maxs"][0] and d["mins"][1] <= cy <= d["maxs"][1] for d in found):
            missing.append((tx, ty))
    if not missing:
        print(f"AOI covered by {len(found)} file(s) in {DIR}")
        return

    s, w, n, e = bbox_lonlat(MARGIN)
    x0, y0, x1, y1 = world_bounds(MARGIN)
    print(f"""
Missing PNOA-LiDAR coverage for {len(missing)} 1 km tile(s) (lower-left corner in km, {CRS}):
  {', '.join(f'X {tx} Y {ty}' for tx, ty in missing)}
  expected file names: {', '.join(cnig_name(tx, ty) for tx, ty in missing)}

Download them by hand (the CNIG download centre requires a reCAPTCHA):
  1. Open {SERIES_URL}
     (series "LiDAR 3a Cobertura (2022-2025)", product "Nube de puntos clasificada", NPC02).
  2. Search by coordinates or on the map for the area
       {CRS}: X {x0:.0f} to {x1:.0f}, Y {y0:.0f} to {y1:.0f}
       lon/lat: {w:.5f} to {e:.5f}, {s:.5f} to {n:.5f} (area "{AREA_NAME}" in pipeline.toml)
     and pick the LAZ files (NPC02, 2024 flight, huso 30) whose 1 km square covers it.
  3. Save the .laz files, unrenamed, in:
       {DIR}
  4. Run this script again; it reads the file headers to check the coverage.""")
    sys.exit(1)


if __name__ == "__main__":
    main()
