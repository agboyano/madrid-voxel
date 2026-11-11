"""Every label on the map and how far away it shows, from the OSM features linked to Wikidata (fetch_wikidata.py).

Labels show the Spanish name (the OSM name, as on the street signs; Wikidata's Spanish label when OSM has none), with
the English one under it where it differs, and the facts for the info card (year, architects, height, style, heritage
designation, website, Wikipedia). Which features get a label:
  required  REQUIRED in fetch_wikidata.py (PLAN.md Phase 4): always, seen from anywhere on the map (far 9000)
  extended  places, not boundaries, routes, streets or chains: buildings, monuments, squares, parks, places of
            worship, museums and theatres whose item has a heritage designation or a Wikipedia article; the closer the
            camera must be, the less known the place (far 2500 / 1300 / 600). EXTENDED_EXCLUDE drops items by id.
Curated labels from landmarks.py (LABELS, EXTRA_LABELS, overrides.json) come first and win over Wikidata.
`far` is the camera distance (m) up to which a label shows.
"""
import json

import numpy as np
from scipy import ndimage

from aoi import AREA, W, D
from fetch_wikidata import ENGLISH_NAMES, REQUIRED

WIKIDATA = AREA / "wikidata.json"
EXTENDED_EXCLUDE = set()  # qids proposed for the extended set and turned down (DECISIONS.md)
# Wikidata types (instance of) of items that are not the place itself, though an OSM element points to them: the person a
# tomb or statue honours, the event a memorial recalls, the body that sits in a building
NOT_PLACE_TYPES = {"human", "mass shooting", "murder", "massacre", "terrorist attack", "battle", "event", "organization",
                   "autonomous government", "government", "company", "business", "neighborhood of Madrid", "street",
                   "rapid transit line", "commuter rail service", "Stolperstein", "commemorative inscription",
                   "water depth", "remarkable tree"}
# what an OSM element is, for the label's kind and for whether it is a place at all
PLACE_TAGS = [("place", ("square",)), ("historic", None), ("tourism", ("museum", "attraction", "gallery", "artwork", "viewpoint")),
              ("amenity", ("place_of_worship", "theatre", "townhall", "library", "university", "arts_centre", "cinema",
                           "fountain", "courthouse", "post_office", "marketplace", "college", "school", "hospital")),
              ("building", ("cathedral", "church", "chapel", "palace", "government", "public", "civic",
                            "train_station", "museum", "monastery", "convent")),
              ("leisure", ("park", "garden")), ("man_made", ("tower", "obelisk")),
              ("railway", ("station",)), ("office", ("government",)), ("building", None)]
NOT_PLACES = ("boundary", "route", "highway", "brand", "shop", "admin_level", "waterway", "public_transport")
# building=* values that say little about a landmark: the Wikidata type (instance of) names it better
GENERIC = {"building", "commercial", "retail", "public", "house", "government", "apartments", "residential", "office",
           "civic"}


def cap(s):
    """Wikidata labels of common nouns start in lower case ("plaza de la Provincia"); a map label does not. English
    labels often end in ", Madrid" to tell them from namesakes elsewhere; on a map of Madrid that is noise. A stray full
    stop at the end of an OSM name goes too ("Hospital General Universitario Gregorio Marañón.")."""
    if not s:
        return s
    s = s.removesuffix(", Madrid").removesuffix(".")
    return s[:1].upper() + s[1:]


def kind_of(t):
    for k, vals in PLACE_TAGS:
        v = t.get(k)
        if v and v != "no" and (vals is None or v in vals):
            v = "building" if v == "yes" else v
            return v.replace("_", " ") if k != "historic" else ("monument" if v in ("yes", "memorial") else v.replace("_", " "))
    return None


def _tagged(osm):
    """qid -> [(tags, geometry)] of the OSM elements that carry it, areas first, largest first."""
    out = {}
    for _, _, t, g in osm.areas:
        if t.get("wikidata"):
            out.setdefault(t["wikidata"], []).append((t, g))
    for src in (osm.lines, osm.nodes):
        for _, t, g in src:
            if t.get("wikidata"):
                out.setdefault(t["wikidata"], []).append((t, g))
    for q in out:
        out[q].sort(key=lambda tg: -tg[1].area)
    return out


def _anchor(geom, top_at, tall):
    """The label's cell: a tall building's highest cell, else a point inside the shape (its centroid if inside)."""
    from shapely.geometry import Point
    if tall and geom.area > 0:
        minx, miny, maxx, maxy = geom.bounds
        best = None
        for r in range(max(int(miny), 0), min(int(maxy) + 1, D)):
            for c in range(max(int(minx), 0), min(int(maxx) + 1, W)):
                if geom.contains(Point(c + 0.5, r + 0.5)):
                    z = top_at(r, c)
                    if best is None or z > best[0]:
                        best = (z, r, c)
        if best:
            return best[2], best[1]
    p = geom.centroid if geom.area > 0 and geom.contains(geom.centroid) else geom.representative_point()
    return int(p.x), int(p.y)


def label(qid, f, t, geom, top_at, far):
    en, es = cap(ENGLISH_NAMES.get(qid) or f.get("en") or t.get("name:en")), cap(t.get("name") or f.get("es"))
    name = es or en
    kind = kind_of(t)
    if kind is None or (kind in GENERIC and f.get("types")):
        kind = (f.get("types") or ["place"])[0]
    c, r = _anchor(geom, top_at, "building" in t or kind in ("cathedral", "church", "palace", "tower"))
    if not (0 <= c < W and 0 <= r < D):
        return None
    wiki = (f"https://en.wikipedia.org/wiki/{f['enwiki'].replace(' ', '_')}" if f.get("enwiki") else
            f"https://es.wikipedia.org/wiki/{f['eswiki'].replace(' ', '_')}" if f.get("eswiki") else None)
    arch = f.get("architects", [])
    out = dict(name=name, en=en if en and en != name else None, kind=kind, year=f.get("year"),
               by=", ".join(arch[:2]) + (" et al." if len(arch) > 2 else "") if arch else None,
               height=f.get("height"), style=cap((f.get("styles") or [None])[0]),
               heritage=cap((f.get("heritage") or [None])[0]), site=f.get("website"), wiki=wiki, qid=qid,
               alt=" ".join(filter(None, {en, es, f.get("es"), t.get("alt_name")} - {name})) or None,
               far=far, x=c, y=r, z=top_at(r, c))
    return {k: v for k, v in out.items() if v is not None}


def assemble(curated, osm, top_at):
    """The curated labels, then one per required and extended Wikidata item found on the map."""
    labels = list(curated)
    if not WIKIDATA.exists():
        return labels
    wd = json.loads(WIKIDATA.read_text())["items"]
    have = {l["name"] for l in labels}
    for qid, elems in _tagged(osm).items():
        f = wd.get(qid)
        if f is None:
            continue
        t, geom = elems[0]
        if qid in REQUIRED:
            far = 9000
        else:
            is_square = t.get("place") == "square"
            if qid in EXTENDED_EXCLUDE or (any(k in t for k in NOT_PLACES) and not is_square) or kind_of(t) is None:
                continue
            if not (f.get("heritage") or f.get("enwiki") or f.get("eswiki")) or NOT_PLACE_TYPES & set(f.get("types", [])):
                continue
            far = 2500 if f.get("wikis", 0) >= 15 else 1300 if f.get("wikis", 0) >= 4 or f.get("heritage") else 600
        l = label(qid, f, t, geom, top_at, far)
        if l and l["name"] not in have:
            labels.append(l)
            have.add(l["name"])
    labels.sort(key=lambda l: -l.get("far", 0))
    return labels


def radii(labels, g, abs_top):
    """Footprint radius: the viewer hides a label only when something *else* is in the way."""
    for l in labels:
        r, c = int(l["y"]), int(l["x"])
        gg = int(g[min(max(r, 0), D - 1), min(max(c, 0), W - 1)])
        l["g"] = gg
        thr = gg + max(6, (l["z"] - gg) * 0.4)
        r0, r1, c0, c1 = max(r - 220, 0), min(r + 221, D), max(c - 220, 0), min(c + 221, W)
        lab_, _ = ndimage.label(abs_top[r0:r1, c0:c1] >= thr)
        k = lab_[r - r0, c - c0] if (0 <= r - r0 < lab_.shape[0] and 0 <= c - c0 < lab_.shape[1]) else 0
        if k:
            rr_, cc_ = np.nonzero(lab_ == k)
            l["R"] = round(float(np.hypot(rr_ + r0 - r, cc_ + c0 - c).max()), 1)
        else:
            l["R"] = 0.0
