"""The distant skyline: the Sierra de Guadarrama and the other ranges around Madrid, baked into a small profile the
sky shader draws (web/src/sky.ts). No terrain is drawn and nothing is fetched at run time.

Adapted from dtla-voxel's scripts/build_horizon.py (https://github.com/sigman78/dtla-voxel, commit 9eeb73e, MIT, see
LICENSE-dtla-voxel); the elevation source here is the IGN's MDT200 (CC BY 4.0) through its WCS, in EPSG:25830, with
orthometric heights like the PNOA-LiDAR the model is built from.

Input: the MDT200 within 121 km of the map's centre, downloaded once to {AREA}/horizon_mdt200.tif.
Output: web/public/data/horizon.bin, 8 rows x 2048 bearings x RGBA8, and horizon.json (its description). Bearing k is
k * 360 / 2048 degrees clockwise from true north; row r is for an eye at r * 500 m above sea level. RG is the highest
angle to the terrain 20-120 km away along that bearing, as a slope (rise over run) mapped from -0.25..0.15, and BA the
height of the terrain that sets it, 0..4095 m; both uint16, high byte first. Heights are lowered by the Earth's
curvature (no refraction).
"""
import hashlib
import json
import math
import urllib.request

import numpy as np
import rasterio
from pyproj import Geod, Transformer

from aoi import AREA, CRS, CX, CY, WEB_DATA

WCS = "https://servicios.idee.es/wcs-inspire/mdt"
COVERAGE = "Elevacion25830_200"
REACH = 121000  # metres around the centre to download
SAMPLES = 2048
MIN_DISTANCE, MAX_DISTANCE, STEP = 20000, 120000, 100
EYES = list(range(0, 3501, 500))


def fetch(path):
    if path.exists():
        return
    url = (f"{WCS}?service=WCS&request=GetCoverage&version=2.0.1&coverageId={COVERAGE}&format=image/tiff"
           f"&subset=x({CX - REACH:.0f},{CX + REACH:.0f})&subset=y({CY - REACH:.0f},{CY + REACH:.0f})")
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    if not data.startswith((b"II*\0", b"MM\0*")):
        raise RuntimeError(f"the WCS did not return a GeoTIFF: {data[:200]!r}")
    path.write_bytes(data)


def main():
    dem = AREA / "horizon_mdt200.tif"
    fetch(dem)
    lon, lat = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(CX, CY)
    bearings = np.arange(SAMPLES) * 360 / SAMPLES
    distances = np.arange(MIN_DISTANCE, MAX_DISTANCE + 1, STEP)
    az, dist = np.broadcast_arrays(bearings[:, None], distances[None, :])
    lons, lats, _ = Geod(ellps="GRS80").fwd(np.full(az.shape, lon), np.full(az.shape, lat), az, dist)
    with rasterio.open(dem) as src:
        assert src.crs.to_string() == CRS, src.crs
        x, y = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(lons, lats)
        rows, cols = rasterio.transform.rowcol(src.transform, x.ravel(), y.ravel())
        rows, cols = np.clip(rows, 0, src.height - 1), np.clip(cols, 0, src.width - 1)
        z = src.read(1).astype(np.float64)[rows, cols].reshape(az.shape)
    valid = (z > -100) & (z < 5000)
    assert valid.mean() > 0.99, f"the elevation model covers only {valid.mean():.1%} of the reach"
    # the Earth's curvature, and the envelope found again for each eye height (moving one winning peak makes spikes)
    corrected = z - dist * dist / (2 * 6371000)
    profiles, max_angles = [], []
    for eye in EYES:
        slopes = np.where(valid, (corrected - eye) / dist, -np.inf)
        ridge = np.maximum(corrected[np.arange(SAMPLES), slopes.argmax(axis=1)], 0)
        envelope = slopes.max(axis=1)
        envelope = 0.25 * np.roll(envelope, 1) + 0.5 * envelope + 0.25 * np.roll(envelope, -1)  # no single-cell needles
        heights = np.rint(np.clip(ridge / 4095, 0, 1) * 65535).astype(np.uint16)
        angles = np.rint(np.clip((envelope + 0.25) / 0.4, 0, 1) * 65535).astype(np.uint16)
        profiles.append(np.stack([angles >> 8, angles & 255, heights >> 8, heights & 255], axis=1).astype(np.uint8))
        max_angles.append(round(math.degrees(math.atan(envelope.max())), 3))
    (WEB_DATA / "horizon.bin").write_bytes(np.stack(profiles).tobytes())
    manifest = dict(source=f"{WCS} ({COVERAGE})", credit="MDT200 © Instituto Geográfico Nacional (CC BY 4.0)",
                    dem_sha256=hashlib.sha256(dem.read_bytes()).hexdigest(), center_lonlat=[round(lon, 6), round(lat, 6)],
                    samples=SAMPLES, min_distance_m=MIN_DISTANCE, max_distance_m=MAX_DISTANCE, eye_elevations_m=EYES,
                    encoding="RGBA8: RG = (slope + 0.25) / 0.4; BA = curvature-corrected elevation / 4095; uint16 big endian",
                    maximum_angles_deg=max_angles)
    (WEB_DATA / "horizon.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
