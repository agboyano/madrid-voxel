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
from aoi import AREA, D as _D, W as _W, to_grid

M_WALL, M_GLASS, M_CONCRETE, M_CLOCK = 1, 2, 13, 14

# OSM name -> facts for the curated labels (en, kind, height, year, by, alt, anchor="top"); filled in Phase 4
LABELS = {}
# labels without a single OSM polygon: name -> facts with at=(x, y) in EPSG:25830
EXTRA_LABELS = {}
# roofs to smooth (a membrane or a lattice the LiDAR reads as noise): OSM id -> description
SMOOTH_ROOFS = {}
# Madrid's historic core, for its own wall palette (palette.AUSTRIAS_WALLS) and tiled roofs: Madrid de los Austrias,
# between Calle de Bailen, Calle Mayor, the east side of Plaza Mayor, Calle de Toledo, Plaza de la Cebada and Calle de
# Segovia; traced roughly, EPSG:25830 (x, y)
HISTORIC_CORE = [(439458, 4474153), (439764, 4474195), (440061, 4474204), (440187, 4474036), (440083, 4473815), (439972, 4473705), (439717, 4473651), (439422, 4473820)]


def historic_core():
    if not HISTORIC_CORE:
        return Polygon()
    return Polygon([tuple(float(v) for v in to_grid(x, y)) for x, y in HISTORIC_CORE])


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


def small_tree(vol, g, r, c, h, leaves, trunk, height=None):
    """A young street tree as planted 2025-26 (Plac Centralny, Złota): photos show a clear trunk to ~4 m and a
    narrow, airy crown on top (visual_ref.md, Złota 2026 photos)."""
    H = int(height or 7 + h % 3)
    z0 = int(g[r, c])
    tr = max(3, int(H * 0.42))
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


def wall_override(f, pal):
    o = override_for(f)
    return _style(pal, o["wall"]) if o and "wall" in o else None


def roof_override(f, pal):
    o = override_for(f)
    return _style(pal, o["roof"]) if o and "roof" in o else None


def details_geometry(vol, g, feats, pal, note):
    """Every curated change to the landmarks' voxels (also run alone by patch.py on the cached volume). None yet."""
    return


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
    """Camera presets in three.js coords (x = col, y = up, z = row): the map's centre (Puerta del Sol) from above,
    obliquely and from Calle Mayor at street level. At street level the target sits just below the eye: OrbitControls'
    tilt limit lifts a camera that looks up."""
    H_, W_ = g.shape
    cx, cz = W_ / 2, H_ / 2
    gz = lambda x, z: float(g[int(z), int(x)])  # noqa: E731
    mx, mz = (float(v) for v in to_grid(440224.1, 4474235.9))  # Calle Mayor centreline (OSM), 125 m west of Sol
    views = {
        "overview": dict(label="Overview", target=[cx, gz(cx, cz), cz], pos=[cx + 330, 380, cz + 420]),
        "top": dict(label="Top-down", target=[cx, gz(cx, cz), cz], pos=[cx, 900, cz + 1]),
        "sol": dict(label="Puerta del Sol", target=[cx, gz(cx, cz) + 8, cz], pos=[cx + 150, gz(cx, cz) + 110, cz + 170]),
    }
    if 0 <= mx < W_ and 0 <= mz < H_:
        views["street"] = dict(label="Calle Mayor", target=[cx, gz(mx, mz) + 1.5, cz], pos=[mx, gz(mx, mz) + 2.5, mz])
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
        nz = nz[nz > g[r, c]]
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
