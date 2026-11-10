"""The rasters voxelize.py reads (data/prep.npz), from the common elevation format and the orthophoto.

Replaces Warsaw's GUGiK mosaic. Inputs: {AREA}/elevation_<source>.npz (prep_lidar.py) and
{AREA}/ortho/ortho.tif (fetch_ortho.py). Output, row 0 = grid row 0, cell centres (the contract in NOTES.md):
  dsm   float32 (2D, 2W)  0.5 m  absolute surface height; NaN where the cloud has no point
  dtm   float32 (D, W)    1 m    absolute ground height, no gaps
  orto  uint8   (5D, 5W, 3) 0.2 m sRGB
  cls   uint8   (D, W)    1 m    canonical point class of each cell (prep_lidar.py), for the Madrid additions to the
                                 fusion; Warsaw's voxelize.py did not have it
The elevation rasters are resampled from the configured resolution to these fixed cell sizes by nearest neighbour
(at 1 m the DSM is each cell repeated 2 x 2, so the ratio voxelize.py hard-codes is kept without inventing detail);
the orthophoto is read north-up and sampled on the rotated grid with bilinear interpolation.

usage: PYTHONPATH=scripts uv run python scripts/prep.py
"""
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage

from aoi import AREA, CX, CY, D, THETA, VOXEL_SIZE, W, to_world
from config import ELEVATION

OUT = Path("data/prep.npz")
DSM_RES, DTM_RES, ORTO_RES = 0.5, 1.0, 0.2  # metres, fixed by voxelize.py


def regrid(a, src_res, out_res):
    """Nearest-neighbour resample of a grid-aligned raster between cell sizes (both in metres, same origin)."""
    nj, ni = round(D * VOXEL_SIZE / out_res), round(W * VOXEL_SIZE / out_res)
    j = np.minimum(((np.arange(nj) + 0.5) * out_res / src_res).astype(int), a.shape[0] - 1)
    i = np.minimum(((np.arange(ni) + 0.5) * out_res / src_res).astype(int), a.shape[1] - 1)
    return a[j[:, None], i[None, :]]


def sample_north_up(path, out_res, band=1024):
    """Bilinear samples of a north-up RGB GeoTIFF at the centres of the rotated grid's cells of out_res metres."""
    with rasterio.open(path) as r:
        img, inv = r.read(), ~r.transform
    nj, ni = round(D * VOXEL_SIZE / out_res), round(W * VOXEL_SIZE / out_res)
    out = np.empty((nj, ni, img.shape[0]), np.uint8)
    k = out_res / VOXEL_SIZE  # grid cells per output cell
    for j0 in range(0, nj, band):
        jj, ii = np.mgrid[j0:min(j0 + band, nj), 0:ni].astype(np.float64)
        x, y = to_world((ii + 0.5) * k, (jj + 0.5) * k)
        col, row = inv * (x, y)
        for b in range(img.shape[0]):
            out[j0:j0 + band, :, b] = np.clip(np.round(ndimage.map_coordinates(
                img[b].astype(np.float32), [row - 0.5, col - 0.5], order=1, mode="nearest")), 0, 255)
    return out


def main():
    z = np.load(AREA / f"elevation_{ELEVATION['source']}.npz")
    info = json.loads(str(z["info"]))
    a = info["aoi"]
    if (a["CX"], a["CY"], a["W"], a["D"], a["voxel"]) != (CX, CY, W, D, VOXEL_SIZE) or \
            abs(a["theta_deg"] - np.degrees(THETA)) > 1e-9:
        raise SystemExit("prep: elevation rasters were built for another AOI; re-run prep_lidar.py")
    res = info["res"]
    dsm = regrid(z["dsm"], res, DSM_RES).astype(np.float32)
    dtm = regrid(z["dtm"], res, DTM_RES).astype(np.float32) if res <= DTM_RES else \
        ndimage.zoom(z["dtm"], res / DTM_RES, order=1).astype(np.float32)
    cls = regrid(z["cls"], res, DTM_RES)
    orto = sample_north_up(AREA / "ortho" / "ortho.tif", ORTO_RES)
    assert dsm.shape == (2 * D, 2 * W) and dtm.shape == (D, W) and orto.shape == (5 * D, 5 * W, 3)
    assert not np.isnan(dtm).any(), "the DTM must have no gaps"
    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(OUT, dsm=dsm, dtm=dtm, orto=orto, cls=cls)
    print(f"{OUT}: dsm {dsm.shape} ({np.isnan(dsm).mean() * 100:.2f} % empty), dtm {dtm.shape} "
          f"{dtm.min():.1f}-{dtm.max():.1f} m, orto {orto.shape}; from {info['source']} at {res} m")


if __name__ == "__main__":
    main()
