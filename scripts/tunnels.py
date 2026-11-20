"""Road tunnels carved under the streets: Doctor Esquerdo under O'Donnell, Bailén under the Plaza de Oriente, Atocha.

OSM maps a tunnel as ways tagged tunnel=yes and the ramps down to it as ordinary ways; the LiDAR's ground follows the
ramps into their trench. Until this module the tunnels were left out (layers.tunnelish), the street over the short
ones was lifted level (layers.py), and each ramp ended against a wall of ground at its portal, its cars vanishing there.

plan() works in 2D, from the ground g (voxels) and the raw OSM: it picks the tunnelled carriageways (the classes of
CLASSES; service ways, mostly car-park ramps, stay as they were), groups them by shared nodes, and finds each
group's portals (its nodes shared with surface roads). A portal's floor is the ramp's bottom just outside it. Inside,
the floor is interpolated between the portals over the tunnel's own graph (harmonic: every point the length-weighted
mean of its neighbours), then kept under the street (CLEAR_MIN of headroom and a SLAB of roof) and under any tunnel
of a higher layer it crosses (its whole CLEAR), at no more than MAX_GRADE of slope away from those limits.

carve() digs them into the volume: the bore (CLEAR high where the street allows, CLEAR_MIN at least), an asphalt
floor with a dashed centre line, concrete walls and roof where soil would show, and a lamp on the roof every
LAMP_EVERY (palette material M_TUNNEL_LAMP, lit day and night by the viewer). traffic.py drives the carved ways at the
floor (FLOOR, IDS).

Distances are in metres and converted to cells with VOXEL_SIZE; heights are voxels.

    PYTHONPATH=scripts uv run python scripts/tunnels.py    # the report, from the last build's ground
"""
import heapq
import json
from collections import defaultdict

import numpy as np
import scipy.sparse as sp
from scipy import ndimage
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point

from aoi import AREA, VOXEL_SIZE
from osm import to_grid
from palette import M_TUNNEL_LAMP, parse_len

CLASSES = {"primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}  # (not Calle 30's motorway)
SURFACE = CLASSES | {"motorway", "trunk", "service"}  # roads a portal opens onto
DEEPEST = -2  # the lowest layer carved (O'Donnell's and the Plaza Mayor's); deeper ones are left out
CLEAR = 5.0  # m of headroom where the street over it allows (a bus is 3.2 m)
CLEAR_MIN = 4.0  # m of headroom at least: near a portal the street over it stands only ~6 m over the ramp
SLAB = 1.0  # m of roof under the street
MAX_GRADE = 0.08  # the steepest the floor runs away from a limit
LANE = 3.25  # m per lane
MARGIN = 1.0  # m beside the outer lanes
RAMP = (1.0, 5.0)  # m out from a portal along its ramp where the ramp's bottom is read
RAMP_CUT = 0.10  # the slope a ramp is cut down at to meet a portal pulled under it
RAMP_MIN = 3.0  # m a ramp's bottom must stand under the street for its portal to count (else no ramp: the tunnel tag
#                 has no cut in the LiDAR)
STREET_R = 5.0  # m: the street over a point is the highest ground within it (not the ramp's trench beside a portal)
PORTAL_FREE = 10.0  # m in from a portal where the street sets no limit: the trench runs on to the portal's lintel
LAMP_EVERY = 6.0  # m between roof lamps
DASH = (3.0, 6.0)  # m painted, m period of the centre line

cells = lambda m: max(1, int(round(m / VOXEL_SIZE)))  # noqa: E731

FLOOR = None  # (D, W) int16: the carved floor's level (first free voxel) under and round each carved way, -1 elsewhere
IDS = set()  # the OSM ids of the carved ways
PROFILE = {}  # OSM id -> (samples along the way, floor at each): where tunnels cross, each way keeps its own floor


def _layer(t):
    v = parse_len(str(t.get("layer", "0")).split(";")[0])
    return 0 if v is None else v


def _select(data, D, W):
    """the tunnelled carriageways and the surface roads' nodes: (ways {id: way}, surface node ids, node positions)"""
    ways, surf, pos = {}, set(), {}
    for e in data["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or not e.get("geometry") or None in e["geometry"]:
            continue
        base = (t.get("highway") or "").replace("_link", "")
        if base not in SURFACE:
            continue
        for n, p in zip(e["nodes"], e["geometry"]):
            pos.setdefault(n, to_grid(p["lon"], p["lat"]))
        if t.get("tunnel") == "yes" and base in CLASSES and t.get("indoor") != "yes" and t.get("location") != "indoor" \
                and _layer(t) >= DEEPEST:
            ways[e["id"]] = e
        elif t.get("tunnel") in (None, "no") and _layer(t) >= 0 and t.get("covered") in (None, "no"):
            surf.update(e["nodes"])
            e["_surface"] = True
    surf_ways = [e for e in data["elements"] if e.get("_surface")]
    return ways, surf, pos, surf_ways


def _groups(ways):
    par = {w: w for w in ways}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    by_node = defaultdict(list)
    for w, e in ways.items():
        for n in e["nodes"]:
            by_node[n].append(w)
    for ids in by_node.values():
        for w in ids[1:]:
            par[find(w)] = find(ids[0])
    out = defaultdict(list)
    for w in ways:
        out[find(w)].append(w)
    return list(out.values())


def _sample(g, x, y):
    D, W = g.shape
    return g[min(max(int(y), 0), D - 1), min(max(int(x), 0), W - 1)]


def _inside(x, y, D, W):
    return 0 <= x < W and 0 <= y < D


def plan(g, data=None, note=print):
    """The tunnels to carve, from the ground g (voxels). Sets FLOOR and IDS; returns {ways, ramps}: the carved ways, each
    a dict with wid, name, layer, half width (cells), P (samples along it, grid coordinates), zf (floor) and top (first
    voxel of roof) per sample; and the ramps to cut down to a portal pulled under them (P out from the portal, zf, hw)."""
    global FLOOR
    D, W = g.shape
    if data is None:
        data = json.load(open(AREA / "osm.json"))
    ways, surf, pos, surf_ways = _select(data, D, W)
    street = ndimage.maximum_filter(g, size=2 * cells(STREET_R) + 1)
    clear, clear_min, slab = cells(CLEAR), cells(CLEAR_MIN), cells(SLAB)
    step = 1.0  # cells between samples
    groups = _groups(ways)
    # higher layers first: a tunnel under another is planned under its floor
    groups.sort(key=lambda ids: -max(_layer(ways[w]["tags"]) for w in ids))
    FLOOR = np.full((D, W), -1, np.int16)
    IDS.clear()
    PROFILE.clear()
    out, report, ramps = [], [], []
    upper = np.full((D, W), np.iinfo(np.int16).max, np.int32)  # the floor of the tunnels planned so far, under them

    # the ramp's bottom outside a portal: along each surface road leaving the node, RAMP metres out
    surf_at = defaultdict(list)
    for e in surf_ways:
        for end in (0, -1):
            surf_at[e["nodes"][end]].append((e["nodes"] if end == 0 else e["nodes"][::-1], e["tags"]))

    def ramp_level(n):
        best = None
        for seq, _ in surf_at.get(n, []):
            pts = [pos[m] for m in seq if m in pos]
            if len(pts) < 2:
                continue
            ln = LineString(pts)
            d = [v / VOXEL_SIZE for v in np.arange(RAMP[0], min(RAMP[1], ln.length * VOXEL_SIZE) + 1e-6, VOXEL_SIZE)]
            hs = [_sample(g, *ln.interpolate(v).coords[0]) for v in d]
            if hs:
                h = int(np.median(hs))
                best = h if best is None else min(best, h)
        return best

    for ids in groups:
        names = sorted({ways[w]["tags"].get("name", "") for w in ids} - {""})
        layer = min(_layer(ways[w]["tags"]) for w in ids)
        # the dense graph: every OSM node, and a sample every cell between them
        key_xy, key_of, edges = [], {}, []

        def vid(k, xy):
            if k not in key_of:
                key_of[k] = len(key_xy)
                key_xy.append(xy)
            return key_of[k]
        way_seq = {}
        for w in ids:
            e = ways[w]
            seq = []
            ns = [n for n in e["nodes"] if n in pos]
            for i, (a, b) in enumerate(zip(ns, ns[1:])):
                pa, pb = np.array(pos[a]), np.array(pos[b])
                L = float(np.hypot(*(pb - pa)))
                k = max(1, int(L / step))
                prev = vid(("n", a), tuple(pa))
                if i == 0:
                    seq.append(prev)
                for j in range(1, k + 1):
                    cur = vid(("n", b), tuple(pb)) if j == k else vid(("s", w, i, j), tuple(pa + (pb - pa) * j / k))
                    edges.append((prev, cur, L / k))
                    seq.append(cur)
                    prev = cur
            if len(seq) >= 2:
                way_seq[w] = seq
        if not way_seq:
            continue
        xy = np.array(key_xy)
        n = len(xy)
        inside = np.array([_inside(x, y, D, W) for x, y in xy])
        # portals: nodes shared with a surface road, inside the map, with a ramp under the street
        portals, dropped = {}, []
        for k, i in key_of.items():
            if k[0] != "n" or k[1] not in surf or not inside[i]:
                continue
            h = ramp_level(k[1])
            s = _sample(street, *xy[i])
            if h is None or s - h < cells(RAMP_MIN):
                dropped.append((k[1], None if h is None else int(s - h)))
                continue
            portals[i] = h
        if len(portals) < 2:  # (one portal in the map: the rest runs off its edge, which would show its section)
            report.append((names, layer, len(portals), 0, len(dropped), "under two portals with a ramp in the map: left out"))
            continue
        # harmonic floor between the portals: sum_j w_ij (z_i - z_j) = 0, portals fixed
        A = sp.lil_matrix((n, n))
        b = np.zeros(n)
        for a_, b_, L in edges:
            wgt = 1.0 / max(L, 1e-3)
            for i, j in ((a_, b_), (b_, a_)):
                if i in portals:
                    continue
                A[i, i] += wgt
                if j in portals:
                    b[i] += wgt * portals[j]
                else:
                    A[i, j] -= wgt
        for i, h in portals.items():
            A[i, i] = 1.0
            b[i] = h
        z = spsolve(A.tocsr(), b)
        # the limits: under the street, under the tunnels above, never under the map's floor
        cx = np.clip(xy[:, 0].astype(int), 0, W - 1)
        cy = np.clip(xy[:, 1].astype(int), 0, D - 1)
        # (the street's own top voxel, g - 1, stays: the roof and its lamps are under it)
        cap = np.minimum(g[cy, cx] - 1 - slab - clear_min, upper[cy, cx] - 1 - slab - clear).astype(float)
        adj = defaultdict(list)
        for a_, b_, L in edges:
            adj[a_].append((b_, L))
            adj[b_].append((a_, L))
        # near a portal the street sets no limit (the ramp's trench reaches the lintel): graph distance from the portals
        dist = np.full(n, np.inf)
        heap = [(0.0, i) for i in portals]
        for _, i in heap:
            dist[i] = 0.0
        while heap:
            d, i = heapq.heappop(heap)
            if d > dist[i]:
                continue
            for j, L in adj[i]:
                if d + L < dist[j]:
                    dist[j] = d + L
                    heapq.heappush(heap, (d + L, j))
        cap = np.where(dist < PORTAL_FREE / VOXEL_SIZE, np.inf, cap)
        z = np.minimum(z, cap)
        # no steeper than MAX_GRADE away from what pulled it down (Dijkstra over the graph from the lowest points)
        heap = [(z[i], i) for i in range(n)]
        heapq.heapify(heap)
        while heap:
            zi, i = heapq.heappop(heap)
            if zi > z[i]:
                continue
            for j, L in adj[i]:
                zj = zi + MAX_GRADE * L  # (cells along, voxels up: both VOXEL_SIZE)
                if zj < z[j] - 1e-6:
                    z[j] = zj
                    heapq.heappush(heap, (zj, j))
        zf = np.maximum(np.round(z).astype(int), 2)
        top = np.minimum(zf + clear, np.maximum(g[cy, cx] - 1 - slab, zf + clear_min))
        forced = [(int(h), int(zf[i])) for i, h in portals.items() if zf[i] < h]
        # a portal under its ramp's bottom (the DTM loses the ramp under the lintel): the ramp is cut down to it
        node_at = {i: k[1] for k, i in key_of.items() if k[0] == "n"}
        for i, h in portals.items():
            if zf[i] >= h:
                continue
            for seq, t in surf_at.get(node_at[i], []):
                pts = [pos[m] for m in seq if m in pos]
                if len(pts) >= 2:
                    lanes = parse_len(t.get("lanes")) or 2
                    ramps.append(dict(P=np.array(pts), zf=int(zf[i]), hw=(lanes * LANE / 2 + MARGIN) / VOXEL_SIZE))
        L_in = 0.0
        for w, seq in way_seq.items():
            e = ways[w]
            t = e["tags"]
            lanes = parse_len(t.get("lanes")) or 2
            hw = (lanes * LANE / 2 + MARGIN) / VOXEL_SIZE
            P = xy[seq]
            ok = inside[seq]
            if ok.sum() < 2:
                continue
            L_in += float(np.hypot(*np.diff(P[ok], axis=0).T).sum()) * VOXEL_SIZE
            out.append(dict(wid=w, name=t.get("name", ""), layer=_layer(t), hw=hw, P=P, zf=zf[seq], top=top[seq],
                            oneway=t.get("oneway") in ("yes", "-1", "true", "1")))
            IDS.add(w)
            PROFILE[w] = (P, zf[seq])
        # the floor raster under and round these ways (traffic reads it), and the limit for tunnels under them
        report.append((names, layer, len(portals), round(L_in), len(dropped), f"floor {zf.min()}..{zf.max()}"
                       + (f", portals pulled under their ramp (ramp, floor): {forced}" if forced else "")))
        for c in [o for o in out if o["wid"] in way_seq]:
            rr, cc, kk = _cells_of_way(c, D, W, extra=1.0 / VOXEL_SIZE)
            zf_c = c["zf"][kk]
            cur = FLOOR[rr, cc]
            FLOOR[rr, cc] = np.where((cur < 0) | (zf_c < cur), zf_c, cur)
            upper[rr, cc] = np.minimum(upper[rr, cc], zf_c)
    note(f"road tunnels: {len(out)} ways carved in {sum(1 for r in report if r[3])} groups, "
         f"{sum(r[3] for r in report)} m inside the map")
    for names, layer, np_, L, nd, info in report:
        note(f"  {', '.join(names) or '(unnamed)'}: layer {layer:g}, {np_} portals, {L} m, "
             f"{nd} nodes on surface roads without a ramp; {info}")
    return dict(ways=out, ramps=ramps)


def _cells_of_way(c, D, W, extra=0.0):
    """the cells of a carved way's bore (half width + extra cells), each with the index of its nearest sample"""
    from layers import cells_of
    poly = LineString(c["P"]).buffer(c["hw"] + extra, cap_style="flat")
    rr, cc = cells_of(poly)
    k = (rr >= 0) & (rr < D) & (cc >= 0) & (cc < W)
    rr, cc = rr[k], cc[k]
    kk = cKDTree(c["P"]).query(np.column_stack([cc + 0.5, rr + 0.5]))[1]
    return rr, cc, kk


def carve(vol, g, tunnels, C, pal, note=print):
    """Dig the planned tunnels into the volume and cut their ramps down to them (vol and g in place). Higher layers
    first, as planned."""
    D, W = g.shape
    concrete, lamp = C["concrete"], pal("#fff1d6", M_TUNNEL_LAMP)
    floor_c, mark = C["asphalt"], C["mark"]
    n_cells = n_lamps = n_cut = 0
    # the ramps first: out from a portal its road falls to the tunnel's floor at RAMP_CUT; its sides become walls
    for rp in tunnels["ramps"]:
        P = rp["P"]
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
        reach = (g.max() - rp["zf"]) / RAMP_CUT
        ln = LineString(P)
        if ln.length > reach:
            ln = LineString([ln.interpolate(v).coords[0] for v in np.linspace(0, reach, max(2, int(reach) + 1))])
        from layers import cells_of
        for extra, wall in ((0.0, False), (1.0 / VOXEL_SIZE, True)):
            rr, cc = cells_of(ln.buffer(rp["hw"] + extra, cap_style="flat"))
            k = (rr >= 0) & (rr < D) & (cc >= 0) & (cc < W)
            rr, cc = rr[k], cc[k]
            d = np.array([ln.project(Point(x + 0.5, y + 0.5)) for x, y in zip(cc, rr)])
            target = rp["zf"] + np.ceil(RAMP_CUT * d).astype(int)
            for r, col, z in zip(rr, cc, target):
                if g[r, col] <= z:
                    continue
                if not wall:
                    top = vol[g[r, col] - 1, r, col]
                    vol[z:g[r, col], r, col] = 0
                    vol[z - 1, r, col] = top
                    g[r, col] = z
                    n_cut += 1
                elif vol[g[r, col] - 1, r, col] != 0:
                    vol[z - 1:g[r, col] - 1, r, col] = np.where(vol[z - 1:g[r, col] - 1, r, col] != 0, concrete, 0)
    for c in tunnels["ways"]:
        rr, cc, kk = _cells_of_way(c, D, W)
        zf, top = c["zf"][kk], c["top"][kk]
        for r, col, z0, z1 in zip(rr, cc, zf, top):
            if z1 > g[r, col] - 2:  # no roof under the street's own voxel: by a portal the bore opens to the trench
                z1 = max(z1, g[r, col])
            vol[z0:z1, r, col] = 0
            vol[z0 - 1, r, col] = floor_c
            if z1 <= g[r, col] - 2 and vol[z1, r, col] != 0:
                vol[z1, r, col] = concrete
            n_cells += 1
        # the walls where soil would show
        wr, wc, wk = _cells_of_way(c, D, W, extra=1.0 / VOXEL_SIZE)
        inner = set(zip(rr.tolist(), cc.tolist()))
        for r, col, k in zip(wr, wc, wk):
            if (r, col) in inner:
                continue
            z0, z1 = c["zf"][k] - 1, min(c["top"][k] + 1, g[r, col] - 1)
            if z1 > z0:
                seg = vol[z0:z1, r, col]
                vol[z0:z1, r, col] = np.where(seg != 0, concrete, 0)
        # the centre line, dashed, and the lamps on the roof over it
        P = c["P"]
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))]) * VOXEL_SIZE
        for i, (x, y) in enumerate(P):
            r, col = int(y), int(x)
            if not (0 <= r < D and 0 <= col < W):
                continue
            z0, z1 = c["zf"][i], c["top"][i]
            if s[i] % DASH[1] < DASH[0] and vol[z0 - 1, r, col] == floor_c:
                vol[z0 - 1, r, col] = mark
            if s[i] % LAMP_EVERY < VOXEL_SIZE and z1 <= g[r, col] - 2 and vol[z1, r, col] != 0:
                vol[z1, r, col] = lamp
                n_lamps += 1
    note(f"road tunnels carved: {n_cells} cells, {n_lamps} roof lamps; ramp cells cut down to a portal: {n_cut}")


if __name__ == "__main__":
    g = np.load(AREA / "ground.npz")["g"].astype(np.int32)
    plan(g)
