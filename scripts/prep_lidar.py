"""Rasterise a classified point cloud straight onto the rotated grid: the common elevation format.

Adapted from dtla-voxel scripts/prep_lidar.py (https://github.com/sigman78/dtla-voxel, commit 90bc1a6c, MIT, see
LICENSE-dtla-voxel). Unlike LA, the PNOA cloud is already classified, so classes are read, not inferred, and the
points are in the grid's own CRS, so there is no reprojection.

Every point goes to the cell of the aoi.py frame it falls in (centre + rotation), at the resolution set in
pipeline.toml; nothing is rasterised north-up and rotated afterwards. A new rotation only means re-running this step.

Sources: each entry of SOURCES is an adapter from one flight's files and class codes to the canonical classes below.
Adding a source (the municipal 2026 flight, NPC03) means a fetch_ script and one entry here; nothing downstream
changes.

Output: {AREA}/elevation_{source}.npz, every array (rows, cols) on the grid at RES metres, row 0 = grid row 0:
  dsm        float32  highest point that is not noise or a vehicle (overlap points included); NaN where empty
  dtm        float32  ground (canonical GROUND) mean height, gaps filled by a multi-scale fill: no NaN
  ground_n   uint16   ground points per cell (0 where the DTM is filled)
  cls        uint8    canonical class of the highest non-overlap point; cells with only overlap points take the class
                      of the nearest cell that has its own (CLAUDE.md, DECISIONS.md 2026-11-11); 0 where empty
  cls_filled bool     cells whose class came from a neighbour
  top_<k>    float32  highest point of class group k (building, vegetation, bridge); NaN where none
  n_<k>      uint16   points of class group k (all, overlap, vegetation_nonlast, vehicle)
plus res, source, crs, vertical, dates and the aoi parameters, for checking that downstream steps agree.

usage: PYTHONPATH=scripts uv run python scripts/prep_lidar.py
"""
import datetime as dt
import json
import math
import time
from pathlib import Path

import laspy
import numpy as np
from scipy import ndimage

from aoi import AREA, CRS, CX, CY, D, RAW, THETA, VOXEL_SIZE, W, to_grid, world_bounds
from config import ELEVATION

# Canonical classes: ASPRS codes, plus PNOA's own above 63. Adapters map their source's codes onto these.
UNCLASSIFIED, GROUND, VEG_LOW, VEG_MED, VEG_HIGH, BUILDING, NOISE, WATER, OVERLAP = 1, 2, 3, 4, 5, 6, 7, 9, 12
POWER_LINE, POWER_TOWER, BRIDGE, VEHICLE, WALL, SOLAR, ANTENNA = 14, 15, 17, 64, 65, 67, 70
GROUPS = {"building": (BUILDING, WALL, SOLAR, ANTENNA, 71, 72, 73, 74, 75),
          "vegetation": (VEG_LOW, VEG_MED, VEG_HIGH),
          "bridge": (BRIDGE,)}

SOURCES = {
    "pnoa_npc02": dict(
        description="PNOA-LiDAR 3rd coverage, NPC02 (CNIG), flown 2024-03-17/18",
        files=Path(RAW) / "pnoa_lidar", pattern="*NPC02.[lL][aA][zZ]",
        crs="EPSG:25830", vertical="orthometric (IGN conversion from ellipsoidal; geoid model not stated)",
        classes={},  # PNOA already uses the canonical codes
        noise=(NOISE, 18), overlap=(OVERLAP,), gps_adjusted=True),
}
GPS_EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.UTC)
CHUNK = 2_000_000
FILL_SMOOTH = 3.0  # metres, sigma of the smoothing applied to filled ground cells


def fill_gaps(a):
    """Fill NaN cells by a multi-scale average (push-pull): each coarser level averages the valid cells, holes take
    the coarse value, so large gaps (ground under buildings) get a smooth surface and small ones their neighbours."""
    if not np.isnan(a).any():
        return a
    h, w = a.shape
    v = np.nan_to_num(a)
    wt = (~np.isnan(a)).astype(np.float64)
    if (h, w) == (1, 1) or min(h, w) < 2:
        m = v.sum() / max(wt.sum(), 1)
        return np.where(np.isnan(a), m, a)
    ph, pw = h + h % 2, w + w % 2
    vp, wp = np.zeros((ph, pw)), np.zeros((ph, pw))
    vp[:h, :w], wp[:h, :w] = v * wt, wt
    vs = vp.reshape(ph // 2, 2, pw // 2, 2).sum((1, 3))
    ws = wp.reshape(ph // 2, 2, pw // 2, 2).sum((1, 3))
    coarse = fill_gaps(np.where(ws > 0, vs / np.maximum(ws, 1e-12), np.nan))
    up = ndimage.zoom(coarse, 2, order=1, mode="nearest")[:h, :w]
    return np.where(np.isnan(a), up, a)


def chunk_top(cell, z, extra):
    """Per cell present in this chunk: its highest point's z and the matching value of extra."""
    order = np.lexsort((z, cell))
    c, zz, ee = cell[order], z[order], extra[order]
    last = np.r_[c[1:] != c[:-1], True]
    return c[last], zz[last], ee[last]


def main():
    name = ELEVATION["source"]
    src = SOURCES[name]
    res = float(ELEVATION["resolution"])
    k = VOXEL_SIZE / res  # raster cells per grid cell
    ni, nj = round(W * k), round(D * k)
    n = ni * nj
    lut = np.arange(256, dtype=np.uint8)
    for a, b in src["classes"].items():
        lut[a] = b

    dsm = np.full(n, -np.inf, np.float32)
    gsum, gcnt = np.zeros(n), np.zeros(n, np.uint32)
    top_z, top_cls = np.full(n, -np.inf, np.float32), np.zeros(n, np.uint8)
    tops = {g: np.full(n, -np.inf, np.float32) for g in GROUPS}
    counts = {c: np.zeros(n, np.uint32) for c in ("all", "overlap", "vegetation_nonlast", "vehicle")}
    is_group = {g: np.isin(np.arange(256), v) for g, v in GROUPS.items()}
    noise, overlap = np.isin(np.arange(256), src["noise"]), np.isin(np.arange(256), src["overlap"])
    t_min, t_max, npts, t0 = math.inf, -math.inf, 0, time.time()

    bx0, by0, bx1, by1 = world_bounds()
    files = []
    for p in sorted(Path(src["files"]).glob(src["pattern"])):
        with laspy.open(p) as f:
            h = f.header
            if h.maxs[0] < bx0 or h.mins[0] > bx1 or h.maxs[1] < by0 or h.mins[1] > by1:
                continue
            files.append(p)
            for c in f.chunk_iterator(CHUNK):
                gi, gj = to_grid(np.asarray(c.x), np.asarray(c.y))
                ii, jj = np.floor(gi * k).astype(np.int64), np.floor(gj * k).astype(np.int64)
                m = (ii >= 0) & (ii < ni) & (jj >= 0) & (jj < nj)
                if not m.any():
                    continue
                cls = lut[np.asarray(c.classification)[m]]
                z = np.asarray(c.z)[m].astype(np.float32)
                cell = jj[m] * ni + ii[m]
                ret, nret = np.asarray(c.return_number)[m], np.asarray(c.number_of_returns)[m]
                t = np.asarray(c.gps_time)[m]
                t_min, t_max, npts = min(t_min, t.min()), max(t_max, t.max()), npts + m.sum()

                keep = ~noise[cls]
                cell, z, cls, ret, nret = cell[keep], z[keep], cls[keep], ret[keep], nret[keep]
                np.add.at(counts["all"], cell, 1)
                ov = overlap[cls]
                np.add.at(counts["overlap"], cell[ov], 1)
                veh = cls == VEHICLE
                np.add.at(counts["vehicle"], cell[veh], 1)
                np.maximum.at(dsm, cell[~veh], z[~veh])
                g = cls == GROUND
                np.add.at(gsum, cell[g], z[g])
                np.add.at(gcnt, cell[g], 1)
                for name_g, sel in is_group.items():
                    s = sel[cls]
                    np.maximum.at(tops[name_g], cell[s], z[s])
                veg = is_group["vegetation"][cls] & (ret < nret)
                np.add.at(counts["vegetation_nonlast"], cell[veg], 1)
                own = ~ov
                tc, tz, tk = chunk_top(cell[own], z[own], cls[own])
                up = tz > top_z[tc]
                top_z[tc[up]], top_cls[tc[up]] = tz[up], tk[up]
        print(f"{p.name}: {npts:,} points in the AOI so far, {time.time() - t0:.0f} s", flush=True)

    shape = (nj, ni)
    nan = lambda a: np.where(np.isfinite(a), a, np.nan).astype(np.float32).reshape(shape)  # noqa: E731
    dsm = nan(dsm)
    ground = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1), np.nan).reshape(shape)
    # filled cells take a smoothed fill (the coarse levels of the fill leave steps); observed ground is untouched
    filled = fill_gaps(ground)
    dtm = np.where(np.isnan(ground), ndimage.gaussian_filter(filled, FILL_SMOOTH / res), ground).astype(np.float32)

    cls = top_cls.reshape(shape)
    has_pts = counts["all"].reshape(shape) > 0
    need = has_pts & (cls == 0)  # only overlap points: class from the nearest cell with its own points
    _, (ri, ci) = ndimage.distance_transform_edt(cls == 0, return_indices=True)
    cls = np.where(need, cls[ri, ci], cls).astype(np.uint8)

    d0, d1 = (GPS_EPOCH + dt.timedelta(seconds=float(v) + (1e9 if src["gps_adjusted"] else 0)) for v in (t_min, t_max))
    out = AREA / f"elevation_{name}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    info = dict(source=name, description=src["description"], res=res, crs=src["crs"], vertical=src["vertical"],
                dates=[d0.date().isoformat(), d1.date().isoformat()], files=[p.name for p in files], points=int(npts),
                aoi=dict(CX=CX, CY=CY, theta_deg=math.degrees(THETA), W=W, D=D, voxel=VOXEL_SIZE), crs_aoi=CRS)
    np.savez_compressed(out, dsm=dsm, dtm=dtm, ground_n=np.minimum(gcnt, 65535).astype(np.uint16).reshape(shape),
                        cls=cls, cls_filled=need,
                        **{f"top_{g}": nan(v) for g, v in tops.items()},
                        **{f"n_{c}": np.minimum(v, 65535).astype(np.uint16).reshape(shape) for c, v in counts.items()},
                        info=json.dumps(info))
    print(f"{out}: {ni} x {nj} cells of {res} m, {npts:,} points; dsm empty {np.isnan(dsm).mean() * 100:.2f} %, "
          f"ground cells {(gcnt > 0).mean() * 100:.1f} %, class from neighbours {need.mean() * 100:.1f} %, "
          f"flown {info['dates'][0]}..{info['dates'][1]}")


if __name__ == "__main__":
    main()
