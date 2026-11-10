"""Monuments as voxel art: statues, columns and gates the LiDAR surface does not resolve, built from boxes.

MONUMENTS maps a name to dict(at=(lon, lat), phi=facing in degrees, parts=[B(...), ...], clear=metres to clear first);
build() places them on the ground. The Warsaw snapshot's monuments are gone; Madrid's come with the landmarks
(Phase 4). Builders: B (a box, optionally turned, leaning or tapering), standing (a figure), rider (an equestrian
statue), crosses, plane; attach() joins thin pieces turned off the grid.
"""
import math

import numpy as np

from osm import to_grid

STONE, METAL = 0, 6
BRONZE, PATINA = ("#6a5c48", METAL), ("#678072", METAL)
GRANITE, DARK, BLACK = ("#9c9890", STONE), ("#6a6661", STONE), ("#34353a", STONE)
LIGHT, SAND, MARBLE = ("#cfcac0", STONE), ("#d6c39c", STONE), ("#eeece6", STONE)
CONCRETE, BASALT, STEEL = ("#bdbab2", STONE), ("#807a71", STONE), ("#b3b1aa", STONE)
RELIEF, SAPPER, SILVER = ("#55635b", METAL), ("#4f5a53", METAL), ("#c4c6c4", METAL)
DARK_BRONZE, DARK_GRANITE, RED_GRANITE = ("#4a453e", METAL), ("#4b4b4e", STONE), ("#8f6f66", STONE)
PALE_GRANITE, FROND = ("#c9c6bf", STONE), ("#4f7a3a", STONE)
PINK_GRANITE, GREY_BRONZE, WORN_BRONZE = ("#b4a598", STONE), ("#59605a", METAL), ("#4f5a50", METAL)
MID_GRANITE, COPPER, MERMAID = ("#8f8d88", STONE), ("#7a5236", METAL), ("#4d6b5e", METAL)


def B(a, b, w, d, z0, z1, col, rot=0.0, lean=(0.0, 0.0), top=1.0):
    return dict(a=a, b=b, w=w, d=d, z0=z0, z1=z1, col=col, rot=rot, lean=lean, top=top)


def standing(a, b, z, h, col, arm=None):
    """a figure h m tall: two voxels across to the shoulders, the head one; arm 'up' raises a sabre or a hand on
    its right"""
    out = [B(a, b, 2, 1, z, z + h - 1, col), B(a - 0.5, b, 1, 1, z + h - 1, z + h, col)]
    if arm == "up":
        out += [B(a + 1.5, b, 1, 1, z + h - 2, z + h + 1, col)]
    return out


def rider(a, b, z, col, rot=0.0, arm=False):
    """a horse with its rider, 5 m, facing +b: front and hind legs, a 4 m body, the neck and head raised, the tail,
    the rider over the saddle, arm out ahead with a sabre if arm"""
    r = math.radians(rot)
    at = lambda k: (a + k * math.sin(r), b + k * math.cos(r))
    out = [B(*at(-1.5), 1, 1, z, z + 2, col, rot), B(*at(1.5), 1, 1, z, z + 2, col, rot),
           B(*at(0), 1, 4, z + 2, z + 3, col, rot), B(*at(2.5), 1, 1, z + 3, z + 5, col, rot),
           B(*at(-2.5), 1, 1, z + 1, z + 3, col, rot), B(*at(-0.5), 1, 1, z + 3, z + 5, col, rot)]
    if arm:
        out.append(B(*at(0.5), 1, 1, z + 4, z + 5, col, rot))
    return out


def crosses(w, d, z):
    """a thicket of crosses over w x d cells from z: each cell a post of its own height (4 to 7 m), some with the
    crossbar out to a side"""
    out = []
    for i in range(w):
        for k in range(d):
            hh = (i * 7 + k * 13 + i * k * 5) % 5
            if hh == 4:
                continue
            a, b, top = i - (w - 1) / 2, k - (d - 1) / 2, z + 3 + hh
            out.append(B(a, b, 1, 1, z, top, DARK_BRONZE))
            if (i + k * 3) % 3 == 0:
                out.append(B(a + (-1 if i < w / 2 else 1), b, 1, 1, top - 2, top - 1, DARK_BRONZE))
    return out


def plane(L, S, col):
    """an aircraft on display, nose along +b: the fuselage 2 m round on its gear, swept wings of span S a little behind
    the middle, the tailplane and the fin at the back"""
    c = (col, METAL)
    out = [B(0, L * 0.3, 1.6, 1.6, 0, 1, c), B(-1.5, -L * 0.05, 1.6, 1.6, 0, 1, c), B(1.5, -L * 0.05, 1.6, 1.6, 0, 1, c),
           B(0, 0, 2, L, 1, 3, c), B(0, L / 2 + 0.5, 1.6, 1.6, 1.5, 2.5, c),
           B(0, -L * 0.05, S, max(2, L * 0.15), 1, 2, c),
           B(0, -L * 0.42, S * 0.4, 2, 2, 3, c), B(0, -L * 0.42, 1.2, 2.5, 3, 5, c)]
    return out


MONUMENTS = {}


def attach(vol, g, rc, zmax):
    """a thin piece turned off the grid (a sword, an arm, a crossbar) can come to touch the rest only by an edge once
    its cells are whole: each piece of the monument's box not held by the ground gets a straight run of its own
    voxels, axis by axis, to the nearest voxel that is"""
    from scipy import ndimage
    r0, c0 = rc.min(0) - 1
    r1, c1 = rc.max(0) + 2
    zlo = int(g[r0:r1, c0:c1].min()) - 1
    box = vol[zlo:zmax + 3, r0:r1, c0:c1]
    for _ in range(8):
        lab, n = ndimage.label(box != 0)
        held = set(np.unique(lab[0]).tolist()) - {0}
        loose = [i for i in range(1, n + 1) if i not in held]
        if not loose:
            return
        for i in loose:
            pts = np.argwhere(lab == i)
            fix = np.argwhere((lab != 0) & (lab != i))
            d = ((pts[:, None, :] - fix[None, :, :]) ** 2).sum(-1)
            a, b = np.unravel_index(np.argmin(d), d.shape)
            p, q = pts[a].copy(), fix[b]
            v = box[tuple(p)]
            for ax in (1, 2, 0):  # across first, then down, so a sword joins the arm that holds it
                while p[ax] != q[ax]:
                    p[ax] += 1 if q[ax] > p[ax] else -1
                    if box[tuple(p)] == 0:
                        box[tuple(p)] = v


def build(vol, g, pal, note, keep=()):
    """every monument into the volume; returns each cell's new top (absolute z, 0 where none) for the labels"""
    D, W = g.shape
    mon_top = np.zeros((D, W), np.int16)
    keep = np.asarray(sorted(keep), dtype=vol.dtype)
    for name, m in MONUMENTS.items():
        c0, r0 = (int(v) + 0.5 for v in to_grid(*m["at"]))
        ph = math.radians(m["phi"])
        rt, fw = (math.cos(ph), math.sin(ph)), (math.sin(ph), -math.cos(ph))
        R = int(max(math.hypot(p["a"], p["b"]) + math.hypot(p["w"], p["d"]) + math.hypot(*p["lean"]) for p in m["parts"])) + 2
        rr, cc = np.mgrid[int(r0) - R:int(r0) + R + 1, int(c0) - R:int(c0) + R + 1]
        ok = (rr >= 0) & (rr < D) & (cc >= 0) & (cc < W)
        rr, cc = rr[ok], cc[ok]
        dc, dr = cc + 0.5 - c0, rr + 0.5 - r0
        A, Bf = dc * rt[0] + dr * rt[1], dc * fw[0] + dr * fw[1]
        cells = []
        for p in m["parts"]:
            t = math.radians(p["rot"])
            for z in range(int(p["z0"]), int(math.ceil(p["z1"]))):
                f = (z + 0.5 - p["z0"]) / max(p["z1"] - p["z0"], 1e-6)
                s = 1 + (p["top"] - 1) * f
                pa, pb = A - p["a"] - p["lean"][0] * f, Bf - p["b"] - p["lean"][1] * f
                x, y = pa * math.cos(t) - pb * math.sin(t), pa * math.sin(t) + pb * math.cos(t)
                hw, hd = p["w"] * s / 2, p["d"] * s / 2  # half-open, so an even width is that many cells
                hit = (x >= -hw - 1e-6) & (x < hw - 1e-6) & (y >= -hd - 1e-6) & (y < hd - 1e-6)
                if hit.any():
                    cells.append((z, rr[hit], cc[hit], p))
        if not cells:
            continue
        foot = np.unique(np.concatenate([np.stack([r, c], 1) for z, r, c, p in cells if p["z0"] == 0]), axis=0)
        z0 = int(g[foot[:, 0], foot[:, 1]].max())
        allrc = np.unique(np.concatenate([np.stack([r, c], 1) for z, r, c, p in cells]), axis=0)
        if m.get("clear"):  # what stood there in the LiDAR, crowns and trunks too (the Palm read as a leafy tree)
            near = np.hypot(dc, dr) <= m["clear"]
            for r, c in zip(rr[near], cc[near]):
                vol[g[r, c]:, r, c] = 0
        zmax = z0 + max(int(math.ceil(p["z1"])) for p in m["parts"])
        for r, c in allrc:  # what the LiDAR or an OSM outline left on the spot (not the trees around it)
            col = vol[g[r, c]:zmax + 2, r, c]
            col[~np.isin(col, keep)] = 0
        for z, r, c, p in cells:
            v = pal(p["col"][0], p["col"][1])
            if p["z0"] == 0 and z == 0:
                for ri, ci in zip(r, c):
                    vol[g[ri, ci]:z0 + 1, ri, ci] = v
            else:
                vol[z0 + z, r, c] = v
            mon_top[r, c] = np.maximum(mon_top[r, c], z0 + z + 1)
        attach(vol, g, allrc, zmax)
        note(f"monument {name} at ({int(r0)}, {int(c0)}), {zmax - z0} m")
    return mon_top
