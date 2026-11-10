"""Catastro INSPIRE buildings and building parts (fetch_catastro.py) in grid coordinates.

Used by voxelize.py beside the OSM footprints: OSM outlines carry the tags (names, wikidata, colours, building types)
and the part structure the fusion relies on, Catastro the number of floors of every volume. See DECISIONS.md.
"""
import json
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.strtree import STRtree

from aoi import RAW, to_grid

DIR = Path(RAW) / "catastro"
FLOOR_H = 3.2  # metres per floor above ground, as voxelize.py takes for OSM building:levels


def _grid_geom(g):
    polys = []
    for rings in g["coordinates"]:
        conv = [[tuple(float(v) for v in to_grid(x, y)) for x, y in ring] for ring in rings]
        p = Polygon(conv[0], conv[1:]).buffer(0)
        if not p.is_empty:
            polys.append(p)
    return MultiPolygon([q for p in polys for q in getattr(p, "geoms", [p])]) if polys else None


def load(name):
    """[(id, properties, geometry in grid coords)] of buildings.geojson or building_parts.geojson; [] if absent."""
    f = DIR / f"{name}.geojson"
    if not f.exists():
        return []
    out = []
    for feat in json.load(open(f))["features"]:
        geom = _grid_geom(feat["geometry"])
        if geom is not None:
            out.append((feat["properties"]["id"], feat["properties"], geom))
    return out


class Floors:
    """Floors above ground of the Catastro parts under a footprint: the most common count by area."""

    def __init__(self):
        self.parts = load("building_parts")
        self.tree = STRtree([g for _, _, g in self.parts]) if self.parts else None

    def under(self, geom, min_share=0.5):
        if self.tree is None:
            return None
        area = {}
        for k in self.tree.query(geom, predicate="intersects"):
            _, props, g = self.parts[k]
            n = props.get("floors_above")
            if n:
                area[n] = area.get(n, 0.0) + g.intersection(geom).area
        if not area or sum(area.values()) < min_share * geom.area:
            return None
        return max(area, key=lambda k: area[k])
