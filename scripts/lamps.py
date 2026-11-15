"""Street lamps for the viewer (web/src/lamps.ts): one record per lamp in web/public/data/lamps.bin.

The lamps come from the Ayuntamiento's lighting inventory (fetch_lamps.py: every unit on the streets, the Retiro and
the Jardines de Sabatini, about 22 000 over the AOI). OpenStreetMap's street_lamp nodes only fill in where the
inventory has no unit within OSM_GAP (private estates, a few squares). The viewer draws each lamp at its real width
instead of as 1 m voxels, and the pipeline does not put lamps in the tiles.

The inventory gives the luminaire model, not the support. The model decides it: each code is hung on facades or set
on posts almost without exception (FVLED005, a Villa lantern on a wall bracket: 95 % of its units within a metre of a
building; FVLED002, the same lantern on a column: 10 %), so a code whose units mostly stand on a facade is a wall
lamp (WALL_SHARE), one whose units mostly stand off it is a post, and a code with few units or no clear answer is
decided unit by unit. The code's prefix gives the lantern: FV the "Villa" lantern, FF the "Fernando VII" (fernandino),
G a globe, the rest a modern luminaire. The height is not in the inventory: STYLE_HEIGHT, by the street beside it.

Each post stands where the inventory puts it, unless that is inside a building or on a carriageway or track (the
municipal points are snapped to the street address, and OSM's roads are drawn wide): then on the nearest cell clear of
both within SNAP, or not at all. A wall lamp hangs on the nearest facade within WALL_REACH, facing away from it.

lamps.bin, gzip of a little-endian array of REC (16 bytes per lamp):
  x, y     float32  foot of the post, or the point on the facade under the bracket, grid cells (column, row)
  z        uint16   the surface it stands on (first open voxel above the ground, or above a bridge deck)
  height   uint8    lantern height above z, decimetres
  style    uint8    0 Villa lantern, 1 Fernando VII lantern, 2 globe, 3 modern luminaire
  heading  uint8    direction the arm or bracket points, (0..256) * 2 pi / 256 in the grid plane from +column
                    towards +row: over the road for a post, out of the wall for a bracket
  arms     uint8    luminaires: 1, or 2 on opposite sides (along heading and against it)
  light    uint8    0 LED, 1 discharge (sodium, halide), 2 both on one support
  flags    uint8    1 on a wall, 2 from OSM, 4 in a park, 8 on a bridge deck

usage: PYTHONPATH=scripts uv run python scripts/lamps.py  (after voxelize.py, which writes ground.npz)
"""
import gzip
import json
import math
import re
from collections import Counter, defaultdict

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from aoi import AREA, VOXEL_SIZE, WEB_DATA, D, W, to_grid
from osm import to_grid as lonlat_to_grid
from palette import stable_hash

REC = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<u2"), ("height", "u1"), ("style", "u1"), ("heading", "u1"),
                ("arms", "u1"), ("light", "u1"), ("flags", "u1")])
VILLA, FERNANDINO, GLOBE, MODERN = range(4)
F_WALL, F_OSM, F_PARK, F_DECK = 1, 2, 4, 8
LIGHT = {"LED": 0, "DESCARGA": 1, "LED-DESCARGA": 2}

# metres
WALL_NEAR = 1.0  # a unit this close to a building (or inside its footprint) stands on its facade
WALL_SHARE = 0.8  # a model whose units are this often on a facade is a wall lamp; this often off it, a post
MODEL_MIN = 8  # units of a model in the AOI needed to decide its support from them
WALL_REACH = 3.0  # how far a wall lamp may move to find its facade
SNAP = 4.0  # how far a post may move off a building or a carriageway
SAME = 0.8  # two units closer than this are one support entered twice (640 exact repeats in the street file)
OSM_GAP = 12.0  # an OSM lamp with no inventory unit this close is a lamp the inventory lacks
ROAD_REACH = 8.0  # a post's arm points to the nearest carriageway within this, or along a hash angle
MEDIAN = 6.0  # a modern post with carriageway on both sides within this stands on a median: two arms
AVENUE_W = 12.0  # carriageway at least this wide within 6 m makes an avenue (DECISIONS.md, 2026-11-10)
# lantern height by style: (walk, street, avenue). Villa and Fernando VII columns and globes are 3.5-4.5 m in Madrid,
# their wall brackets at the first floor; the modern luminaires on bent masts are 6-10 m (DECISIONS.md)
STYLE_HEIGHT = {VILLA: (4.0, 4.0, 4.5), FERNANDINO: (4.0, 4.0, 4.5), GLOBE: (3.5, 4.0, 4.0), MODERN: (5.0, 7.0, 9.0)}
WALL_HEIGHT = 4.5  # a bracket on the facade, about the first floor


def style_of(model, where):
    if where == "historic_park":
        return FERNANDINO  # the Retiro's and Sabatini's cast-iron lantern posts
    m = re.match(r"[A-Z]+", (model or "").upper())
    p = m.group(0) if m else ""
    return VILLA if p.startswith("FV") else FERNANDINO if p.startswith("FF") else GLOBE if p.startswith("G") else MODERN


def load_units():
    units = json.loads((AREA / "lamps.json").read_text())["lamps"]
    i, j = to_grid(np.array([u["x"] for u in units]), np.array([u["y"] for u in units]))
    return units, np.c_[i, j]


def load_osm():
    """OSM's street_lamp nodes: [(x, y, tags)] in grid cells (the whole file is not parsed into shapes: only nodes)."""
    data = json.loads((AREA / "osm.json").read_text())
    out = []
    for e in data["elements"]:
        t = e.get("tags") or {}
        if e["type"] == "node" and t.get("highway") == "street_lamp":
            out.append((*lonlat_to_grid(e["lon"], e["lat"]), t))
    return out


def build(note=print):
    G = np.load(AREA / "ground.npz")
    g, bmask, road, deck = G["g"].astype(int), G["b"] > 0, G["road"], G["deck"].astype(int)
    driven = road > 0
    cell = 1 / VOXEL_SIZE
    units, P = load_units()
    inside = (P[:, 0] >= 0) & (P[:, 0] < W) & (P[:, 1] >= 0) & (P[:, 1] < D)
    units, P = [u for u, k in zip(units, inside) if k], P[inside]

    # one support entered twice: keep the first, both luminaire types on it
    groups = cKDTree(P).query_ball_point(P, SAME * cell)
    keep, light = np.ones(len(P), bool), [LIGHT.get(u["light"], 0) for u in units]
    for a, near in enumerate(groups):
        if not keep[a]:
            continue
        for b in near:
            if b > a and keep[b]:
                keep[b] = False
                if light[b] != light[a]:
                    light[a] = 2
    n_twice = int((~keep).sum())
    units, P, light = [u for u, k in zip(units, keep) if k], P[keep], [l for l, k in zip(light, keep) if k]

    # how far each unit is from a building (0 inside a footprint), and each model's share on a facade
    bdist, (bnr, bnc) = ndimage.distance_transform_edt(~bmask, return_indices=True)
    rr, cc = P[:, 1].astype(int), P[:, 0].astype(int)
    near_wall = bdist[rr, cc] * VOXEL_SIZE <= WALL_NEAR
    by_model = defaultdict(list)
    for u, w in zip(units, near_wall):
        by_model[u["model"]].append(w)
    support = {}  # model -> True wall, False post (absent: decided per unit)
    for m, ws in by_model.items():
        share = float(np.mean(ws))
        if m and len(ws) >= MODEL_MIN and (share >= WALL_SHARE or share <= 1 - WALL_SHARE):
            support[m] = share >= WALL_SHARE
    note("lamp models:", len(by_model), "wall models:", sum(support.values()),
         "post models:", sum(not v for v in support.values()), "decided per unit:", len(by_model) - len(support))

    # OSM lamps where the inventory has none
    osm = load_osm()
    O = np.array([(x, y) for x, y, _ in osm]) if osm else np.zeros((0, 2))
    d_osm, _ = cKDTree(P).query(O) if len(O) else (np.zeros(0), None)
    gap = [k for k in range(len(osm)) if d_osm[k] * VOXEL_SIZE > OSM_GAP and 0 <= O[k, 0] < W and 0 <= O[k, 1] < D]
    note("OSM street lamps:", len(osm), "within 5 m of an inventory unit:", int((d_osm * VOXEL_SIZE <= 5).sum()),
         "no unit within", OSM_GAP, "m (kept):", len(gap))

    # what the placement needs: open ground off buildings and carriageways, the nearest carriageway, the facade normal
    blocked = bmask | driven
    sd, (snr, snc) = ndimage.distance_transform_edt(blocked, return_indices=True)
    rd, (rnr, rnc) = ndimage.distance_transform_edt(~driven, return_indices=True)
    road_half = ndimage.maximum_filter(ndimage.distance_transform_edt(road == 1), size=2 * round(6 * cell) + 1)
    near_road = ndimage.maximum_filter((road == 1).astype(np.uint8), size=2 * round(6 * cell) + 1) > 0
    soft = ndimage.gaussian_filter(bmask.astype(np.float32), 1.5 * cell)
    gy, gx = np.gradient(soft)  # the facade's outward normal is -grad
    _, (onr, onc) = ndimage.distance_transform_edt(bmask, return_indices=True)  # from inside to the nearest open cell

    def street_kind(r, c):
        return 2 if road_half[r, c] * VOXEL_SIZE >= AVENUE_W / 2 else 1 if near_road[r, c] else 0

    def surface(r, c):
        return (int(deck[r, c]), F_DECK) if deck[r, c] > 0 else (int(g[r, c]), 0)

    def angle(dc, dr):
        return int(round(math.atan2(dr, dc) / (2 * math.pi) * 256)) % 256

    recs, kinds, dropped = [], Counter(), Counter()

    def wall(x, y, style, li, flags):
        r, c = int(y), int(x)
        if bmask[r, c]:  # inside the footprint: out to the nearest open cell
            r, c = int(onr[r, c]), int(onc[r, c])
        if bdist[r, c] * VOXEL_SIZE > WALL_REACH:
            return False
        br, bc = int(bnr[r, c]), int(bnc[r, c])  # the building cell the bracket hangs on
        nx_, ny_ = -gx[r, c], -gy[r, c]
        if math.hypot(nx_, ny_) < 1e-4:
            nx_, ny_ = c - bc, r - br
        n = math.hypot(nx_, ny_) or 1.0
        nx_, ny_ = nx_ / n, ny_ / n
        # the foot of the bracket: the face of the building cell, along the normal from its centre
        fx, fy = bc + 0.5 + nx_ * 0.5, br + 0.5 + ny_ * 0.5
        z, f = surface(r, c)
        recs.append((fx, fy, z, round(WALL_HEIGHT * 10), style, angle(nx_, ny_), 1, li, flags | F_WALL | f))
        kinds["wall " + ("villa", "fernandino", "globe", "modern")[style]] += 1
        return True

    def post(x, y, style, li, flags, arms=1):
        r, c = int(y), int(x)
        if blocked[r, c]:
            if sd[r, c] * VOXEL_SIZE > SNAP:
                dropped["in a building or a carriageway, nothing clear within %g m" % SNAP] += 1
                return
            r, c = int(snr[r, c]), int(snc[r, c])
            x, y = c + 0.5, r + 0.5
        z, f = surface(r, c)
        kind = street_kind(r, c)
        h = STYLE_HEIGHT[style][kind]
        if rd[r, c] * VOXEL_SIZE <= ROAD_REACH:
            dc, dr = rnc[r, c] + 0.5 - x, rnr[r, c] + 0.5 - y
            head = angle(dc, dr)
            n = math.hypot(dc, dr) or 1.0
            ox, oy = int(x - dc / n * MEDIAN * cell), int(y - dr / n * MEDIAN * cell)  # as far the other way
            if style == MODERN and 0 <= ox < W and 0 <= oy < D and road[oy, ox] == 1:  # a median: two arms
                arms = 2
        else:
            head = stable_hash(c, r) % 256
        recs.append((x, y, z, round(h * 10), style, head, arms, li, flags | f))
        kinds[("villa", "fernandino", "globe", "modern")[style] + (" two-arm" if arms == 2 else "")] += 1

    for u, (x, y), w, li in zip(units, P, near_wall, light):
        style = style_of(u["model"], u["where"])
        flags = F_PARK if u["where"] != "street" else 0
        on_wall = support.get(u["model"], bool(w))
        arms = 2 if (u["model"] or "").upper().startswith("LLED") else 1
        if on_wall and wall(x, y, style, li, flags):
            continue
        post(x, y, style, li, flags, arms)
    for k in gap:
        x, y, t = osm[k]
        style = MODERN if t.get("lamp_mount") == "bent_mast" else FERNANDINO
        arms = 2 if (t.get("light:count") or "1").strip() in ("2", "3") else 1
        if t.get("support") == "wall_mounted" and wall(x, y, style, 0, F_OSM):
            continue
        post(x, y, style, 0, F_OSM, arms)

    a = np.array(recs, REC)
    (WEB_DATA / "lamps.bin").write_bytes(gzip.compress(a.tobytes(), 9, mtime=0))
    note("street lamps:", len(a), "from", len(units) + n_twice, "inventory units (", n_twice, "entered twice ) and",
         len(gap), "OSM nodes;", dict(kinds.most_common()))
    if dropped:
        note("street lamps dropped:", dict(dropped))
    return a


if __name__ == "__main__":
    a = build()
    # per 500 m block (x to the right, y downward), for comparing coverage
    blk = round(500 / VOXEL_SIZE)
    grid = np.zeros((math.ceil(D / blk), math.ceil(W / blk)), int)
    np.add.at(grid, ((a["y"] // blk).astype(int), (a["x"] // blk).astype(int)), 1)
    print(grid)
