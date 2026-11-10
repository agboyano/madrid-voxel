"""Most recent PNOA orthophoto over the AOI -> {AREA}/ortho/ortho.tif (+ ortho.json with flight dates)

Source: IGN WMS "Ortofotos PNOA máxima actualidad" (https://www.ign.es/wms-inspire/pnoa-ma, layer
OI.OrthoimageCoverage; IGN/CNIG, CC BY 4.0). The WMS serves the newest PNOA flight for each area; the layer
OI.MosaicElement gives each area's acquisition date and resolution, which are sampled over the AOI and recorded.

The image is requested at RES metres per pixel (the native resolution), axis-aligned in EPSG:25830, in tiles of at
most MAX_PX pixels; tiles are cached as PNG and assembled into one GeoTIFF. Warping onto the rotated grid happens
in the raster preparation step (aoi.grid_transform), not here, so a new rotation needs no new download.

usage: PYTHONPATH=scripts uv run python scripts/fetch_ortho.py
"""
import json
import math
import sys
import time

import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.transform import from_origin

from aoi import AREA, CRS, D, W, to_world, world_bounds

WMS = "https://www.ign.es/wms-inspire/pnoa-ma"
LAYER, INFO_LAYER = "OI.OrthoimageCoverage", "OI.MosaicElement"
UA = {"User-Agent": "madrid-voxel/0.1"}
RES = 0.25  # metres per pixel, the PNOA native resolution over Madrid
MARGIN = 50  # metres around the AOI
MAX_PX = 4000  # the service allows 4096
DIR = AREA / "ortho"
OUT = DIR / "ortho.tif"


def request(params, expect):
    base = {"service": "WMS", "version": "1.3.0", "crs": "EPSG:25830", "styles": ""}
    for attempt in range(5):
        try:
            r = requests.get(WMS, params={**base, **params}, headers=UA, timeout=300)
            if r.ok and r.headers.get("content-type", "").startswith(expect):
                return r
            print(f"  retry {r.status_code} {r.headers.get('content-type')}: {r.text[:200]}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  retry: {e}", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    raise SystemExit("fetch_ortho: WMS request failed")


def get_tile(bb, w, h, path):
    if not path.exists():
        r = request({"request": "GetMap", "layers": LAYER, "bbox": ",".join(f"{v:.2f}" for v in bb),
                     "width": w, "height": h, "format": "image/png"}, "image/png")
        path.write_bytes(r.content)
    return np.asarray(Image.open(path).convert("RGB"))


def flight_dates():
    """Acquisition date and resolution of the mosaic at the AOI centre and corners, grouped."""
    found = {}
    for i, j in [(0.5, 0.5), (0, 0), (1, 0), (1, 1), (0, 1)]:
        x, y = to_world(i * W, j * D)
        r = request({"request": "GetFeatureInfo", "layers": INFO_LAYER, "query_layers": INFO_LAYER,
                     "bbox": f"{x - 5:.2f},{y - 5:.2f},{x + 5:.2f},{y + 5:.2f}", "width": 10, "height": 10,
                     "i": 5, "j": 5, "info_format": "application/json"}, "application/json")
        for f in r.json().get("features", []):
            p = f["properties"]
            found.setdefault((p.get("Fecha"), p.get("Resolucion")), []).append([round(float(x), 1), round(float(y), 1)])
    return [{"date": d, "resolution_m": float(res) if res else None, "sampled_at": pts} for (d, res), pts in found.items()]


def main():
    if OUT.exists():
        print(f"ortho cached {OUT}")
        return
    DIR.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = world_bounds(MARGIN)
    # snap to the pixel grid so tiles line up exactly
    x0, y0 = math.floor(x0 / RES) * RES, math.floor(y0 / RES) * RES
    w_px, h_px = math.ceil((x1 - x0) / RES), math.ceil((y1 - y0) / RES)
    img = np.zeros((h_px, w_px, 3), np.uint8)
    for r0 in range(0, h_px, MAX_PX):
        for c0 in range(0, w_px, MAX_PX):
            w, h = min(MAX_PX, w_px - c0), min(MAX_PX, h_px - r0)
            top = y0 + (h_px - r0) * RES
            bb = (x0 + c0 * RES, top - h * RES, x0 + (c0 + w) * RES, top)
            img[r0:r0 + h, c0:c0 + w] = get_tile(bb, w, h, DIR / f"tile_{r0}_{c0}.png")
    tmp = OUT.with_suffix(".tif.part")
    with rasterio.open(tmp, "w", driver="GTiff", width=w_px, height=h_px, count=3, dtype="uint8", crs=CRS,
                       transform=from_origin(x0, y0 + h_px * RES, RES, RES), compress="deflate",
                       photometric="RGB", tiled=True) as dst:
        dst.write(img.transpose(2, 0, 1))
    tmp.rename(OUT)
    dates = flight_dates()
    (DIR / "ortho.json").write_text(json.dumps({"source": f"{WMS} {LAYER}", "crs": CRS, "resolution_m": RES,
                                                "flights": dates}, indent=1))
    print(f"ortho {w_px} x {h_px} px at {RES} m -> {OUT}; flights {[(d['date'], d['resolution_m']) for d in dates]}")


if __name__ == "__main__":
    main()
