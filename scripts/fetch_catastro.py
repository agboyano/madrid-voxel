"""Catastro INSPIRE buildings over the AOI -> {AREA}/catastro/buildings.geojson and building_parts.geojson

Source: Dirección General del Catastro, INSPIRE Buildings WFS (https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx),
municipality of Madrid (INE 28079). The WFS answers bounding-box queries, so only the AOI plus MARGIN is read, in
tiles of at most TILE metres; each tile's GML is cached. Features crossing tiles are merged by their INSPIRE id.

- Building: the footprint of a cadastral building, with year of construction, current use, condition and counts
  of dwellings and units. Its own floor count is unpopulated in Madrid.
- BuildingPart: the footprint of each volume of a building with its number of floors above and below ground; the
  floors of a building come from its parts (building_id links them).

Geometry is EPSG:25830, (x, y) order. Field names from the INSPIRE schema are mapped to English keys here.

usage: PYTHONPATH=scripts uv run python scripts/fetch_catastro.py
"""
import json
import math
import sys
import time
import xml.etree.ElementTree as ET

import requests

from aoi import AREA, CRS, world_bounds

WFS = "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
UA = {"User-Agent": "madrid-voxel/0.1"}
MARGIN = 50  # metres around the AOI
TILE = 500  # metres per query, well under the service's area limit
MIN_TILE = 60  # metres: the smallest tile a failing one is split into
SKIPPED = []  # [type, bbox] of the tiles the service failed on at MIN_TILE
DIR = AREA / "catastro"
NS = {"gml": "http://www.opengis.net/gml/3.2",
      "bu-core2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-core2d/2.0",
      "bu-ext2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-ext2d/2.0"}
GML_ID = "{http://www.opengis.net/gml/3.2}id"


def get_tile(type_name, bb, path, rounds=3):
    """The tile's GML, cached; None if the service keeps failing on it. Dense tiles sometimes come back with the
    document's start replaced by an "Object moved" error page: not XML, so it counts as a failure."""
    if path.exists():
        return path.read_bytes()
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": type_name,
              "srsName": "EPSG::25830", "bbox": ",".join(f"{v:.1f}" for v in bb) + ",EPSG::25830"}
    for attempt in range(rounds):
        try:
            r = requests.get(WFS, params=params, headers=UA, timeout=300)
            if r.ok and r.content.lstrip().startswith(b"<?xml") and b"FeatureCollection" in r.content[:2000]:
                path.write_bytes(r.content)
                return r.content
            print(f"  retry {type_name} {r.status_code}: {r.text[:120]!r}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  retry {type_name}: {e}", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    return None


def tile_features(type_name, bb, path, depth=0):
    """The features of one tile; a tile the service fails on is split in four (cached as path_0..path_3), down to
    MIN_TILE metres. A tile that still fails holds a record the service cannot serve: it is skipped and listed in
    SKIPPED (the LiDAR heights stand there; only Catastro's floors are missing)."""
    data = get_tile(type_name, bb, path)
    if data is not None:
        return ET.fromstring(data).iterfind(f".//bu-ext2d:{type_name.split(':')[1]}", NS)
    x0, y0, x1, y1 = bb
    if x1 - x0 <= MIN_TILE:
        print(f"  {type_name} tile {bb} skipped: the service fails on it", file=sys.stderr)
        SKIPPED.append([type_name, [round(v, 1) for v in bb]])
        return []
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    quads = [(x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)]
    print(f"  {type_name} tile {bb} split in four", file=sys.stderr)
    return [f for k, q in enumerate(quads) for f in tile_features(type_name, q, path.with_name(f"{path.stem}_{k}.gml"), depth + 1)]


def ring(el):
    v = [float(t) for t in el.find(".//gml:posList", NS).text.split()]
    return [[v[k], v[k + 1]] for k in range(0, len(v), 2)]


def geometry(feat):
    polys = []
    for patch in feat.iterfind(".//gml:PolygonPatch", NS):
        rings = [ring(patch.find("gml:exterior", NS))] + [ring(r) for r in patch.iterfind("gml:interior", NS)]
        polys.append(rings)
    return {"type": "MultiPolygon", "coordinates": polys}


def text(feat, path, conv=None):
    el = feat.find(path, NS)
    if el is None or el.text is None or not el.text.strip():
        return None
    v = el.text.strip()
    return conv(v) if conv else v


def year(v):
    """Year of an ISO-like date; Catastro writes years before 1000 with three digits ("979-01-01...")."""
    return int(v.split("-", 1)[0])


def building(feat):
    return {"id": feat.get(GML_ID).removeprefix("ES.SDGC.BU."),
            "year_built": text(feat, ".//bu-core2d:dateOfConstruction//bu-core2d:beginning", year),
            "condition": text(feat, "bu-core2d:conditionOfConstruction"),
            "current_use": text(feat, "bu-ext2d:currentUse"),
            "dwellings": text(feat, "bu-ext2d:numberOfDwellings", int),
            "units": text(feat, "bu-ext2d:numberOfBuildingUnits", int),
            "area_m2": text(feat, ".//bu-ext2d:OfficialArea/bu-ext2d:value", float)}


def building_part(feat):
    pid = feat.get(GML_ID).removeprefix("ES.SDGC.BU.")
    return {"id": pid, "building_id": pid.rsplit("_part", 1)[0],
            "floors_above": text(feat, "bu-ext2d:numberOfFloorsAboveGround", int),
            "floors_below": text(feat, "bu-ext2d:numberOfFloorsBelowGround", int),
            "height_below_m": text(feat, "bu-ext2d:heightBelowGround", float)}


def collect(type_name, props, tiles):
    tag = type_name.split(":")[1]
    feats = {}
    for k, bb in enumerate(tiles):
        for f in tile_features(type_name, bb, DIR / f"{tag}_{k}.gml"):
            feats.setdefault(f.get(GML_ID), {"type": "Feature", "properties": props(f), "geometry": geometry(f)})
    return list(feats.values())


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = world_bounds(MARGIN)
    nx, ny = math.ceil((x1 - x0) / TILE), math.ceil((y1 - y0) / TILE)
    tiles = [(x0 + i * TILE, y0 + j * TILE, min(x0 + (i + 1) * TILE, x1), min(y0 + (j + 1) * TILE, y1))
             for i in range(nx) for j in range(ny)]
    for type_name, props, name in (("BU:Building", building, "buildings"),
                                   ("BU:BuildingPart", building_part, "building_parts")):
        feats = collect(type_name, props, tiles)
        out = DIR / f"{name}.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "crs": CRS, "features": feats,
                                   "skipped": [b for t, b in SKIPPED if t == type_name]}))
        print(f"{len(feats)} {name} from {len(tiles)} tile(s) -> {out}")


if __name__ == "__main__":
    main()
