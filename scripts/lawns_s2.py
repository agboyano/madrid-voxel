"""Madrid's lawns through the year, from Sentinel-2: irrigated lawns and dry meadows, a colour per month for each.

Madrid waters its park lawns, which stay green all summer, but not its meadows and verges, which turn the colour of
straw by July. Warsaw's lawn colours (scripts/grass_photos.json) know neither. This measures both over the AOI:

  scenes    Sentinel-2 L2A over the AOI, 2022-2024, cloud cover < 20 %, from the Microsoft Planetary Computer STAC
            (public; the assets are read through its anonymous SAS token). One scene per date (reprocessed copies of the
            same acquisition are dropped). Bands B02, B03, B04, B08 at 10 m and the scene classification (SCL) at 20 m,
            read only over the AOI's window and cached per scene in {RAW}/sentinel2/.
  lawn      a 10 m pixel counts when at least LAWN_SHARE of its 1 m grid cells are lawn: inside an OSM lawn, meadow, park
            or garden (most of the Retiro's lawns are not mapped on their own), without a LiDAR tree (class 3-5) and without a
            building, and the pixel is green in spring (March-May median NDVI at least GREEN_NDVI): a meadow that never
            greens is bare ground or gravel. Cloud, shadow, snow and water (SCL) are left out per scene.
  dry       a lawn pixel whose median NDVI in July-August is under DRY_NDVI.
  colours   per month and class, the median reflectance (B04, B03, B02) of the lawn pixels over all scenes of that month,
            with the processing-baseline offset removed (DN - 1000 from baseline 04.00 on).

Output: {AREA}/lawns_s2.json (monthly linear-RGB reflectance per class, pixel counts, thresholds) and
{AREA}/lawns_s2.npz (dry: bool per 2 m cell of the foliage grid, as phenology.py writes foliage.bin).

usage: PYTHONPATH=scripts uv run python scripts/lawns_s2.py
"""
import json
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

from aoi import AREA, RAW, D, W, bbox_lonlat, to_world, world_bounds
from osm import OSM

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-2-l2a"
YEARS = (2022, 2023, 2024)
MAX_CLOUD = 20
BANDS = ("B02", "B03", "B04", "B08")
SCL_OK = (4, 5)  # vegetation, not vegetated; cloud, shadow, snow, water and saturated pixels are left out
LAWN_SHARE = 0.8
DRY_NDVI = 0.45
GREEN_NDVI = 0.5
CACHE = Path(RAW) / "sentinel2"
LAWN_TAGS = {"landuse": ("grass", "meadow", "village_green", "greenfield"), "natural": ("grassland",),
             "leisure": ("park", "garden")}


def get_json(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "madrid-voxel lawns"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def scenes():
    s, w, n, e = bbox_lonlat()
    out = {}
    for year in YEARS:
        body = {"collections": ["sentinel-2-l2a"], "bbox": [w, s, e, n], "datetime": f"{year}-01-01/{year}-12-31",
                "query": {"eo:cloud_cover": {"lt": MAX_CLOUD}}, "limit": 1000}
        for f in get_json(STAC, body)["features"]:
            date = f["properties"]["datetime"][:10]
            if f["properties"].get("s2:mgrs_tile") == "30TVK":
                out.setdefault(date, f)  # one scene per acquisition date
    return [out[d] for d in sorted(out)]


def read_scene(f, token, bounds):
    path = CACHE / f"{f['id']}.npz"
    if path.exists():
        z = np.load(path)
        return {k: z[k] for k in z.files}
    arrs = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for b in BANDS + ("SCL",):
            with rasterio.open(f["assets"][b]["href"] + "?" + token) as src:
                win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                if b == "SCL":  # 20 m: onto the 10 m pixels of the bands
                    shape = arrs["B02"].shape
                    arrs[b] = src.read(1, window=win, out_shape=shape, resampling=Resampling.nearest)
                else:
                    arrs[b] = src.read(1, window=win)
                    if b == "B02":
                        arrs["transform"] = np.array(src.window_transform(win))[:6]
        base = f["properties"].get("s2:processing_baseline", "00.00")
    arrs["offset"] = np.array(1000 if base >= "04.00" else 0)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrs)
    time.sleep(0.2)
    return arrs


def lawn_cells(osm):
    """bool (D, W): 1 m grid cells of open lawn (OSM lawn, meadow or park; no LiDAR tree, no building)."""
    shapes = [(g, 1) for key, vals in LAWN_TAGS.items() for _, _, _, g in osm.areas_with(key, vals)]
    lawn = features.rasterize(shapes, out_shape=(D, W), transform=rasterio.Affine.identity(), dtype=np.uint8) > 0
    bld = features.rasterize([(g, 1) for _, _, _, g in osm.areas_with("building")], out_shape=(D, W),
                             transform=rasterio.Affine.identity(), dtype=np.uint8) > 0
    cls = np.load(AREA / "prep.npz")["cls"]
    return lawn & ~bld & ~np.isin(cls, (3, 4, 5))


def pixel_of(transform, shape, cols, rows):
    """S2 pixel (row, col) of grid points; -1 outside."""
    x, y = to_world(cols, rows)
    t = rasterio.Affine(*transform)
    c, r = ~t * (x, y)
    r, c = np.floor(r).astype(int), np.floor(c).astype(int)
    ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
    return np.where(ok, r, -1), np.where(ok, c, -1)


def main():
    feats = scenes()
    print(f"{len(feats)} scenes ({MAX_CLOUD} % cloud at most, {YEARS[0]}-{YEARS[-1]})")
    token = get_json(TOKEN)["token"]
    bounds = world_bounds(30)
    data = [(f["properties"]["datetime"][:10], read_scene(f, token, bounds)) for f in feats]
    shape, transform = data[0][1]["B02"].shape, data[0][1]["transform"]

    # lawn pixels: share of open-lawn 1 m cells per 10 m pixel
    lawn = lawn_cells(OSM())
    rr, cc = np.mgrid[0:D, 0:W]
    pr, pc = pixel_of(transform, shape, cc + 0.5, rr + 0.5)
    ok = pr >= 0
    flat = pr[ok] * shape[1] + pc[ok]
    n_all = np.bincount(flat, minlength=shape[0] * shape[1])
    n_lawn = np.bincount(flat, weights=lawn[ok], minlength=shape[0] * shape[1])
    is_lawn = (n_all >= 50) & (n_lawn >= LAWN_SHARE * np.maximum(n_all, 1))
    is_lawn = is_lawn.reshape(shape)

    # reflectance per scene, per month
    month = defaultdict(list)
    for date, a in data:
        if a["B02"].shape != shape:
            continue
        refl = np.stack([(a[b].astype(np.float32) - a["offset"]) / 10000 for b in ("B04", "B03", "B02", "B08")], -1)
        refl[~np.isin(a["SCL"], SCL_OK) | (a["B02"] == 0)] = np.nan
        month[int(date[5:7])].append(refl)
    med = {m: np.nanmedian(np.stack(v), 0) for m, v in month.items()}
    nd = lambda r: (r[..., 3] - r[..., 0]) / np.maximum(r[..., 3] + r[..., 0], 1e-6)  # noqa: E731
    spring = nd(np.nanmedian(np.stack([med[m] for m in (3, 4, 5)]), 0))
    ndvi = nd(np.nanmedian(np.stack([med[m] for m in (7, 8)]), 0))
    is_lawn &= spring >= GREEN_NDVI
    dry = is_lawn & (ndvi < DRY_NDVI)
    wet = is_lawn & (ndvi >= DRY_NDVI)
    series = {}
    for name, mask in (("irrigated", wet), ("dry", dry)):
        series[name] = [[round(float(v), 4) for v in np.nanmedian(med[m][mask][:, :3], 0)] for m in range(1, 13)]
    out = dict(source="Copernicus Sentinel-2 L2A (Microsoft Planetary Computer), " + f"{YEARS[0]}-{YEARS[-1]}",
               scenes=len(data), scenes_per_month={m: len(v) for m, v in sorted(month.items())},
               pixels=dict(irrigated=int(wet.sum()), dry=int(dry.sum())), dry_ndvi=DRY_NDVI, green_ndvi=GREEN_NDVI,
               lawn_share=LAWN_SHARE,
               linear_rgb=series)
    (AREA / "lawns_s2.json").write_text(json.dumps(out, indent=1))

    # the dry mask on the 2 m foliage grid (phenology.py: foliage.bin)
    gy, gx = np.mgrid[0:D // 2, 0:W // 2]
    fr, fc = pixel_of(transform, shape, gx * 2 + 1.0, gy * 2 + 1.0)
    dry2 = np.where(fr >= 0, dry[np.maximum(fr, 0), np.maximum(fc, 0)], False)
    np.savez_compressed(AREA / "lawns_s2.npz", dry=dry2)
    print(f"lawn pixels: {int(wet.sum())} irrigated, {int(dry.sum())} dry (July-August NDVI < {DRY_NDVI}); "
          f"2 m cells marked dry: {int(dry2.sum())}")
    for name in series:
        print(name, [("%.3f %.3f %.3f" % tuple(v)) for v in series[name][5:9]])


if __name__ == "__main__":
    main()
