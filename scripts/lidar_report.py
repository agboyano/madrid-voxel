"""Report on the PNOA-LiDAR point cloud over the AOI: density, capture dates, classes, colour and NIR, NDVI test.

Reads the LAZ files that fetch_pnoa_lidar.py validated, keeps the points inside the AOI (and, for the NDVI test, a
box over Paseo del Prado) and prints the figures recorded in NOTES.md. With --images it also writes top-down class
and NDVI maps to docs/img/ for visual checks. Re-run it for any new cloud (NPC03, the municipal 2026 flight).

usage: PYTHONPATH=scripts uv run python scripts/lidar_report.py [--images]
"""
import argparse
import datetime as dt
from pathlib import Path

import laspy
import numpy as np
from PIL import Image

from aoi import D, RAW, ROOT, VOXEL_SIZE, W, to_grid, world_bounds

DIR = Path(RAW) / "pnoa_lidar"
CHUNK = 2_000_000
# Paseo del Prado between the Prado Museum and Neptuno: a row of plane trees over road and pavement.
PRADO = (441_200.0, 4_474_050.0, 441_330.0, 4_474_350.0)
# PNOA-LiDAR classes (pnoa.ign.es, "Procesamiento de los datos"): ASPRS 1-17 plus PNOA codes from 64. Class 12
# (overlap) replaces the semantic class of points from the second strip where flight lines overlap.
CLASSES = {1: "unclassified", 2: "ground", 3: "low vegetation", 4: "medium vegetation", 5: "high vegetation",
           6: "building", 7: "noise", 9: "water", 12: "overlap", 14: "power line", 15: "power tower",
           17: "bridge", 64: "vehicle", 65: "wall", 67: "solar panel", 68: "wind turbine", 69: "dam",
           70: "antenna", 71: "flat roof", 72: "pitched roof", 73: "green flat roof", 74: "facade",
           75: "interior courtyard"}
OVERLAP = 12
COLOURS = {1: (255, 0, 255), 2: (150, 120, 90), 3: (170, 230, 120), 4: (90, 190, 70), 5: (20, 110, 30),
           6: (220, 60, 50), 7: (0, 0, 0), 9: (40, 90, 220), 14: (0, 0, 0), 17: (255, 200, 0),
           64: (0, 200, 255), 65: (255, 140, 0), 67: (60, 60, 160), 70: (255, 255, 0)}
GPS_EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.UTC)


def points_in(box):
    """Concatenated point arrays (x, y, z, class, return info, time, rgb, nir) inside box from every file."""
    x0, y0, x1, y1 = box
    cols = {k: [] for k in ("x", "y", "z", "cls", "ret", "nret", "t", "r", "g", "b", "nir", "withheld", "overlap")}
    for p in sorted(DIR.glob("*.[lL][aA][zZ]")):
        with laspy.open(p) as f:
            h = f.header
            if h.maxs[0] < x0 or h.mins[0] > x1 or h.maxs[1] < y0 or h.mins[1] > y1:
                continue
            for c in f.chunk_iterator(CHUNK):
                x, y = np.asarray(c.x), np.asarray(c.y)
                m = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
                if not m.any():
                    continue
                cols["x"].append(x[m]); cols["y"].append(y[m]); cols["z"].append(np.asarray(c.z)[m])
                cols["cls"].append(np.asarray(c.classification)[m])
                cols["ret"].append(np.asarray(c.return_number)[m]); cols["nret"].append(np.asarray(c.number_of_returns)[m])
                cols["t"].append(np.asarray(c.gps_time)[m])
                for k, d in (("r", "red"), ("g", "green"), ("b", "blue"), ("nir", "nir")):
                    cols[k].append(np.asarray(c[d])[m])
                cols["withheld"].append(np.asarray(c.withheld)[m]); cols["overlap"].append(np.asarray(c.overlap)[m])
    return {k: np.concatenate(v) for k, v in cols.items()}


def gps_date(t):
    """Adjusted standard GPS time (global encoding bit set in the PNOA headers) to a UTC date, ignoring leap seconds."""
    return (GPS_EPOCH + dt.timedelta(seconds=float(t) + 1e9)).date()


def ndvi(p):
    nir, red = p["nir"].astype(float), p["r"].astype(float)
    return (nir - red) / np.maximum(nir + red, 1)


def class_map(p, path):
    """Top-down map at VOXEL_SIZE: the class of the highest non-overlap point in each cell (white: none)."""
    i, j = to_grid(p["x"], p["y"])
    i, j = i.astype(int), j.astype(int)
    keep = (i >= 0) & (i < W) & (j >= 0) & (j < D) & (p["cls"] != OVERLAP)
    i, j, z, cls = i[keep], j[keep], p["z"][keep], p["cls"][keep]
    order = np.argsort(z)  # later (higher) points overwrite earlier ones
    img = np.full((D, W, 3), 255, np.uint8)
    lut = np.zeros((256, 3), np.uint8)
    for k, c in COLOURS.items():
        lut[k] = c
    img[j[order], i[order]] = lut[cls[order]]
    Image.fromarray(img).resize((W * 2, D * 2), Image.NEAREST).save(path)


def ndvi_map(p, box, path, cell=0.5):
    x0, y0, x1, y1 = box
    w, h = int((x1 - x0) / cell), int((y1 - y0) / cell)
    c = np.minimum(((p["x"] - x0) / cell).astype(int), w - 1)
    r = np.minimum(((y1 - p["y"]) / cell).astype(int), h - 1)
    order = np.argsort(p["z"])
    v = np.full((h, w), np.nan)
    v[r[order], c[order]] = ndvi(p)[order]
    t = np.clip((np.nan_to_num(v, nan=-1) + 0.2) / 0.9, 0, 1)
    img = np.stack([(1 - t) * 230, 60 + t * 160, (1 - t) * 60], -1).astype(np.uint8)
    img[np.isnan(v)] = 255
    Image.fromarray(img).resize((w * 3, h * 3), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", action="store_true", help="write class and NDVI maps to docs/img/")
    args = ap.parse_args()

    box = world_bounds()
    p = points_in(box)
    area = (box[2] - box[0]) * (box[3] - box[1])
    n, first, last = len(p["x"]), (p["ret"] == 1).sum(), (p["ret"] == p["nret"]).sum()
    print(f"AOI {area / 1e6:.2f} km2: {n:,} points, {n / area:.1f} pts/m2 all returns, "
          f"{first / area:.1f} first returns/m2, {last / area:.1f} last returns/m2")
    own = p["cls"] != OVERLAP
    print(f"without overlap (class {OVERLAP}): {own.sum() / area:.1f} pts/m2, "
          f"{(own & (p['ret'] == 1)).sum() / area:.1f} first returns/m2")
    gx, gy = to_grid(p["x"], p["y"])
    ok = (gx >= 0) & (gx < W) & (gy >= 0) & (gy < D)
    for name, m in (("all points", ok), ("without overlap", ok & own)):
        cells = np.zeros(W * D, int)
        np.add.at(cells, gy[m].astype(int) * W + gx[m].astype(int), 1)
        print(f"cells of {VOXEL_SIZE} m with no points ({name}): {(cells == 0).mean() * 100:.2f} %, "
              f"median points per cell {np.median(cells):.0f}")
    print(f"withheld {p['withheld'].sum():,}, overlap flag {p['overlap'].sum():,}")

    days, counts = np.unique([gps_date(t) for t in np.quantile(p["t"], np.linspace(0, 1, 201))], return_counts=True)
    print("capture dates (sampled):", ", ".join(f"{d} ({c / 2:.1f} %)" for d, c in zip(days, counts)))

    print("classes:")
    for k, c in zip(*np.unique(p["cls"], return_counts=True)):
        print(f"  {k:3d} {CLASSES.get(int(k), '?'):20s} {c:>10,} {c / n * 100:6.2f} %")

    for k in ("r", "g", "b", "nir"):
        v = p[k]
        print(f"{k:>4}: min {v.min()} max {v.max()} mean {v.mean():.0f} zero {np.mean(v == 0) * 100:.1f} %")
    g = p["cls"] == 2
    print(f"ground z: min {p['z'][g].min():.2f} median {np.median(p['z'][g]):.2f} max {p['z'][g].max():.2f} m")

    q = points_in(PRADO)
    v = ndvi(q)
    print(f"NDVI test over Paseo del Prado {PRADO}: {len(v):,} points")
    for name, m in (("high vegetation (5)", q["cls"] == 5), ("medium vegetation (4)", q["cls"] == 4),
                    ("ground (2)", q["cls"] == 2), ("building (6)", q["cls"] == 6)):
        if m.any():
            print(f"  {name:22s} n {m.sum():>8,} NDVI median {np.median(v[m]):+.2f} "
                  f"p10 {np.quantile(v[m], 0.1):+.2f} p90 {np.quantile(v[m], 0.9):+.2f}")

    if args.images:
        out = ROOT / "docs" / "img"
        class_map(p, out / "phase1-lidar-classes.png")
        ndvi_map(q, PRADO, out / "phase1-lidar-ndvi-prado.png")
        print("images written to", out)


if __name__ == "__main__":
    main()
