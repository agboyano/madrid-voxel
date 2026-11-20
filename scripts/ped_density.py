"""How many people walk each footpath, from the Ayuntamiento's pedestrian counters: the density `k` (people per km at the
weekday's busiest hour, the hourly profile's 1) and the half width `h` people spread over, for every edge of the
pedestrian graph (traffic.py; read by web/src/sim/life.ts).

The counters (Aforos de peatones y bicicletas, datos.madrid.es, life_profiles.counter_rows) count people crossing a
line each hour. A flow q (people per hour) walked at speed v is a density q / v along the way: each counter's mean
weekday hour at its busiest (2023, without July, August and December), over V_WALK, the viewer's mean walking speed.

Each edge takes, in order (DECISIONS.md, 2026-11-20):
  1. its street's counter: the same street (the edge's own name, or a sidewalk's road within ROAD_R) within
     COUNTER_R of a counter on it (the median of several); a sidewalk counter stands for each sidewalk of the street,
     a pedestrian street's for its one way;
  2. the commercial core without a counter (CORE): Fuencarral's, the busiest pedestrian street counted;
  3. by class, from the counters: pedestrian and living streets the median of the pedestrian-street counters; the
     sidewalks of primary, secondary and trunk roads the median of the sidewalk counters without Gran Vía;
  4. by class, assumed (no counter): the sidewalks of smaller streets half the main roads', any other path PATH_K.
"""
import re
import unicodedata
from collections import defaultdict

import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from aoi import VOXEL_SIZE

V_WALK = 1.33  # m/s: the mean of the viewer's walking speeds (spawnPed in web/src/sim/life.ts: 1.05 + 0.55 * rand)
YEAR = 2023  # the counters' last whole year (life_profiles.COUNTERS_YEAR)
SKIP_MONTHS = (7, 8, 12)  # summer holidays and Christmas: not an ordinary weekday
COUNTER_R = 800.0  # m along a street that one counter stands for
ROAD_R = 15.0  # m from a sidewalk to the road it belongs to
CORE = ("preciados", "carmen", "montera", "puerta del sol")  # Madrid's busiest streets with no counter
CORE_LIKE = "fuencarral"
PATH_K = 40.0  # people per km on a path that belongs to no street (parks, steps, platforms): assumed
MAIN = {"primary", "secondary", "trunk", "primary_link", "secondary_link", "trunk_link"}
HALF = {"pedestrian": 4.0, "living_street": 3.0}  # m people spread either side of the way, when OSM has no width
HALF_SIDEWALK, HALF_PATH = 1.5, 1.0

_ART = re.compile(r"^(calle|plaza|paseo|avenida|glorieta|ronda|cuesta|costanilla|travesia|carrera|camino)( de(l| la| los| las)?)? ")


def norm(name):
    """a street name for matching: lower case, no accents, no 'Calle de' (OSM 'Calle del Doctor Esquerdo', the counter
    'Calle Hortaleza 18')"""
    s = unicodedata.normalize("NFD", (name or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[,.].*$", "", s).strip()
    s = re.sub(r"\s+\d.*$", "", s)  # a house number and what follows
    s = re.sub(r"\s+(esquina|entre)\s.*$", "", s)
    return _ART.sub("", s).strip()


def counters(note=print):
    """The pedestrian counters in the map: [(station, x, y, street (normalised), pedestrian street?, k)]."""
    from life_profiles import counter_rows, daytype
    rows, stations = counter_rows("peds", YEAR)
    hours = defaultdict(lambda: defaultdict(lambda: np.zeros(24)))
    for sid, day, hh, n in rows:
        if day.month in SKIP_MONTHS or daytype(day) != "weekday":
            continue
        hours[sid][day][hh] += n
    out = []
    for sid, days in hours.items():
        A = np.array([v for v in days.values() if (v > 0).sum() >= 20])
        if len(A) < 30:
            continue
        x, y, address, side = stations[sid]
        peak = float(A.mean(0).max())
        out.append((sid, x, y, norm(_unmangle(address)), "peatonal" in side.lower(), peak / (3600 * V_WALK) * 1000))
    for sid, x, y, street, ped, k in sorted(out, key=lambda c: -c[5]):
        note(f"  pedestrian counter {sid} {street!r}{' (pedestrian street)' if ped else ''}: {k:.0f} people/km at peak")
    return out


def assign(peds, roads, note=print):
    """Set k (people per km at the profile's peak) and h (half width, cells) on every pedestrian edge, from its OSM tags
    in e["_t"] (taken off; none on the links traffic.py makes itself). roads: [(tags, LineString)] of the drivable
    ways."""
    tags = [e.pop("_t", None) for e in peds]
    cs = counters(note)
    rtree = STRtree([l for _, l in roads])
    lines = [LineString([q[:2] for q in e["p"]]) for e in peds]
    street, cls = [], []
    for e, t, ln in zip(peds, tags, lines):
        t = t or {}
        hw = t.get("highway")
        if hw in ("pedestrian", "living_street") or (hw and t.get("name") and t.get("footway") != "sidewalk"):
            street.append(norm(t.get("name")))
            cls.append(hw)
            continue
        mid = ln.interpolate(0.5, normalized=True)
        near = [roads[i] for i in rtree.query(mid.buffer(ROAD_R / VOXEL_SIZE))]
        near = [(rt, rl) for rt, rl in near if rl.distance(mid) <= ROAD_R / VOXEL_SIZE and rt.get("name")]
        if near and (t.get("footway") in ("sidewalk", None) and hw in ("footway", "path", "pedestrian", None)):
            rt, _ = min(near, key=lambda r: r[1].distance(mid))
            street.append(norm(rt["name"]))
            cls.append("sidewalk:" + rt["highway"])
        else:
            street.append("")
            cls.append(hw or "path")
    # 1. the counters on each street, by the distance along the map
    by_street = defaultdict(list)
    for sid, x, y, s, ped, k in cs:
        by_street[s].append((x, y, k))
    ped_k = [k for *_, ped, k in cs if ped]
    side_k = [k for _, _, _, s, ped, k in cs if not ped and s != "gran via"]
    core_k = next((k for _, _, _, s, _, k in cs if s == CORE_LIKE), max(ped_k, default=PATH_K))
    k_ped = float(np.median(ped_k)) if ped_k else PATH_K
    k_main = float(np.median(side_k)) if side_k else PATH_K
    rule = defaultdict(float)
    matched = defaultdict(float)
    for e, s, c, ln in zip(peds, street, cls, lines):
        mid = ln.interpolate(0.5, normalized=True)
        on = [k for x, y, k in by_street.get(s, []) if mid.distance(Point(x, y)) * VOXEL_SIZE <= COUNTER_R] if s else []
        if on:
            k, r = float(np.median(on)), "counter"
            matched[s] += e["L"]
        elif s in CORE:
            k, r = core_k, "core"
        elif c in ("pedestrian", "living_street"):
            k, r = k_ped, "pedestrian street (counters)"
        elif c.startswith("sidewalk:") and c[9:] in MAIN:
            k, r = k_main, "main-road sidewalk (counters)"
        elif c.startswith("sidewalk:"):
            k, r = k_main / 2, "side-street sidewalk (assumed)"
        else:
            k, r = PATH_K, "other path (assumed)"
        e["k"] = round(k)
        rule[r] += e["L"]
    for e, t, c in zip(peds, tags, cls):
        t = t or {}
        w = _width(t.get("width"))
        if c in HALF:
            e["h"] = round((w / 2 if w else HALF[c]) / VOXEL_SIZE, 1)
        elif c.startswith("sidewalk:") or t.get("footway") == "sidewalk":
            e["h"] = round((w / 2 if w else HALF_SIDEWALK) / VOXEL_SIZE, 1)
        else:
            e["h"] = round((w / 2 if w else HALF_PATH) / VOXEL_SIZE, 1)
    note(f"pedestrian density: pedestrian streets {k_ped:.0f}/km, main-road sidewalks {k_main:.0f}/km, core {core_k:.0f}/km;"
         " km by rule: " + ", ".join(f"{r} {L / 1000:.1f}" for r, L in sorted(rule.items(), key=lambda kv: -kv[1])))
    for *_, s, _, _ in cs:
        if not matched.get(s):
            note(f"  counter on {s!r} matched no footpath of its street")
    return peds


def _unmangle(s):
    """the counters' file is UTF-8 read once as Latin-1 and saved again ('Gran VÃ\xada', 'BailÃ©n'): undo it"""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _width(v):
    try:
        return float(str(v).replace(",", ".").split()[0]) if v else None
    except ValueError:
        return None
