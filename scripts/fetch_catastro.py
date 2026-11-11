"""Catastro INSPIRE buildings over the AOI -> {AREA}/catastro/buildings.geojson and building_parts.geojson

Source: Dirección General del Catastro, INSPIRE Buildings WFS (https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx),
municipality of Madrid (INE 28079). The WFS answers bounding-box queries, so only the AOI plus MARGIN is read, in
tiles of TILE metres on a fixed world grid (GRID_ORIGIN), cached by coordinates in {RAW}/catastro_tiles and shared
by every area, so a new or rotated AOI only downloads the tiles it adds. Features crossing tiles are merged by their
INSPIRE id.

- Building: the footprint of a cadastral building, with year of construction, current use, condition and counts
  of dwellings and units. Its own floor count is unpopulated in Madrid.
- BuildingPart: the footprint of each volume of a building with its number of floors above and below ground; the
  floors of a building come from its parts (building_id links them).

A record the WFS cannot serve fails every query that touches it (four 31 m squares near Calle de Toledo do): the
features of such tiles are read instead from Catastro's ATOM download for the municipality (ATOM_URL, 117 MB, the
smallest file Catastro offers), downloaded once to {RAW}/catastro_atom only when a tile was skipped, and listed under
"filled_from_atom".

Geometry is EPSG:25830, (x, y) order. Field names from the INSPIRE schema are mapped to English keys here.

usage: PYTHONPATH=scripts uv run python scripts/fetch_catastro.py
"""
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

from aoi import AREA, CRS, RAW, world_bounds

WFS = "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
UA = {"User-Agent": "madrid-voxel/0.1"}
MARGIN = 50  # metres around the AOI
TILE = 500  # metres per query, well under the service's area limit
MIN_TILE = 60  # metres: the smallest tile a failing one is split into
SKIPPED = []  # [type, bbox] of the tiles the service failed on at MIN_TILE
DIR = AREA / "catastro"
TILES = Path(RAW) / "catastro_tiles"
GRID_ORIGIN = (438950.0, 4472900.0)  # EPSG:25830; tiles start at multiples of TILE from here
NS = {"gml": "http://www.opengis.net/gml/3.2",
      "bu-core2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-core2d/2.0",
      "bu-ext2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-ext2d/2.0"}
GML_ID = "{http://www.opengis.net/gml/3.2}id"
ATOM_URL = "https://www.catastro.hacienda.gob.es/INSPIRE/Buildings/28/28900-MADRID/A.ES.SDGC.BU.28900.zip"
ATOM = Path(RAW) / "catastro_atom" / ATOM_URL.rsplit("/", 1)[1]


def get_tile(type_name, bb, path, rounds=3):
    """The tile's GML, cached; None if the service keeps failing on it. Dense tiles sometimes come back with the
    document's start replaced by an "Object moved" error page: not XML, so it counts as a failure."""
    if path.exists():
        return path.read_bytes()
    failed = path.with_suffix(".failed")  # the service failed on this tile before: go straight to its quarters
    if failed.exists():
        return None
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
    failed.touch()
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


def atom_features(type_name, boxes):
    """The features of type_name in Catastro's ATOM file for the municipality that reach into any of boxes."""
    if not ATOM.exists():
        ATOM.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {ATOM_URL}", file=sys.stderr)
        with requests.get(ATOM_URL, headers=UA, timeout=600, stream=True) as r:
            r.raise_for_status()
            tmp = ATOM.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.rename(ATOM)
    tag = type_name.split(":")[1]
    member = {"Building": ".building.gml", "BuildingPart": ".buildingpart.gml"}[tag]
    with zipfile.ZipFile(ATOM) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(member))
        with z.open(name) as fh:
            for _, el in ET.iterparse(fh):
                if el.tag != f"{{{NS['bu-ext2d']}}}{tag}":
                    continue
                pts = [float(v) for p in el.iterfind(".//gml:posList", NS) for v in p.text.split()]
                xs, ys = pts[0::2], pts[1::2]
                if any(min(xs) < b[2] and max(xs) > b[0] and min(ys) < b[3] and max(ys) > b[1] for b in boxes):
                    yield el
                else:
                    el.clear()


def collect(type_name, props, tiles):
    tag = type_name.split(":")[1]
    feats = {}
    for k, bb in enumerate(tiles):
        for f in tile_features(type_name, bb, TILES / f"{tag}_{bb[0]:.0f}_{bb[1]:.0f}_{bb[2]:.0f}_{bb[3]:.0f}.gml"):
            feats.setdefault(f.get(GML_ID), {"type": "Feature", "properties": props(f), "geometry": geometry(f)})
    skipped = [b for t, b in SKIPPED if t == type_name]
    filled = 0
    for f in atom_features(type_name, skipped) if skipped else []:
        if f.get(GML_ID) not in feats:
            feats[f.get(GML_ID)] = {"type": "Feature", "properties": props(f), "geometry": geometry(f)}
            filled += 1
    if skipped:
        print(f"  {filled} {type_name} features of the skipped tiles from the ATOM file", file=sys.stderr)
    return list(feats.values()), filled


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    TILES.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = world_bounds(MARGIN)
    gx, gy = GRID_ORIGIN
    i0, i1 = math.floor((x0 - gx) / TILE), math.ceil((x1 - gx) / TILE)
    j0, j1 = math.floor((y0 - gy) / TILE), math.ceil((y1 - gy) / TILE)
    tiles = [(gx + i * TILE, gy + j * TILE, gx + (i + 1) * TILE, gy + (j + 1) * TILE)
             for i in range(i0, i1) for j in range(j0, j1)]
    for type_name, props, name in (("BU:Building", building, "buildings"),
                                   ("BU:BuildingPart", building_part, "building_parts")):
        feats, filled = collect(type_name, props, tiles)
        out = DIR / f"{name}.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "crs": CRS, "features": feats,
                                   "skipped": [b for t, b in SKIPPED if t == type_name],
                                   "filled_from_atom": filled}))
        print(f"{len(feats)} {name} from {len(tiles)} tile(s) -> {out}")


if __name__ == "__main__":
    main()
