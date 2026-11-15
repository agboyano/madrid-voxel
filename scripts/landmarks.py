"""Landmarks: curated labels, per-building overrides (overrides.json) and the generic tools for curated geometry.

The Warsaw snapshot rebuilt dozens of Warsaw landmarks here in hard-coded grid boxes (the Palace of Culture, its clock
and tower, churches, bridges, masts). Those are gone; what stays is the machinery: labels, overrides.json (wall and
roof styles, facade zones, crowns, stripes), young street trees, OSM bridge piers, and the helpers a curated Madrid
landmark can use (classic_rebuild, edge_windows, ortho_roof, _onion, recolour_walls, _pier). Madrid's labels come in
Phase 4 from OSM wikidata tags (fetch_wikidata.py), never by name.
"""
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon
from scipy import ndimage

import monuments
import roofgardens
from aoi import AREA, D as _D, VOXEL_SIZE, W as _W, to_grid

M_WALL, M_GLASS, M_CONCRETE, M_CLOCK = 1, 2, 13, 14

# OSM name -> facts for the curated labels (en, kind, height, year, by, alt, anchor="top"); filled in Phase 4
LABELS = {}
# labels without a single OSM polygon: name -> facts with at=(x, y) in EPSG:25830
EXTRA_LABELS = {}
# roofs to smooth (a membrane or a lattice the LiDAR reads as noise): OSM id -> description
SMOOTH_ROOFS = {}
# Madrid's historic core, for its own wall palette (palette.AUSTRIAS_WALLS) and tiled roofs: Madrid de los Austrias.
# It has no official boundary (it lies in the barrio of Palacio, which also takes in the Royal Palace, Ópera and Plaza
# de España); the usual description runs along these streets, clockwise from the north-west, and the outline follows
# their OSM centrelines, each joined to the next where they come closest.
HISTORIC_CORE_STREETS = ["Calle de Bailén", "Calle Mayor", "Plaza Mayor", "Calle de Toledo", "Plaza de la Cebada",
                         "Plaza de los Carros", "Calle de la Redondilla"]
HISTORIC_CORE_SEED = (439728, 4474088)  # EPSG:25830, Plaza de la Villa: the face of the street network it lies in
_CORE = None


def historic_core():
    """The hole of the street lines, drawn 2 m wide, that holds the seed, with Plaza Mayor (which its own outline
    closes off) and grown back to the centrelines."""
    global _CORE
    if _CORE is None:
        from shapely.ops import nearest_points, unary_union
        from shapely.geometry import LineString
        from osm import OSM
        lines = OSM().lines
        G = [unary_union([g for _, t, g in lines if t.get("name") == n and t.get("highway")]) for n in HISTORIC_CORE_STREETS]
        if any(g.is_empty for g in G):
            missing = [n for n, g in zip(HISTORIC_CORE_STREETS, G) if g.is_empty]
            raise SystemExit(f"historic_core: no OSM street named {missing}")
        links = [LineString(nearest_points(a, b)) for a, b in zip(G, G[1:] + G[:1])]
        band = unary_union(G + [l for l in links if l.length > 0]).buffer(1.0)
        holes = [Polygon(r) for p in getattr(band, "geoms", [band]) for r in p.interiors]
        seed = Point(*to_grid(*HISTORIC_CORE_SEED))
        core = [h for h in holes if h.contains(seed)]
        if not core:
            raise SystemExit("historic_core: the streets do not close round the seed")
        hull = G[HISTORIC_CORE_STREETS.index("Plaza Mayor")].convex_hull.buffer(2)
        # grown 1 m back to the centrelines, and 2 m more and back to join Plaza Mayor across Calle Mayor's band
        _CORE = unary_union(core + [h for h in holes if h.within(hull)]).buffer(3.0).buffer(-2.0)
    return _CORE


def label(osm_name, facts, x, y, z):
    keep = {k: v for k, v in facts.items() if k not in ("anchor", "at", "name")}
    return dict(name=facts.get("name", osm_name), **keep, x=x, y=y, z=z)


def adjust_heights(top, feats, note):
    """Per-building height corrections. PGE Narodowy's roof is a translucent membrane on a cable net: the LiDAR came
    back from the membrane, the cables and the trusses under it alike, a field of 1-3 m boxes from the air. Its slope
    is kept and the noise taken out: a 9 m median, then a 3 m Gaussian within the part's cells."""
    for f in feats:
        if f["id"] not in SMOOTH_ROOFS:
            continue
        rr, cc = f["rr"], f["cc"]
        r0, r1, c0, c1 = rr.min() - 10, rr.max() + 11, cc.min() - 10, cc.max() + 11
        sub = top[r0:r1, c0:c1]
        m = np.zeros(sub.shape, bool)
        m[rr - r0, cc - c0] = True
        med = ndimage.median_filter(np.where(m, sub, np.nan_to_num(np.median(sub[m]))), size=9)
        w = ndimage.gaussian_filter(m.astype(float), 3)
        sm = ndimage.gaussian_filter(np.where(m, med, 0), 3) / np.maximum(w, 1e-6)
        sub[m] = sm[m]
        note(f"roof smoothed: {SMOOTH_ROOFS[f['id']]} ({len(rr)} cells)")


MAT_IDS = {"solid": 0, "wall": 1, "glass": 2, "metal": 6, "grass": 8, "roof": 12, "concrete": 13,
           "bronze_grid": 15, "sign": 16, "sign_band": 18, "ribbon": 19, "classic": 20, "window": 21, "tenement": 22}


OVERRIDES = json.load(open(Path(__file__).with_name("overrides.json")))["buildings"]


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def override_for(f):
    """overrides.json entry for a feature: by its own id, its parent outline's id, or its (parent's) name."""
    keys = [str(f["id"])]
    if f.get("parent"):
        keys.append(str(f["parent"]["id"]))
    keys.append(_name(f) or "")
    for k in keys:
        o = OVERRIDES.get(k)
        if o and (f["maxh"] or 0) >= o.get("min_part_height", -1):
            return o
    return None


def _style(pal, spec):
    return pal(_hex(spec["colour"]), MAT_IDS[spec.get("material", "wall")])


def apply_stripes(vol, g, bmask, pal, osm, cells_of, note):
    """overrides.json areas with "stripes": vertical bands of colour by angle around the area's centre on every
    building column inside it, from 3 m up to (not including) the roof voxel -- e.g. PGE Narodowy's red and silver
    facade. Whole columns, because the LiDAR bowl rises above the OSM part heights.
    Returns the floodlit infields as [x, y, r] (cells) for the night lighting."""
    floods = []
    for oid, o in OVERRIDES.items():
        st = o.get("stripes")
        if not st or not oid.isdigit():
            continue
        geom = next((gm for i, typ, t, gm in osm.areas if str(i) == oid), None)
        if geom is None:
            continue
        cx, cy = geom.centroid.x, geom.centroid.y
        R = math.sqrt(geom.area / math.pi)
        cols = [pal(_hex(c), MAT_IDS[st.get("material", "wall")]) for c in st["colours"]]
        # "bands": horizontal bands by height above ground instead of vertical stripes, [{to (m), colour | checker, material}],
        # the last without "to" running to the top
        bands, chk = [], None
        for b in st.get("bands", []):
            if "repeat" in b:  # floor by floor: [[metres, colour, material], ...] cycled upward (Zebra Tower's spandrels)
                bands.append((b.get("to", 10 ** 4), [(n, pal(_hex(c), MAT_IDS[m])) for n, c, m in b["repeat"]]))
            elif "checker" in b:
                chk = [pal(_hex(c), MAT_IDS[b.get("material", "wall")]) for c in b["checker"]]
                bands.append((b.get("to", 10 ** 4), "checker"))
            else:
                bands.append((b.get("to", 10 ** 4), pal(_hex(b["colour"]), MAT_IDS[b.get("material", "wall")])))
        rr, cc = cells_of(geom)
        # recolour by palette colour within the area (e.g. OSM's #3399cc "glass" inner roof edge)
        for src, dst in o.get("recolour", {}).items():
            sr = _hex(src)
            # palette entries are the OSM colour after voxelize's grading (soften by 8 % for glass, 12 % otherwise)
            soft = [tuple(v * (1 - a) + w * a for v, w in zip(sr, (226, 220, 208))) for a in (0.08, 0.12)]
            ids = [i for i, e in enumerate(pal.entries) if any(max(abs(e[k] - t[k]) for k in range(3)) < 8 for t in soft)]
            if ids:
                colv = vol[:, rr, cc]
                for i_ in ids:
                    mat = pal.entries[i_][3]
                    colv[colv == i_] = pal(_hex(dst), mat)
                vol[:, rr, cc] = colv
        # the infield: the open middle of the building mass (the pitch), at ground level
        inf = o.get("infield")
        if inf:
            r0_, c0_ = rr.min(), cc.min()
            mm = np.zeros((rr.max() - r0_ + 3, cc.max() - c0_ + 3), bool)
            kk = bmask[rr, cc]
            mm[rr[kk] - r0_ + 1, cc[kk] - c0_ + 1] = True
            mm = ndimage.binary_closing(mm, iterations=3)
            hole = ndimage.binary_fill_holes(mm) & ~mm
            hr, hc = np.nonzero(hole)
            hr, hc = hr + r0_ - 1, hc + c0_ - 1
            gi = pal(_hex(inf["colour"]), MAT_IDS[inf.get("material", "grass")])
            vol[g[hr, hc] - 1, hr, hc] = gi
            # open above the pitch: the LiDAR column there (the hub and its cables) left a fat cylinder; keep only a
            # slim hub, 3 m across, hanging from 45 m up
            hcr, hcc = hr.mean(), hc.mean()
            for r_, c_ in zip(hr, hc):
                hub = abs(r_ - hcr) <= 1.5 and abs(c_ - hcc) <= 1.5
                vol[g[r_, c_]:g[r_, c_] + 45 if hub else vol.shape[0], r_, c_] = 0
            # the inner face of the bowl: seating tiers (red seat rows, grey walkways), not office windows
            seat, walk = pal(_hex("#b3343b"), 0), pal(_hex("#8f8f8c"), 0)
            depth_in = ndimage.distance_transform_edt(~hole)
            ir, ic = np.nonzero(mm & (depth_in <= 10))
            for r_, c_ in zip(ir + r0_ - 1, ic + c0_ - 1):
                nz = np.nonzero(vol[:, r_, c_])[0]
                if not len(nz):
                    continue
                for z_ in range(int(g[r_, c_]), int(nz[-1])):
                    if vol[z_, r_, c_]:
                        vol[z_, r_, c_] = walk if (z_ - g[r_, c_]) % 4 == 0 else seat
            floods.append([round(float(hc.mean()) + 0.5, 1), round(float(hr.mean()) + 0.5, 1), round(math.sqrt(len(hr) / math.pi), 1)])
            note("infield:", o.get("name", oid)[:30], len(hr), "cells")
        masts = _smooth_bowl(vol, g, bmask, pal, rr, cc, cx, cy, o["smooth"], note) if o.get("smooth") else []
        k_ = bmask[rr, cc]
        ring = st.get("ring", 1e9)  # only the facade: cells within this many metres of the building mass's outer edge
        r0, c0 = rr.min(), cc.min()
        m = np.zeros((rr.max() - r0 + 3, cc.max() - c0 + 3), bool)
        m[rr[k_] - r0 + 1, cc[k_] - c0 + 1] = True
        depth = ndimage.distance_transform_edt(ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=3)))
        n = 0
        for r, c in zip(rr[k_], cc[k_]):
            if depth[r - r0 + 1, c - c0 + 1] > ring:
                continue
            nz = np.nonzero(vol[:, r, c])[0]
            if not len(nz):
                continue
            z0, z1 = int(g[r, c]) + 3, int(nz[-1])
            if z1 <= z0:
                continue
            arc = (math.atan2(r + 0.5 - cy, c + 0.5 - cx) + math.pi) * R  # metres along the perimeter
            col = vol[z0:z1, r, c]
            if bands:
                hz = np.arange(z0, z1) - int(g[r, c])  # height above ground
                out = np.zeros_like(col)
                lo = 0
                for b, (to, kind) in zip(st["bands"], bands):
                    sel = (hz >= lo) & (hz < to)
                    if kind == "checker":  # panels of cell[0] m along x cell[1] m up, more of the second colour higher up
                        cw, ch = b["cell"]
                        rows = (hz[sel] - lo) // ch
                        t = rows / max(1, (to - lo) // ch - 1)
                        hsh = (np.int64(arc // cw) * 73856093 ^ rows.astype(np.int64) * 19349663) % 1000 / 1000
                        out[sel] = np.where(hsh < b.get("p", 0.25) + b.get("dp", 0.4) * t, chk[1], chk[0])
                    elif isinstance(kind, list):
                        per = sum(n for n, _ in kind)
                        ph = (hz[sel] - lo) % per
                        o_, acc = np.zeros(int(sel.sum()), out.dtype), 0
                        for n, cid in kind:
                            o_[(ph >= acc) & (ph < acc + n)] = cid
                            acc += n
                        out[sel] = o_
                    else:
                        out[sel] = kind
                    lo = to
                vol[z0:z1, r, c] = np.where(col != 0, out, 0)
            else:
                k = int(arc / st.get("width", 3)) % len(cols)
                vol[z0:z1, r, c] = np.where(col != 0, cols[k], 0)
            n += 1
        lean = o.get("smooth", {}).get("lean", 8)  # the masts lean outward (photos: spikes round the rim from above)
        for r, c, z0, z1, col, a in masts:
            for zz in range(z0, z1):
                t = lean * (zz - z0) / max(1, z1 - z0)
                vol[zz, int(round(r + t * math.sin(a))), int(round(c + t * math.cos(a)))] = col
        note("stripes:", o.get("name", oid)[:40], n, "columns")
    return floods


def _smooth_bowl(vol, g, bmask, pal, rr, cc, cx, cy, sm, note):
    """A stadium's roof as one smooth surface: its height is the median LiDAR height at each distance from the outer
    edge (1 m steps), so the masts and cable points no longer stand as radial fins round the facade; then
    sm["masts"] thin masts evenly round the rim, sm["mast_h"] m above the roof edge."""
    k = bmask[rr, cc]
    r0, c0 = rr.min() - 8, cc.min() - 8
    m = np.zeros((rr.max() - r0 + 9, cc.max() - c0 + 9), bool)
    m[rr[k] - r0, cc[k] - c0] = True
    # the bowl's outline smoothed: the masts' and stair cores' LiDAR footprints made a comb of fins round it
    sm_it = sm.get("outline", 6)
    mc = ndimage.binary_closing(m, iterations=sm_it)
    m = ndimage.binary_opening(ndimage.binary_fill_holes(mc), iterations=sm_it)
    lab, nl = ndimage.label(mc)  # the bowl is the largest piece; islands in the pitch (the hub's LiDAR) are not
    ring_ = lab == 1 + int(np.argmax(ndimage.sum(mc, lab, range(1, nl + 1))))
    hole = ndimage.binary_fill_holes(ring_) & ~ring_  # the pitch stays open
    yy, xx = np.mgrid[-6:7, -6:7]
    hole = ndimage.binary_closing(np.pad(hole, 8), xx ** 2 + yy ** 2 <= 36)[8:-8, 8:-8]  # no roof spikes into it
    # the opening is a rounded rectangle (ortho), a little smaller than the gap between the OSM stands
    hy, hx = np.nonzero(hole)
    a, b = (hx.max() - hx.min()) / 2 - sm.get("hole_shrink", 3), (hy.max() - hy.min()) / 2 - sm.get("hole_shrink", 3)
    gy, gx = np.mgrid[0:hole.shape[0], 0:hole.shape[1]]
    hole = (np.abs((gx - (hx.max() + hx.min()) / 2) / a) ** 4 + np.abs((gy - (hy.max() + hy.min()) / 2) / b) ** 4) <= 1
    inside = (m & ~hole)[rr - r0, cc - c0]
    in_hole = hole[rr - r0, cc - c0] & k
    hr_, hc_ = rr[hole[rr - r0, cc - c0]], cc[hole[rr - r0, cc - c0]]
    hubc = pal(_hex("#eceae4"), MAT_IDS["solid"])
    for r, c in zip(rr[in_hole], cc[in_hole]):  # open to the sky but for a slim white hub hanging 45-60 m up
        hub = abs(r - hr_.mean()) <= 1.5 and abs(c - hc_.mean()) <= 1.5
        vol[int(g[r, c]):, r, c] = 0
        if hub:
            vol[int(g[r, c]) + 45:int(g[r, c]) + 60, r, c] = hubc
        bmask[r, c] = False
    concrete = pal(_hex(sm.get("podium_colour", "#a3a29d")), MAT_IDS["concrete"])
    for r, c in zip(rr[k & ~inside & ~hole[rr - r0, cc - c0]], cc[k & ~inside & ~hole[rr - r0, cc - c0]]):
        zp = int(g[r, c]) + sm.get("podium", 8)  # outside the bowl: no more than the podium, in concrete
        vol[zp:, r, c] = 0
        nz = np.nonzero(vol[:zp, r, c])[0]
        if len(nz):
            vol[nz[-1], r, c] = concrete
    fill = pal(_hex(sm.get("mast_colour", "#ecedee")), MAT_IDS["solid"])
    for r, c in zip(rr[~k & inside], cc[~k & inside]):  # gaps in the outline: part of the bowl
        vol[int(g[r, c]):int(g[r, c]) + 1, r, c] = fill
        bmask[r, c] = True
    r_, c_ = rr[inside], cc[inside]
    orig = k[inside]  # measured columns (the gap cells just filled carry no height)
    depth = np.round(ndimage.distance_transform_edt(m)[r_ - r0, c_ - c0]).astype(int)
    tops = np.array([(np.nonzero(vol[:, r, c])[0][-1] + 1 if vol[:, r, c].any() else int(g[r, c])) for r, c in zip(r_, c_)]) - g[r_, c_]
    prof = np.zeros(depth.max() + 1)
    for d in range(len(prof)):
        v = tops[(depth == d) & orig]
        prof[d] = np.median(v) if len(v) else prof[d - 1]
    prof = np.maximum.accumulate(ndimage.median_filter(prof, 5))  # the membrane only rises inward
    n = sm.get("masts", 72)
    # the membrane sags between the radial cables, one per mast (ortho: radial panels, not rings), grey along each
    # cable; a translucent grey-blue ring round the opening
    frac = ((np.arctan2(r_ + 0.5 - cy, c_ + 0.5 - cx) + math.pi) / (2 * math.pi) * n) % 1.0
    sag = sm.get("sag", 1.5) * np.sin(math.pi * (frac - 0.5)) ** 2
    rad = np.hypot(r_ + 0.5 - cy, c_ + 0.5 - cx)
    on_cable = np.abs(frac - 0.5) * 2 * math.pi * rad / n < 0.6
    in_d = ndimage.distance_transform_edt(~hole)[r_ - r0, c_ - c0]
    memb, cable = pal(_hex("#eceae4"), MAT_IDS["solid"]), pal(_hex("#c3c6c8"), MAT_IDS["metal"])
    seat, walk = pal(_hex("#b3343b"), 0), pal(_hex("#8f8f8c"), 0)
    glass = pal(_hex(sm.get("ring_colour", "#8e9ca6")), MAT_IDS["glass"])
    for i_, (r, c, d) in enumerate(zip(r_, c_, depth)):
        z0, zt = int(g[r, c]), int(g[r, c] + round(prof[d] - sag[i_]))
        col = vol[:, r, c]
        nz = np.nonzero(col)[0]
        if not len(nz):
            continue
        top = nz[-1] + 1
        if top > zt:
            col[zt:] = 0
        elif top < zt:
            col[top:zt] = col[top - 1]
        col[z0 + 1:zt][col[z0 + 1:zt] == 0] = col[zt - 1]  # no hollows under the roof
        col[zt - 1] = glass if in_d[i_] <= sm.get("ring", 8) else cable if on_cable[i_] else memb
        # the stands: seating rakes up from the pitch under a thin roof (not a 50 m cliff round the opening)
        if in_d[i_] <= sm.get("stands", 45):
            zs = min(z0 + 2 + int(0.75 * in_d[i_]), zt - 5)
            col[zt - 1 - 2:zt - 1] = col[zt - 1] if in_d[i_] <= sm.get("ring", 8) else memb
            col[zs:zt - 3] = 0
            for zz in range(z0 + 1, zs):
                col[zz] = walk if (zz - z0) % 4 == 0 else seat
    white = pal(_hex(sm.get("mast_colour", "#ecedee")), MAT_IDS["metal"])
    rim = (depth == 1)
    ang = np.arctan2(r_[rim] + 0.5 - cy, c_[rim] + 0.5 - cx)
    masts = []
    for kk in range(n):  # just outside the facade, from the ground to mast_h above the roof edge (photos)
        a = -math.pi + (kk + 0.5) * 2 * math.pi / n
        i = int(np.argmin(np.abs((ang - a + math.pi) % (2 * math.pi) - math.pi)))
        r, c = int(round(r_[rim][i] + 2 * math.sin(a))), int(round(c_[rim][i] + 2 * math.cos(a)))
        masts.append((r, c, int(g[r, c]), int(g[r, c] + round(prof[1])) + sm.get("mast_h", 18), white, a))
    note(f"smooth bowl: roof {prof[1]:.0f}-{prof.max():.0f} m over {len(prof)} m depth, {n} masts")
    return masts


def apply_zones(vol, g, feats, pal, bmask, note):
    """Facade zones and crown bands from overrides.json, painted onto the voxels of the building's footprint."""
    by_outline = {}
    for f in feats:
        o = override_for(f)
        if o and ("zones" in o or "crown" in o):
            root = f.get("parent") or f
            by_outline.setdefault(root["id"], (o, []))[1].append(f)
    for oid, (o, fs) in by_outline.items():
        rr = np.concatenate([f["rr"] for f in fs])
        cc = np.concatenate([f["cc"] for f in fs])
        keep = bmask[rr, cc]
        rr, cc = rr[keep], cc[keep]
        if len(rr) == 0:
            continue
        # long axis of the footprint; "west" end = smaller grid column
        pts = np.stack([cc, rr], 1).astype(float)
        mu = pts.mean(0)
        _, _, vt = np.linalg.svd(pts - mu, full_matrices=False)
        ax = vt[0] if vt[0][0] >= 0 else -vt[0]
        t = (pts - mu) @ ax
        t = (t - t.min()) / max(np.ptp(t), 1e-6)
        zone_of = np.full(len(rr), -1)
        for k, z in enumerate(o.get("zones", [])):
            tt = t if z.get("origin", "west") in ("west", "north") else 1 - t
            m = (tt >= z["from"]) & (tt <= z["to"]) & (zone_of < 0)
            zone_of[m] = k
            idx = _style(pal, z["wall"])
            for r, c in zip(rr[m], cc[m]):
                col = vol[:, r, c]
                nz = np.nonzero(col)[0]
                nz = nz[nz >= g[r, c]]
                if len(nz) > 1:
                    col[nz[:-1]] = idx  # keep the roof voxel
        cr = o.get("crown")
        if cr:
            m = t <= cr.get("tip", 1.0)
            fp = np.zeros(vol.shape[1:], bool)
            fp[rr, cc] = True
            edge_fp = fp & ~ndimage.binary_erosion(fp)  # facade cells only
            band, sign = _style(pal, cr), pal(_hex(cr.get("sign_colour", cr["colour"])), MAT_IDS["sign"])
            for r, c in set(zip(rr[m], cc[m])):
                if not edge_fp[r, c]:
                    continue
                nz = np.nonzero(vol[:, r, c])[0]
                top = nz.max()
                for k in range(0, cr["height"]):
                    vol[top - k, r, c] = sign if (k == 0 and (r + c) % 2 == 0) else band
        if "roof" in o:
            ridx = _style(pal, o["roof"])
            for r, c in zip(rr, cc):
                vol[np.nonzero(vol[:, r, c])[0].max(), r, c] = ridx
        note(f"override zones: {o.get('name', oid)}: {len(rr)} cells, zones "
             f"{[int((zone_of == k).sum()) for k in range(len(o.get('zones', [])))]}")


def override_labels(feats, g, top_at):
    out = []
    for f in feats:
        o = OVERRIDES.get(str(f["id"]))
        if o and "label" in o and not f["part"] and len(f["rr"]):
            k = len(f["rr"]) // 2
            r, c = int(np.median(f["rr"])), int(np.median(f["cc"]))
            out.append(label(o["label"]["name"], o["label"], c, r, top_at(r, c)))
    return out


def _name(f):
    return f["tags"].get("name") or (f.get("parent") or {}).get("tags", {}).get("name")


def small_tree_size(h, height=None):
    """A young tree's (clear trunk, height) in cells, as small_tree draws it, without drawing it."""
    H = int(height or 7 + h % 3)
    return max(3, int(H * 0.42)), H


def small_tree(vol, g, r, c, h, leaves, trunk, height=None):
    """A young street tree as planted 2025-26 (Plac Centralny, Złota): photos show a clear trunk to ~4 m and a
    narrow, airy crown on top (docs/warsaw/visual_ref.md, Złota 2026 photos). Returns (clear trunk, height) in cells."""
    tr, H = small_tree_size(h, height)
    z0 = int(g[r, c])
    vol[z0:z0 + tr, r, c] = trunk
    leaf = leaves[1 + (h >> 8) % 4]
    leaf2 = leaves[(1 + (h >> 8) % 4 + 2) % len(leaves)]
    ch = H - tr  # crown height
    for k in range(ch):
        f = (k + 0.5) / ch
        rad = 0.6 + 1.3 * math.sin(math.pi * min(1.0, f * 1.1))  # spindle, widest just below the middle
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                d = (dr * dr + dc * dc) ** 0.5
                if d > rad:
                    continue
                if d > 0.5 and ((h >> ((k * 5 + dr * 3 + dc + 20) % 28)) & 7) == 0:
                    continue  # airy gaps
                zz, rr, cc = z0 + tr + k, r + dr, c + dc
                if 0 <= rr < vol.shape[1] and 0 <= cc < vol.shape[2] and zz < vol.shape[0] and vol[zz, rr, cc] == 0:
                    vol[zz, rr, cc] = leaf if (dr + dc + k) % 3 else leaf2
    vol[z0 + tr:z0 + H - 1, r, c] = trunk  # leader through the crown
    return tr, H


def wall_override(f, pal):
    o = override_for(f)
    return _style(pal, o["wall"]) if o and "wall" in o else None


def roof_override(f, pal):
    o = override_for(f)
    return _style(pal, o["roof"]) if o and "roof" in o else None


def details_geometry(vol, g, feats, pal, note):
    """Every curated change to the landmarks' voxels (also run alone by patch.py on the cached volume)."""
    f = _by_id(feats, PUERTA_DE_ALCALA)
    if f is not None:
        puerta_de_alcala(vol, g, f["geom"], pal, note)
    f = _by_id(feats, PALACIO_REAL)
    if f is not None:
        # white Colmenar limestone over a granite ground floor, not the historic core's brick and render; its
        # windows in bays of about 5 m, on the ground floor, the main floor and the two above
        geom = f["geom"]
        recolour_walls(vol, g, geom, pal, "#e4ddcd", MAT_IDS["classic"], note, "Palacio Real")
        D, W = g.shape
        rr, cc = _cells_geom(geom.buffer(1.0), D, W)
        granite = pal(_hex("#aaa59b"), MAT_IDS["classic"])
        stone = pal(_hex("#e4ddcd"), MAT_IDS["classic"])
        for r, c in zip(rr, cc):
            col = vol[int(g[r, c]):int(g[r, c]) + 5, r, c]
            col[col == stone] = granite
        n = edge_windows(vol, g, geom, pal((58, 70, 68), MAT_IDS["window"]), ((2, 3), (9, 4), (16, 3), (22, 2)), 5.0)
        note(f"Palacio Real: {n} window bays")
    f = _by_id(feats, METROPOLIS)
    if f is not None:
        # white stone, and over the corner rotunda the black slate dome with gilded ribs and the gilded Victory
        recolour_walls(vol, g, f["geom"], pal, "#ebe5d8", MAT_IDS["wall"], note, "Edificio Metrópolis")
        statue = lidar_statue(vol, g, f["geom"])
        dome(vol, g, f["geom"], pal, 31, 33, "#2c2f35", note, "Edificio Metrópolis", gold="#c9a54a", radius=9)
        if statue:
            victory(vol, *statue, pal(_hex("#c9a54a"), MAT_IDS["metal"]))
            note(f"Edificio Metrópolis: the Victory at {statue[:2]}, facing {statue[2]}")
    f = _by_id(feats, ALMUDENA)
    if f is not None:
        # white limestone and grey granite; the dome and its lantern in blue-grey slate
        recolour_walls(vol, g, f["geom"], pal, "#e2ddd2", MAT_IDS["classic"], note, "Catedral de la Almudena")
        dome(vol, g, f["geom"], pal, 44, 48, "#5c6670", note, "Catedral de la Almudena", radius=14)
    f = _by_id(feats, PALACIO_DE_CRISTAL)
    if f is not None:
        palacio_de_cristal(vol, g, f["geom"], pal, note)
    f = _by_id(feats, CONGRESO)
    if f is not None:
        congreso(vol, g, f["geom"], pal, note)


PALACIO_REAL, METROPOLIS, ALMUDENA, PALACIO_DE_CRISTAL = 30399, 4655046, 75658, 23596451  # OSM relations and way


def dome(vol, g, geom, pal, z_rel, min_top, hex_, note, name, gold=None, radius=None):
    """The voxels of a dome: in the footprint's columns that rise to at least `min_top` m, everything from `z_rel` m
    up, in one colour as metal (slate, lead), with its ribs in `gold` if given (every fourth cell round the dome
    and the top voxel). Returns (row, col, z above the top) of its highest column, for a lantern or a statue."""
    D, W = g.shape
    rr, cc = _cells_geom(geom, D, W)
    T = _top_rel(vol, g, rr, cc)
    m = T >= min_top
    if not m.any():
        return None
    rr, cc, T = rr[m], cc[m], T[m]
    if radius:  # only round the highest column (other roofs of the block reach the same height)
        k = int(np.argmax(T))
        m = np.hypot(rr - rr[k], cc - cc[k]) <= radius
        rr, cc, T = rr[m], cc[m], T[m]
    slate = pal(_hex(hex_), MAT_IDS["metal"])
    rib = pal(_hex(gold), MAT_IDS["metal"]) if gold else slate
    cy, cx = rr.mean(), cc.mean()
    for r, c in zip(rr, cc):
        col = vol[:, r, c]
        z0 = int(g[r, c]) + z_rel
        nz = np.nonzero(col[z0:])[0] + z0
        ang = int(math.degrees(math.atan2(r - cy, c - cx)) // 22.5)
        col[nz] = rib if ang % 4 == 0 else slate
    k = int(np.argmax(T))
    r, c = int(rr[k]), int(cc[k])
    z = int(g[r, c]) + int(T[k])
    vol[z - 1, r, c] = rib
    note(f"{name}: dome over {len(rr)} columns, top {int(T[k])} m")
    return r, c, z


def lidar_statue(vol, g, geom, radius=7, rise=4):
    """A statue on a dome as the LiDAR reads it: a thin slab of columns standing more than `rise` m over the median
    top of the dome around the highest one. The slab is cleared down to the highest column around it that is not
    part of it. Returns its middle cell and the way it faces (fx, fy), along the grid axis across its longer side
    (a winged figure's wings make the long side) and out of the building, or None."""
    D, W = g.shape
    rr, cc = _cells_geom(geom, D, W)
    T = _top_rel(vol, g, rr, cc)
    k = int(np.argmax(T))
    near = np.hypot(rr - rr[k], cc - cc[k]) <= radius
    spike = near & (T > np.median(T[near]) + rise)
    if not spike.any() or not (near & ~spike).any():
        return None
    level = int(T[near & ~spike].max())
    for r, c in zip(rr[spike], cc[spike]):
        vol[int(g[r, c]) + level + 1:, r, c] = 0
    r, c = int(round(rr[spike].mean())), int(round(cc[spike].mean()))
    dx, dy = c + 0.5 - geom.centroid.x, r + 0.5 - geom.centroid.y
    if np.ptp(rr[spike]) >= np.ptp(cc[spike]):
        return r, c, (int(np.sign(dx)) or 1, 0)
    return r, c, (0, int(np.sign(dy)) or 1)


def victory(vol, r, c, facing, gold):
    """The Victoria Alada over the Metrópolis's dome (Federico Coullaut-Valera, 1977): gilded bronze, 6 m, standing
    with her wings spread and a little raised, drapery falling at her sides (photographs), on the top of the column
    (r, c), facing (fx, fy) along a grid axis so that her wings stay joined."""
    fx, fy = facing
    lx, ly = -fy, fx  # across her shoulders
    z = int(np.nonzero(vol[:, r, c])[0].max()) + 1

    def put(lat, fw, z0, z1):
        vol[z0:z1, r + ly * lat + fy * fw, c + lx * lat + fx * fw] = gold

    put(0, 0, z, z + 6)  # legs, body and head
    put(0, -1, z + 4, z + 5)  # the wings' root at her back
    for s in (-1, 1):
        put(s, 0, z + 2, z + 4)  # the drapery at her sides
        put(s, -1, z + 4, z + 5)  # the wings, from behind her shoulders out to 4 m each side
        put(2 * s, -1, z + 4, z + 6)
        put(3 * s, -1, z + 5, z + 6)
        put(4 * s, -1, z + 5, z + 6)


def palacio_de_cristal(vol, g, geom, pal, note):
    """The Palacio de Cristal (Velázquez Bosco, 1887): glass on a white iron frame, a glass dome over the centre.
    The LiDAR's surface is kept; its voxels turn to clear glass, with the frame in white iron every 3 m along both
    axes and at every 4th m of height."""
    D, W = g.shape
    rr, cc = _cells_geom(geom, D, W)
    glass = pal(_hex("#c8dce2"), MAT_IDS["glass"])
    iron = pal(_hex("#eeeeea"), MAT_IDS["metal"])
    (cx, cy), (ux, uy), (vx, vy), _, _ = _frame(geom)
    n = 0
    for r, c in zip(rr, cc):
        col = vol[:, r, c]
        gz = int(g[r, c])
        nz = np.nonzero(col[gz + 1:])[0] + gz + 1
        if not len(nz):
            continue
        a, b = (c + 0.5 - cx) * ux + (r + 0.5 - cy) * uy, (c + 0.5 - cx) * vx + (r + 0.5 - cy) * vy
        frame = int(a) % 3 == 0 or int(b) % 3 == 0
        for z in nz:
            if mats_of(pal, col[z]) not in (3, 8):  # not the crowns over it
                col[z] = iron if frame or (z - gz) % 4 == 0 else glass
        n += 1
    note(f"Palacio de Cristal: {n} columns in glass and iron")


def _frame(geom):
    """A footprint's own frame from its minimum rotated rectangle: centre (x, y), unit vector along the long side,
    unit vector across, length and depth, in cells."""
    xs, ys = geom.minimum_rotated_rectangle.exterior.coords.xy
    p = list(zip(xs, ys))[:3]
    e = [(p[1][0] - p[0][0], p[1][1] - p[0][1]), (p[2][0] - p[1][0], p[2][1] - p[1][1])]
    n = [math.hypot(*v) for v in e]
    k = 0 if n[0] >= n[1] else 1
    u = (e[k][0] / n[k], e[k][1] / n[k])
    c = geom.minimum_rotated_rectangle.centroid
    return (c.x, c.y), u, (-u[1], u[0]), n[k], n[1 - k]


PUERTA_DE_ALCALA = 174805987  # OSM way


def puerta_de_alcala(vol, g, geom, pal, note):
    """The Puerta de Alcalá (Sabatini, 1778): granite with ornaments in white Colmenar limestone, 44 m long and 22 m
    high at the central pediment, about 25 m to the top of the arms over it. Five openings: three round arches of
    nearly one size and a square-headed one at each end. Columns with Ionic capitals stand on the east face, the
    outer one, ten in all (one at each end, one by each door, three either side of the central arch); on the west
    face only the four beside the central arch, the others being pilasters. Cornice at 13.3 m and a parapet to 15 m
    over the whole length. The central body, 14.4 m long, stands forward of the sides and rises in an attic with the
    inscription (REGE CAROLO III, ANNO MDCCLXXVIII) to a pediment roofed in lead: curved on the east, triangular on
    the west. Over it, on the east, the royal arms held by Fame and a child; on the west, trophies of arms. Sculpture
    groups (children and trophies, the four cardinal virtues on the west) stand on the parapet over the columns; the
    arches' keystones carry masks and lions' heads, and the panels over the doors garlands and cornucopias.
    The LiDAR and OSM read it as a block of flats, so its footprint is cleared and the gate rebuilt in its own frame,
    scaled to the footprint's length. Measured in proportion on photographs of both faces (Commons, "Puerta de Alcalá
    2025" and "Puerta de Alcalá (Madrid) 12") and the description in the Spanish Wikipedia."""
    (cx, cy), (ux, uy), (vx, vy), L, Dp = _frame(geom)
    s = L / 44.0  # proportions from the 44 m elevation
    D, W = g.shape
    rr, cc = _cells_geom(geom.buffer(1.5), D, W)
    zb = int(np.median(g[rr, cc]))
    Z = lambda m: zb + int(round(m * s))  # noqa: E731  (metres of the elevation -> level)
    stone = pal(_hex("#d9d1c1"), MAT_IDS["classic"])
    granite = pal(_hex("#a9a49a"), MAT_IDS["classic"])
    white = pal(_hex("#e8e2d5"), MAT_IDS["classic"])  # the limestone: capitals, keystones, panels, sculpture
    lead = pal(_hex("#7c8085"), MAT_IDS["metal"])
    for r, c in zip(rr, cc):
        vol[g[r, c]:zb + 40, r, c] = 0
    east = 1 if vx > 0 else -1  # the across axis's side that faces east, out of the old town
    half = Dp / 2 - 1  # OSM's outline takes in the columns and the steps
    CB, RISE = 7.2, 2.6  # the central body's half-length and the pediment's rise, in metres
    R = (CB * CB + RISE * RISE) / (2 * RISE)  # the curved pediment's radius
    arches = [(0.0, 2.4, 7.3), (-10.5, 2.5, 6.9), (10.5, 2.5, 6.9)]  # centre, half-width, springing (m)
    doors = [(-16.3, 1.6, 6.0), (16.3, 1.6, 6.0)]  # centre, half-width, head
    columns = {1: (-20.1, -14.5, -7.1, -5.7, -4.0, 4.0, 5.7, 7.1, 14.5, 20.1), -1: (-5.7, -4.0, 4.0, 5.7)}
    near = lambda a, m: abs(a - m * s) < 0.6  # noqa: E731
    n = 0
    r0, r1 = int(cy - L / 2 - 4), int(cy + L / 2 + 5)
    c0, c1 = int(cx - L / 2 - 4), int(cx + L / 2 + 5)
    for r in range(max(r0, 0), min(r1, D)):
        for c in range(max(c0, 0), min(c1, W)):
            dx, dy = c + 0.5 - cx, r + 0.5 - cy
            a, b = dx * ux + dy * uy, dx * vx + dy * vy  # along, across
            if abs(a) > L / 2 + 1 or abs(b) > half + 1:
                continue
            col = vol[:, r, c]
            gz = int(g[r, c])
            central = abs(a) < CB * s
            face = half if central else half - 1  # the side bodies stand a cell behind the central one
            side = 1 if b * east > 0 else -1  # the east face or the west
            if abs(a) > L / 2:
                if abs(b) <= face:  # the cornice runs round the ends too
                    col[Z(13.3):Z(14.2)] = stone
                continue
            if abs(b) > face:  # the course proud of the faces: columns, cornices, plinth, keystones
                if abs(b) > face + 1:
                    continue
                if any(near(a, k) for k in columns[side]):
                    col[gz:Z(10.3)] = stone
                    col[Z(10.3):Z(11.3)] = white
                col[Z(13.3):Z(14.2)] = stone
                if central:
                    col[Z(18.6):Z(19.4)] = stone  # the attic's cornice
                col[gz:zb + 1] = granite
                for ac, hw, spring in arches:
                    if near(a, ac):
                        col[Z(spring + hw) - 1:Z(spring + hw) + 1] = white
                continue
            top = 15.0
            if central:  # the attic and its pediment
                x = abs(a) / s
                top = 19.4 + max(math.sqrt(R * R - x * x) - (R - RISE) if side == 1 else RISE * (1 - x / CB), 0)
            zt = Z(top)
            col[gz:zt] = stone
            col[gz:zb + 1] = granite
            if central:
                col[zt - 1] = lead
                if abs(a) < 2.2 * s and abs(b) > face - 1:
                    col[Z(16.0):Z(18.3)] = white  # the inscription's tablet
            for dc_, hw, head in doors:
                if abs(b) > face - 1 and abs(a - dc_ * s) < 1.5 * s:
                    col[Z(7.5):Z(9.5)] = white  # the panel over the door
            for ac, hw, spring in arches:
                du = (a - ac * s) / s
                if abs(du) < hw:
                    col[gz:Z(spring + math.sqrt(hw * hw - du * du))] = 0
            for dc_, hw, head in doors:
                if abs(a - dc_ * s) < hw * s:
                    col[gz:Z(head)] = 0
            n += 1

    def put(m, bb, h):  # h voxels of sculpture over whatever stands at m metres along, bb cells across
        x, y = cx + ux * m * s + vx * bb, cy + uy * m * s + vy * bb
        col = vol[:, int(y), int(x)]
        z = int(np.nonzero(col)[0].max()) + 1
        col[z:z + h] = white

    for side in (1, -1):
        sgn = east * side
        bb = sgn * (half - 1.5)  # on the side bodies' parapet
        for m in (-20.1, -14.5, 14.5, 20.1):
            if side == 1:  # a child standing by a trophy
                put(m, bb, 3)
                put(m + (1 if m > 0 else -1), bb, 1)
            else:  # a virtue, or a helmet over flags
                put(m, bb, 3)
                put(m - 1, bb, 1)
                put(m + 1, bb, 1)
        for bc in (sgn * (half - 1.5), sgn * (half - 2.5)):  # over the pediment, two cells deep
            if side == 1:  # the arms with the crown, Fame reclining on one side, the child on the other
                for m, h in ((-1, 3), (0, 4), (1, 3), (-2.5, 2), (-3.5, 1), (2.5, 2)):
                    put(m, bc, h)
            else:  # trophies: an empty armour with its helmet, shields and flags
                for m, h in ((0, 3), (-1, 2), (1, 2), (-3, 1), (3, 1)):
                    put(m, bc, h)
    note(f"Puerta de Alcalá rebuilt: {n} columns, {L:.0f} x {Dp:.0f} m")


CONGRESO = 4545711  # OSM relation: the Palacio del Congreso de los Diputados
CONGRESO_LIONS = ((440882.8, 4474178.8), (440898.3, 4474173.0))  # OSM nodes Daoiz and Velarde (EPSG:25830)


def congreso(vol, g, geom, pal, note):
    """The Palacio del Congreso de los Diputados (Narciso Pascual y Colomer, 1843-1850). A two-storey palace in grey
    granite, the ground floor rusticated, the main floor's windows under straight pediments, a cornice at about 17 m
    and hipped roofs in grey zinc round light wells. On the Carrera de San Jerónimo, the 18 m portico: six fluted
    Corinthian columns two storeys high in white stone, an entablature with CONGRESO DE LOS DIPUTADOS on the
    architrave, and a triangular pediment (Ponciano Ponzano's relief of Spain embracing the Constitution, a rise of
    two fifths of its half-width) standing clear of the roofs behind; the bronze doors behind, opened only for the King's opening of
    the Cortes; a flight of granite steps in front, the bronze lions Daoiz and Velarde (Ponzano, cast in 1866 from
    cannon of the African war) on pedestals at its ends. The session hall's semicircular glass vault stands over the
    middle of the roof, 43 m behind the facade.
    The LiDAR read it as a block whose portico melted into the steps, so the main block is rebuilt from its footprint
    (classic_rebuild) and the portico drawn in its own frame, set by the two lions (OSM): its axis between them, the
    facade line the footprint's edge beside it. Proportions from photographs of the facade (Commons, "España - Madrid -
    Palacio de las Cortes - Fachada", "Congreso de los Diputados, enero de 2015", "Congreso de los Diputados (España)
    02"), the bays and the portico's width from OSM, heights from the LiDAR."""
    C = 1 / VOXEL_SIZE  # metres -> cells and levels
    D, W = g.shape
    (l1x, l1y), (l2x, l2y) = (tuple(float(v) for v in to_grid(*p)) for p in CONGRESO_LIONS)
    tx, ty = l2x - l1x, l2y - l1y
    n_ = math.hypot(tx, ty)
    tx, ty = tx / n_, ty / n_  # along the facade
    cx0, cy0 = geom.centroid.x, geom.centroid.y
    mx, my = (l1x + l2x) / 2, (l1y + l2y) / 2
    nx, ny = -ty, tx
    if (mx - cx0) * nx + (my - cy0) * ny < 0:
        nx, ny = -nx, -ny  # out of the building, over the street
    ab = lambda x, y: ((x - mx) * tx + (y - my) * ty, (x - mx) * nx + (y - my) * ny)  # noqa: E731  (along, out)
    # the facade line: the footprint's edge either side of the portico, and the front of the steps
    pts = [ab(x, y) for x, y in geom.exterior.coords]
    wall_b = max(b for a, b in pts if 10 * C < abs(a) < 20 * C)
    front_b = max(b for a, b in pts if abs(a) < 9 * C)
    HW = 9.2 * C  # the pediment's half-width
    cut = Polygon([(mx + tx * a + nx * b, my + ty * a + ny * b) for a, b in
                   ((-HW - 1, wall_b), (HW + 1, wall_b), (HW + 1, front_b + 2), (-HW - 1, front_b + 2))])
    main = geom.difference(cut)
    main = max(main.geoms, key=lambda p: p.area) if main.geom_type == "MultiPolygon" else main
    granite = "#c9c6bf"
    # the roofs rise gently from behind the cornice and stay under the pediment's apex, as seen from the street
    classic_rebuild(vol, g, pal, main, int(round(17 * C)), 0.35, granite, "#a6a9ab", note, "Palacio del Congreso",
                    rows=((int(2 * C), int(4 * C)), (int(10 * C), int(4 * C))), bay=5.0 * C, attic=1, cap=int(20 * C))
    # the rusticated ground floor a shade darker
    rr, cc = _cells_geom(main.buffer(1.0), D, W)
    wall, rustic = pal(_hex(granite), MAT_IDS["classic"]), pal(_hex("#b4b1aa"), MAT_IDS["classic"])
    for r, c in zip(rr, cc):
        col = vol[int(g[r, c]):int(g[r, c]) + int(7 * C), r, c]
        col[col == wall] = rustic
    # the session hall's glass vault: a half dome over the roof, ribbed every 15 degrees
    zinc, glass = pal(_hex("#b9bcbd"), MAT_IDS["metal"]), pal(_hex("#9fbccd"), M_GLASS)
    hx, hy, R = mx - nx * 43 * C, my - ny * 43 * C, 13 * C
    for r in range(int(hy - R) - 1, int(hy + R) + 2):
        for c in range(int(hx - R) - 1, int(hx + R) + 2):
            a, b = ab(c + 0.5, r + 0.5)
            b += 43 * C  # from the vault's straight side, out towards the facade
            d = math.hypot(a, b)
            if b > 0 or d > R:
                continue
            col = vol[:, r, c]
            nz = np.nonzero(col)[0]
            if not len(nz) or nz[-1] - g[r, c] < 12 * C:
                continue
            z0 = int(g[r, c]) + int(17 * C)
            h = int(round(4 * C * math.sqrt(max(1 - (d / R) ** 2, 0))))
            col[z0 + 1:z0 + 8] = 0
            col[z0:z0 + h + 1] = zinc
            if d < R - 1 and int(math.degrees(math.atan2(b, a)) // 15) % 2 == 0:
                col[z0 + h] = glass
    # the portico: cleared, then the steps, the floor, the columns, the entablature and the pediment
    stone = pal(_hex("#e6e2d8"), MAT_IDS["classic"])
    white = pal(_hex("#f1eee6"), MAT_IDS["classic"])  # capitals, the inscription, the relief's figures
    bronze = pal(_hex("#4a4436"), MAT_IDS["metal"])
    lead = pal(_hex("#8d9093"), MAT_IDS["metal"])
    step = pal(_hex("#b4b1aa"), MAT_IDS["classic"])
    zb = int(np.median([g[int(y), int(x)] for x, y in ((l1x, l1y), (l2x, l2y))]))
    Z = lambda m: zb + int(round(m * C))  # noqa: E731
    COLS = [k * 3.2 * C for k in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)]  # six columns, 3.2 m apart
    col_b = wall_b + 2.4 * C  # their row out from the wall; the steps take the rest, down to the lions
    col_cells = {(int(my + ty * k + ny * col_b), int(mx + tx * k + nx * col_b)) for k in COLS}
    ent_b = col_b + 0.7 * C  # the entablature's and pediment's front
    n_cols = 0
    for r in range(int(min(l1y, l2y) - 16 * C), int(max(l1y, l2y) + 16 * C)):
        for c in range(int(min(l1x, l2x) - 16 * C), int(max(l1x, l2x) + 16 * C)):
            if not (0 <= r < D and 0 <= c < W):
                continue
            a, b = ab(c + 0.5, r + 0.5)
            if abs(a) > HW + 0.5 or b < wall_b - 0.5 or b > front_b + 1.5:
                continue
            col = vol[:, r, c]
            gz = int(g[r, c])
            col[gz:gz + int(30 * C)] = 0
            if b > front_b - 0.5:  # the bottom step
                col[gz:Z(0.5)] = step
                continue
            if b > ent_b + 0.5:  # the flight up to the portico floor
                col[gz:Z(1.0)] = step
                continue
            col[gz:Z(1.5)] = step  # the portico's floor
            if b > wall_b + 0.5:
                if (r, c) in col_cells:
                    col[Z(1.5):Z(14.0)] = stone
                    col[Z(14.0):Z(15.0)] = white
                    n_cols += 1
            else:  # the wall behind, the bronze doors in it
                col[Z(1.5):Z(17)] = stone
                if abs(a) < 1.6 * C:
                    col[Z(1.5):Z(7.5)] = bronze
            col[Z(15.0):Z(18.0)] = stone  # architrave, frieze and cornice
            if b > ent_b - 0.5 and abs(a) < 5.5 * C:
                col[Z(15.4):Z(16.4)] = white  # CONGRESO DE LOS DIPUTADOS
            top = 18.0 + 0.45 * (HW - abs(a)) / C  # the pediment
            col[Z(18.0):Z(top)] = stone
            col[Z(top) - 1] = lead
            if b > ent_b - 0.5:  # the relief's figures, a frieze of them along the tympanum's floor, the seated Spain higher
                if abs(a) < 6.5 * C and int(math.floor(a / C)) % 2 == 0:
                    col[Z(18.0)] = white
                if abs(a) < 1.5 * C:
                    col[Z(18.0):Z(20.0)] = white
    # the lions on their pedestals, facing the street
    for lx, ly in ((l1x, l1y), (l2x, l2y)):
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                x, y = lx + tx * da + nx * db, ly + ty * da + ny * db
                col = vol[:, int(y), int(x)]
                gz = int(g[int(y), int(x)])
                col[gz:Z(2.0)] = step
                if da == 0 and db >= 0:
                    col[Z(2.0):Z(3.5)] = bronze
                    if db == 1:
                        col[Z(3.5)] = bronze  # the head and mane
    note(f"Palacio del Congreso: portico of {n_cols} column cells, facade at {wall_b:.1f}, steps to {front_b:.1f} m")


MON_TOP = np.zeros((_D, _W), np.int32)  # top of the monuments (monuments.build), for label heights


def details(vol, g, top, topi, bmask, feats, pal, C, osm, cells_of, note, leaf_ids=()):
    details_geometry(vol, g, feats, pal, note)
    roofgardens.build(vol, g, bmask, pal, osm, cells_of, _orto(), C["garden"], note)
    global MON_TOP
    MON_TOP = monuments.build(vol, g, pal, note, keep=set(leaf_ids) | {C["trunk"]})

    def top_at(r, c):
        col = np.nonzero(vol[:, r, c])[0]
        return int(col[-1]) + 1 if len(col) else int(g[r, c])

    found = {}
    for oid, typ, t, geom in osm.areas:
        n = t.get("name")
        if n not in LABELS or n in found:
            continue
        facts = LABELS[n]
        if facts.get("anchor") == "top":
            rr, cc = cells_of(geom)
            if len(rr) == 0:
                continue
            k = np.argmax(topi[rr, cc] + g[rr, cc])
            r, c = int(rr[k]), int(cc[k])
        else:
            p = geom.representative_point() if not geom.contains(geom.centroid) else geom.centroid
            r, c = int(p.y), int(p.x)
        if 0 <= r < vol.shape[1] and 0 <= c < vol.shape[2]:
            found[n] = label(n, facts, c, r, top_at(r, c))
    labels = [found[n] for n in LABELS if n in found] + override_labels(feats, g, top_at)
    for n, facts in EXTRA_LABELS.items():
        c, r = (int(v) for v in to_grid(*facts["at"]))
        labels.append(label(n, facts, c, r, top_at(r, c)))
    note("labels:", [l["name"] for l in labels])
    return labels, make_views(g)


def make_views(g):
    """Camera presets in three.js coords (x = col, y = up, z = row): the map's centre from above and obliquely, and
    Calle Mayor at street level looking at Puerta del Sol. At street level the target sits just below the eye: OrbitControls'
    tilt limit lifts a camera that looks up."""
    H_, W_ = g.shape
    cx, cz = W_ / 2, H_ / 2
    gz = lambda x, z: float(g[int(z), int(x)])  # noqa: E731
    mx, mz = (float(v) for v in to_grid(440224.1, 4474235.9))  # Calle Mayor centreline (OSM), 125 m west of Sol
    sx, sz = (float(v) for v in to_grid(440316.4, 4474264.1))  # Puerta del Sol (centre of the OSM square, relation 7424032)
    views = {
        "overview": dict(label="Overview", target=[cx, gz(cx, cz), cz], pos=[cx + 330, 380, cz + 420]),
        "top": dict(label="Top-down", target=[cx, gz(cx, cz), cz], pos=[cx, 900, cz + 1]),
        "sol": dict(label="Puerta del Sol", target=[cx, gz(cx, cz) + 8, cz], pos=[cx + 150, gz(cx, cz) + 110, cz + 170]),
    }
    if 0 <= mx < W_ and 0 <= mz < H_:
        views["street"] = dict(label="Calle Mayor", target=[sx, gz(mx, mz) + 1.5, sz], pos=[mx, gz(mx, mz) + 2.5, mz])
    return views


# views of the required landmarks (fetch_wikidata.REQUIRED), by Wikidata id: (key, label, landmarks framed, camera
# offset from their middle in metres: east, up, south)
LANDMARK_VIEWS = [
    ("sol", "Puerta del Sol", ["Q427163"], (150, 110, 170)),
    ("palace", "Royal Palace and Almudena", ["Q171517", "Q849711"], (-260, 170, 320)),
    ("plazamayor", "Plaza Mayor", ["Q1123493"], (140, 120, 160)),
    ("granvia", "Gran Vía and Metrópolis", ["Q465250"], (-260, 130, -120)),
    ("cibeles", "Cibeles and Puerta de Alcalá", ["Q2736564", "Q1140634"], (-420, 160, 180)),
    ("prado", "Prado and the Retiro", ["Q160112"], (-330, 190, 190)),
]


def landmark_views(labels, g):
    """Camera presets framing the required landmarks, from where their labels stand; the map's centre views otherwise."""
    at = {l.get("qid"): l for l in labels if l.get("qid")}
    H_, W_ = g.shape
    views = {}
    for key, name, qids, (dx, dy, dz) in LANDMARK_VIEWS:
        ls = [at[q] for q in qids if q in at]
        if not ls:
            continue
        x, z = float(np.mean([l["x"] for l in ls])) + 0.5, float(np.mean([l["y"] for l in ls])) + 0.5
        y = float(g[int(z), int(x)]) + 10
        px, pz = float(np.clip(x + dx, 0, W_)), float(np.clip(z + dz, 0, H_))
        views[key] = dict(label=name, target=[x, y, z], pos=[px, y + dy, pz])
    if len(views) >= 3:  # the whole map, from the south, steep: far enough that its width (plus 10 %) fills a 16:10
        # screen across the viewer's 28 deg vertical field of view (web/src/main.ts), 43.4 deg horizontally
        dist = max(3100.0, 0.55 * W_ * VOXEL_SIZE / math.tan(math.radians(21.7))) / VOXEL_SIZE
        up, back = dist * 2600 / 3106, dist * 1700 / 3106  # the slope of the old fixed pose (2600 up, 1700 back)
        views["overview"] = dict(label="Whole map", target=[W_ / 2, float(np.median(g)) + 10, H_ * 0.45],
                                 pos=[W_ / 2, float(np.median(g)) + up, H_ * 0.45 + back])
    return views


def mats_of(pal, v):
    return pal.entries[int(v)][3]


def paint_windows(vol, win, faces, centres, rows, w=2, h=2, depth=1, plane_tol=3):
    """Windows painted from a measured elevation instead of a shader rhythm. faces: (axis, plane, normal, u_centre)
    with axis 0 = the face is a row plane (normal along rows), 1 = a column plane; centres: window centres along the
    face in metres from u_centre; rows: (z, height) of each window row (absolute voxel z). For each window the wall
    surface is found within plane_tol of the plane (one depth for the whole window, from its middle cell); if anything
    stands further out (a lower block, a porch) the window is skipped. The surface voxels are cleared to `depth` and
    the glass set behind them. Returns the number of windows cut."""
    n = 0
    for axis, plane, nrm, uc in faces:
        get = (lambda zz, q, u: vol[zz, q, u]) if axis == 0 else (lambda zz, q, u: vol[zz, u, q])
        def put(zz, q, u, v):
            if axis == 0: vol[zz, q, u] = v
            else: vol[zz, u, q] = v
        for c in centres:
            u0 = int(math.floor(uc + c - w / 2 + 0.5))
            for z0, hh in rows:
                um, zm = u0 + w // 2, z0 + hh // 2
                surf = None
                for t in range(plane_tol + 4, -plane_tol - 1, -1):  # from outside in
                    if get(zm, plane + t * nrm, um):
                        surf = t if t <= plane_tol else None
                        break
                if surf is None:
                    continue
                pl = plane + surf * nrm
                for u in range(u0, u0 + w):
                    for zz in range(z0, z0 + hh):
                        if not get(zz, pl, u) or get(zz, pl + nrm, u):
                            continue  # not flush with the window's surface here
                        for d in range(depth):
                            put(zz, pl - d * nrm, u, 0)
                        if win is not None:
                            put(zz, pl - depth * nrm, u, win)
                n += 1
    return n


def _faces(r0, r1, c0, c1):
    """The four faces of an axis-aligned block (inclusive grid bounds): N, S (row planes), W, E (column planes)."""
    return [(0, r0, -1, (c0 + c1 + 1) / 2), (0, r1, 1, (c0 + c1 + 1) / 2),
            (1, c0, -1, (r0 + r1 + 1) / 2), (1, c1, 1, (r0 + r1 + 1) / 2)]


def _feat(feats, name):
    return next((f for f in feats if f["tags"].get("name") == name), None)


def _cells_geom(geom, D, W):
    """Grid cells whose centre lies inside the polygon -> (rows, cols)."""
    import shapely
    minx, miny, maxx, maxy = geom.bounds
    c0, r0 = max(int(minx), 0), max(int(miny), 0)
    c1, r1 = min(int(maxx) + 1, W), min(int(maxy) + 1, D)
    cc, rr = np.meshgrid(np.arange(c0, c1), np.arange(r0, r1))
    m = shapely.contains_xy(geom, cc + 0.5, rr + 0.5)
    return rr[m], cc[m]


def _top_rel(vol, g, rr, cc):
    occ = vol[:, rr, cc] != 0
    H = occ.shape[0]
    return np.where(occ.any(0), H - 1 - np.argmax(occ[::-1], axis=0), 0) - g[rr, cc]


def edge_windows(vol, g, geom, win, rows, bay, w=2, margin=2.5, min_len=6, depth=1, skip=()):
    """Windows on every straight outer edge of a footprint, at any angle: as many bays (`bay` m apart) as fit
    between `margin` m from the ends, centred; rows (z above ground, height) the same on every edge. Each window
    cell walks in from outside to the first wall voxel at its height; that voxel (and depth-1 behind) is cleared and
    the next one set to glass. Edges listed by index in `skip` are left alone."""
    n = 0
    geom = geom.simplify(1.2)  # OSM outlines carry every pilaster step: one straight run per facade
    xs, ys = geom.exterior.coords.xy
    pts = list(zip(xs, ys))
    for k in range(len(pts) - 1):
        if k in skip:
            continue
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < min_len:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = -uy, ux
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if not geom.contains(Point(mx + nx * 2, my + ny * 2)):
            nx, ny = -nx, -ny  # n points into the building
        nb = int((L - 2 * margin) // bay) + 1
        if nb < 1:
            continue
        span = (nb - 1) * bay
        for i in range(nb):
            tc = L / 2 - span / 2 + i * bay
            for t in np.arange(tc - w / 2 + 0.25, tc + w / 2, 0.5):
                bx, by = x0 + ux * t, y0 + uy * t
                # (a wall cut by the map's edge: no window within 4 cells of it, where the probe would leave the grid)
                if not all(4 <= v < lim - 4 for v, lim in ((by, vol.shape[1]), (bx, vol.shape[2]))):
                    continue
                r_, c_ = int(by + ny), int(bx + nx)
                gz = int(g[r_, c_])
                for zr, hh in rows:
                    for zz in range(hh):
                        z = gz + zr + zz
                        hit = None
                        for o in np.arange(-3, 4, 0.5):
                            r, c = int(by + ny * o), int(bx + nx * o)
                            if vol[z, r, c]:
                                hit = o; break
                        if hit is None:
                            continue
                        for d in range(depth):
                            vol[z, int(by + ny * (hit + d)), int(bx + nx * (hit + d))] = 0
                        vol[z, int(by + ny * (hit + depth)), int(bx + nx * (hit + depth))] = win
            n += 1
    return n


def classic_rebuild(vol, g, pal, geom, eave, slope, wall_hex, roof_hex, note, name, glass_hex=None, glass_above=None,
                    rows=(), bay=4.5, gables=(), cap=None, attic=0, pure_hip=False, keep_above=None):
    """A masonry building rebuilt from its footprint: plain walls to the eave, a hipped roof rising `slope` m per m
    from every edge (never above the smoothed LiDAR top, so towers, ridges and courts keep their height; `cap`
    limits it), a 1 m cornice course at the eave, roof cells above `glass_above` m in glass (skylights), windows on
    every edge (edge_windows). `gables`: boxes (r0, r1, c0, c1) where the LiDAR's own roof stays (a pediment), its
    outer face in wall stone."""
    D, W = g.shape
    rr, cc = _cells_geom(geom, D, W)
    T = _top_rel(vol, g, rr, cc)
    r0, c0 = rr.min() - 2, cc.min() - 2
    Mk = np.zeros((rr.max() - r0 + 3, cc.max() - c0 + 3), bool)
    Mk[rr - r0, cc - c0] = True
    Tm = np.zeros(Mk.shape, float); Tm[rr - r0, cc - c0] = T
    Ts = ndimage.median_filter(Tm, 5)[rr - r0, cc - c0]
    d = ndimage.distance_transform_edt(Mk)[rr - r0, cc - c0]
    Hh = eave + slope * (d - 0.5) if pure_hip else np.minimum(eave + slope * (d - 0.5), np.maximum(Ts, eave))
    if cap is not None:
        Hh = np.minimum(Hh, cap)
    gab = np.zeros(len(rr), bool)
    for a0, a1, b0, b1, axis, apex in gables:  # a gable roof over the box, ridge along `axis`, rising to apex m
        m = (rr >= a0) & (rr <= a1) & (cc >= b0) & (cc <= b1)
        half = ((a1 - a0) if axis == "c" else (b1 - b0)) / 2 + 0.5
        off = np.abs(rr + 0.5 - (a0 + a1 + 1) / 2) if axis == "c" else np.abs(cc + 0.5 - (b0 + b1 + 1) / 2)
        Hh = np.where(m, np.maximum(Hh, eave + (apex - eave) * (1 - off / half)), Hh)
        gab |= m
    Hh = np.where(Ts < eave - 3, Ts, Hh)  # courtyards, low annexes
    if keep_above is not None:
        Hh = np.where(Ts >= keep_above, Ts, Hh)  # an atrium's glass roof standing over a flat roof
    wall = pal(_hex(wall_hex), MAT_IDS["classic"])
    roof = pal(_hex(roof_hex), 12)
    glass = pal(_hex(glass_hex), M_GLASS) if glass_hex else roof
    edge = d < 1.5
    for k in range(len(rr)):
        r, c, gz = rr[k], cc[k], int(g[rr[k], cc[k]])
        h = int(round(Hh[k]))
        col = vol[:, r, c]
        col[gz + 1:gz + 70] = 0
        if h <= 0:
            continue
        e = min(h, eave)
        col[gz:gz + e] = wall
        if h > e:
            col[gz + e:gz + h] = wall if (gab[k] and edge[k]) else roof
        col[gz + h - 1] = glass if (glass_above and h >= glass_above and not gab[k]) else \
            (wall if gab[k] and edge[k] else (roof if h > eave else roof))
        if attic and edge[k] and h >= eave:
            col[gz + eave:gz + eave + attic] = wall
    # cornice: one course 1 m proud at the eave
    ring = ndimage.binary_dilation(Mk) & ~Mk
    for r, c in zip(*np.nonzero(ring)):
        r, c = r + r0, c + c0
        z = int(g[r, c]) + eave - 1
        if vol[z, r, c] == 0:
            vol[z, r, c] = wall
    n = 0
    if rows:
        n = edge_windows(vol, g, geom, pal((58, 70, 68), MAT_IDS["window"]), rows, bay)
    note(f"{name} rebuilt: {len(rr)} columns, {n} windows")


def _by_id(feats, oid):
    return next((f for f in feats if f["id"] == oid), None)


def _onion(vol, g, cy, cx, z0, drum, R, bulb, col_drum, col_dome, gold, win=None):
    """a drum of radius R (window slits if win) from z0 to z0+drum, an onion over it swelling to 1.2 R and drawn in
    to a point over `bulb` m, a gold cross on top"""
    zb = z0 + drum
    for r in range(int(cy - 1.3 * R) - 1, int(cy + 1.3 * R) + 2):
        for c in range(int(cx - 1.3 * R) - 1, int(cx + 1.3 * R) + 2):
            d = math.hypot(r + 0.5 - cy, c + 0.5 - cx)
            gz = int(g[r, c]); col = vol[:, r, c]
            if d <= R:
                col[gz + z0:gz + zb] = col_drum
                if win is not None and d > R - 1 and int(math.degrees(math.atan2(r + 0.5 - cy, c + 0.5 - cx)) // 30) % 2:
                    col[gz + z0 + 1:gz + zb - 1] = win
            for k in range(bulb):
                t = (k + 0.5) / bulb
                rad = 1.2 * R * math.sin(math.pi * (0.25 + 0.75 * t)) ** 0.8
                if d <= rad:
                    col[gz + zb + k] = col_dome
            if d < 0.75:
                col[gz + zb + bulb:gz + zb + bulb + 2] = gold


_ORTO = None


def _orto():
    global _ORTO
    if _ORTO is None:
        _ORTO = np.load(AREA / "prep.npz", mmap_mode="r")["orto"]  # the ortho, 5 px per grid metre
    return _ORTO


def ortho_roof(vol, g, geom, pal, note, name, glass_hex="#9fbccd", min_rel=4, allow_glass=True, roof_only=False, inset=0):
    """The roof as the 2025 ortho shows it, cell by cell, on the top voxel of every column of the footprint above
    `min_rel` m: blue glass -> glass, green planting -> grass, anything else -> roof in the ortho's own colour
    (quantised). For roofs that are a patchwork (glass atria, roof gardens) the LiDAR can't tell apart."""
    D, W = g.shape
    rr, cc = _cells_geom(geom.buffer(-inset) if inset else geom, D, W)
    O = _orto()
    glass = pal(_hex(glass_hex), M_GLASS)
    n = [0, 0, 0]
    for r, c in zip(rr, cc):
        col = vol[:, r, c]
        nz = np.nonzero(col)[0]
        if not len(nz) or nz[-1] - g[r, c] < min_rel:
            continue
        z = nz[-1]
        if roof_only and pal.entries[int(col[z])][3] not in (12, M_GLASS, 8):
            continue  # a wall top (a cornice, a pediment): the ortho there is the facade's edge and the street
        px = np.asarray(O[r * 5:r * 5 + 5, c * 5:c * 5 + 5]).reshape(-1, 3).astype(float).mean(0)
        R_, G_, B_ = px
        if allow_glass and B_ > R_ + 12 and B_ >= G_ - 4:
            col[z] = glass; n[0] += 1
        elif G_ > R_ + 8 and G_ > B_ + 8:
            col[z] = pal(tuple(int(v * 0.95) for v in px), 8); n[1] += 1
        else:
            col[z] = pal(tuple(int(v) for v in px), 12, q=12); n[2] += 1
    note(f"{name} roof from the ortho: {n[0]} glass, {n[1]} planted, {n[2]} roof")


def recolour_walls(vol, g, geom, pal, hex_, mat, note, name):
    """Every voxel of the footprint's columns below the top one, in one colour and material (facade cladding)."""
    D, W = g.shape
    rr, cc = _cells_geom(geom.buffer(1.0), D, W)
    v = pal(_hex(hex_), mat)
    win_mat = MAT_IDS["window"]
    n = 0
    for r, c in zip(rr, cc):
        col = vol[:, r, c]
        nz = np.nonzero(col)[0]
        nz = nz[nz >= g[r, c]]  # from the first voxel over the ground (g is the first free level)
        for z in nz[:-1]:
            if pal.entries[int(col[z])][3] not in (win_mat, 8, 3):
                col[z] = v; n += 1
    note(f"{name} walls recoloured: {n}")


# ---------------------------------------------------------------- the Vistula bridges' structure under the decks
DECK = None  # (D, W) top of the bridge decks (first free voxel over the road surface), set by voxelize.py / patch.py


def _deck_frame(p0, p1, halfw, pad=10):
    """Deck cells near the axis p0 -> p1 (grid x = col, y = row): rows, cols, station s along the axis, lateral l
    (to the left of the direction of travel), deck top z; and per metre of station the deck's edges (lmin, lmax)."""
    o = np.asarray(p0, float)
    t = np.subtract(p1, p0, dtype=float)
    L = float(np.hypot(*t))
    t /= L
    n = np.array([-t[1], t[0]])
    r0, r1 = int(min(p0[1], p1[1]) - halfw - pad), int(max(p0[1], p1[1]) + halfw + pad)
    c0, c1 = int(min(p0[0], p1[0]) - halfw - pad), int(max(p0[0], p1[0]) + halfw + pad)
    rr, cc = np.nonzero(DECK[r0:r1, c0:c1] > 0)
    rr, cc = rr + r0, cc + c0
    s = (cc + 0.5 - o[0]) * t[0] + (rr + 0.5 - o[1]) * t[1]
    l = (cc + 0.5 - o[0]) * n[0] + (rr + 0.5 - o[1]) * n[1]
    k = (s >= -pad) & (s <= L + pad) & (np.abs(l) <= halfw)
    rr, cc, s, l = rr[k], cc[k], s[k], l[k]
    si = np.floor(s).astype(int) + pad
    nb = int(L) + 2 * pad + 2
    lmin, lmax = np.full(nb, np.inf), np.full(nb, -np.inf)
    np.minimum.at(lmin, si, l)
    np.maximum.at(lmax, si, l)
    zt = np.zeros(nb)
    cnt = np.zeros(nb)
    np.add.at(zt, si, DECK[rr, cc])
    np.add.at(cnt, si, 1)
    zt = np.where(cnt > 0, zt / np.maximum(cnt, 1), np.nan)
    ok = np.isfinite(lmin)
    for a in (lmin, lmax, zt):  # gaps (a pylon, a missing cell) from the neighbours
        a[~ok] = np.interp(np.nonzero(~ok)[0], np.nonzero(ok)[0], a[ok]) if ok.any() else 0
    edges = lambda v: (np.interp(v + pad, np.arange(nb) + 0.5, lmin), np.interp(v + pad, np.arange(nb) + 0.5, lmax),
                       np.interp(v + pad, np.arange(nb) + 0.5, zt))
    to_cell = lambda sv, lv: (o[1] + t[1] * sv + n[1] * lv, o[0] + t[0] * sv + n[0] * lv)  # -> (row, col)
    return dict(rr=rr, cc=cc, s=s, l=l, z=DECK[rr, cc].astype(int), edges=edges, cell=to_cell, t=t, n=n, o=o, L=L)


def _station(F, col):
    """station on the axis where it crosses grid column `col`"""
    return (col - F["o"][0]) / F["t"][0]


def _pier(vol, g, F, s0, along, lat0, lat1, ztop, mat, round_ends=0.0, step=0.5):
    """a pier: `along` m thick at station s0, from lateral lat0 to lat1, from the ground (riverbed) up to ztop;
    round_ends > 0 rounds the two ends (in plan) with that radius"""
    H = vol.shape[0]
    for a in np.arange(-along / 2, along / 2 + 0.01, step):
        for b in np.arange(lat0, lat1 + 0.01, step):
            if round_ends:
                e = max(lat0 + round_ends - b, b - (lat1 - round_ends), 0)
                if e > 0 and np.hypot(e, a * (round_ends / (along / 2))) > round_ends:
                    continue
            r, c = F["cell"](s0 + a, b)
            r, c = int(r), int(c)
            if not (0 <= r < g.shape[0] and 0 <= c < g.shape[1]):
                continue
            z0 = int(g[r, c]) - 1
            if ztop > z0:
                vol[z0:min(ztop, H), r, c] = mat


PIERS = []  # OSM bridge:support polygons (grid coords), set by voxelize.py / patch.py


def osm_piers(vol, g, pal, note):
    """Every OSM bridge:support polygon under a deck stands as a concrete pier from the riverbed up to the deck's
    underside: the head (the polygon, as the ortho sees it) 3 m deep, the shaft under it inset by 30 % of the half-width
    (the footbridge's piers flare like this in the photos) -- unless a curated pier already stands there (more than half
    its cells solid at mid-height). Markers inside a bigger polygon skip."""
    from shapely.geometry import Point as _P
    conc = pal(_hex("#d6d4ce"), MAT_IDS["concrete"])
    big = [p for p in PIERS if p.area >= 4]
    n = n_skip = 0
    for p in PIERS:
        if p.area < 4 and any(q.contains(p.centroid) for q in big if q is not p):
            continue
        c0, r0, c1, r1 = (int(v) for v in p.bounds)
        c0, r0, c1, r1 = max(c0 - 1, 0), max(r0 - 1, 0), min(c1 + 2, g.shape[1]), min(r1 + 2, g.shape[0])
        if c1 <= c0 or r1 <= r0:
            continue
        cells = [(r, c) for r in range(r0, r1) for c in range(c0, c1) if p.buffer(0.35).contains(_P(c + 0.5, r + 0.5))]
        if not cells:
            continue
        dk = DECK[r0:r1, c0:c1]
        if not (dk > 0).any():
            continue
        top = int(np.median(dk[dk > 0])) - 3  # the underside: the 2-voxel deck and a girder voxel stay
        mid = [(int(g[r, c]) + top) // 2 for r, c in cells]
        if np.mean([vol[m, r, c] != 0 for (r, c), m in zip(cells, mid)]) > 0.5:
            n_skip += 1
            continue
        m = np.zeros((r1 - r0, c1 - c0), bool)
        for r, c in cells:
            m[r - r0, c - c0] = True
        inner = ndimage.distance_transform_edt(np.pad(m, 1))[1:-1, 1:-1]
        w = inner.max()
        for r, c in cells:
            z0 = int(g[r, c]) - 1
            d = inner[r - r0, c - c0]
            shaft = d > 0.3 * w - 0.01
            for z in range(z0, top):
                if (shaft or z >= top - 3) and vol[z, r, c] == 0:
                    vol[z, r, c] = conc
        n += 1
    note(f"OSM piers: {n} drawn, {n_skip} already there")


def _line6(vol, a, b, val):
    """a face-connected voxel line from a to b ((z, row, col) floats): one axis per step, so it holds together for
    walking and the support check; only empty voxels are drawn"""
    n = int(max(abs(b[i] - a[i]) for i in range(3))) + 1
    prev = None
    k = 0
    for j in range(n + 1):
        f = j / n
        cur = [int(a[i] + (b[i] - a[i]) * f) for i in range(3)]
        steps = [cur]
        if prev is not None:
            p = list(prev)
            steps = []
            for ax in (0, 1, 2):
                if p[ax] != cur[ax]:
                    p[ax] = cur[ax]
                    steps.append(tuple(p))
        for z, r, c in steps:
            if 0 <= z < vol.shape[0] and 0 <= r < vol.shape[1] and 0 <= c < vol.shape[2] and vol[z, r, c] == 0:
                vol[z, r, c] = val
                k += 1
        prev = cur
    return k
