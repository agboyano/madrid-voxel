"""One list of the AOI's trees from Madrid's municipal inventory and OSM:

- the municipal inventory (fetch_trees.py: datos.madrid.es "Arbolado en parques y zonas verdes de Madrid (detalle)"):
  one point per municipally maintained tree with species, height and trunk circumference -- the backbone
- OSM natural=tree: kept where no inventory tree stands within 2 m (private courtyards, new plantings), with its tags

Every tree gets a stable id: "mad:<inventory id>", else "osm:<node id>". Species are written as in botany ("Platanus x
hispanica", "Pyrus calleryana 'Chanticleer'"), from the inventory's upper-case names.
"""
import json
import re
import sys
from pathlib import Path

from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from aoi import D, RAW, W, to_grid  # noqa: E402


def _num(v):
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (ValueError, IndexError, TypeError):
        return None


def botanical(name):
    """'PLATANUS X HISPANICA' -> 'Platanus x hispanica'; cultivar quotes keep their capitals ('Chanticleer')."""
    if not name:
        return None
    name = re.sub(r"\s+", " ", name.strip())
    parts = re.split(r"('[^']*')", name)
    out = []
    for k, part in enumerate(parts):
        out.append(part.title() if part.startswith("'") else part.lower())
    s = "".join(out)
    return s[:1].upper() + s[1:]


def load(osm_trees):
    """osm_trees: [(oid, tags, Point(col, row))] from voxelize's OSM reader. Returns a list of dicts with grid x, y."""
    out = []
    inv = Path(RAW) / "trees" / "trees.json"
    if inv.exists():
        for t in json.load(open(inv))["trees"]:
            c, r = (float(v) for v in to_grid(t["x"], t["y"]))
            if not (0 <= c < W and 0 <= r < D):
                continue
            out.append(dict(id=f"mad:{t['id']}", src="city", x=c, y=r, species=botanical(t.get("species")),
                            height=t.get("height_m"), trunk_cm=t.get("trunk_cm"), park=t.get("park_id")))
    n_city = len(out)
    tree = cKDTree([(t["x"], t["y"]) for t in out]) if out else None
    n_osm = 0
    for oid, tg, p in osm_trees:
        if not (0 <= p.x < W and 0 <= p.y < D):
            continue
        if tree is not None:
            d, k = tree.query((p.x, p.y))
            if d < 2.0:
                out[k].setdefault("osm", oid)
                continue
        circ = _num(tg.get("circumference"))
        out.append(dict(id=f"osm:{oid}", src="osm", x=float(p.x), y=float(p.y), species=tg.get("species") or tg.get("genus"),
                        trunk_cm=circ * 100 if circ else None, height=_num(tg.get("height")),
                        leaf_type=tg.get("leaf_type"), osm=oid))
        n_osm += 1
    return out, dict(city=n_city, osm_only=n_osm)


CONIFER = ("Pinus", "Picea", "Abies", "Taxus", "Thuja", "Larix", "Pseudotsuga", "Juniperus", "Chamaecyparis", "Metasequoia",
           "Cupressus", "Cedrus", "Sequoiadendron", "Cupressocyparis")


def is_conifer(t):
    sp = t.get("species") or ""
    return sp.startswith(CONIFER) or t.get("leaf_type") == "needleleaved"


def attach_crowns(trees):
    """A crown map polygon per tree (Warsaw had one from remote sensing); Madrid has none, so nothing is attached."""
    return 0
