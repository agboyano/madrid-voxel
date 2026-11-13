"""Tree trunks for the viewer (web/src/trunks.ts): one record per trunk in web/public/data/trunks.bin.

A trunk drawn in 1 m voxels is a metre thick, six times the median street tree's (53 cm round at 1.3 m in the city's
inventory, 17 cm across). The build still draws every trunk as voxels -- the 8 m clay downsamples them, and
debris.support_floating reads them -- but the 1 m tiles leave them out (tiles.py `drop_ids`) and the viewer draws
each one as a thin box of its real width, with a few branches into its crown (bare in winter).

The records come from the finished volume: every column holding trunk voxels is one trunk (a 2 x 2 block for the
thick ones), so the trunks of the young procedural trees and those debris.support_floating put under floating crowns
are in too. Each is matched to the tree drawn there (`info`, keyed by its trunk cell) for its inventory girth,
species and crown.

trunks.bin, gzip of a little-endian array of REC (16 bytes per trunk):
  x, y    float32  trunk centre, grid cells (column, row)
  z       uint16   ground voxel under it
  hb      uint8    clear trunk: cells from the ground to the first branches (the crown's underside over the trunk)
  ht      uint8    top of the trunk's voxel column above the ground, cells (> hb: a leader up through the crown)
  top     uint8    crown top above the ground, cells
  r       uint8    crown radius, decimetres
  d       uint8    trunk diameter at 1.3 m, cm (inventory girth / pi; estimated from the crown top where unknown)
  flags   uint8    1 evergreen (no bare branches to show), 2 diameter estimated, 4 young tree (procedural)
"""
import gzip

import numpy as np

import phenology

REC = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<u2"), ("hb", "u1"), ("ht", "u1"), ("top", "u1"), ("r", "u1"),
                ("d", "u1"), ("flags", "u1")])
EVERGREEN, ESTIMATED, YOUNG = 1, 2, 4
GIRTH_CM = (3.0, 650.0)  # girths outside this are typos (the city file has 7 500 cm and 0.01 cm)
SUPPORT_RADIUS = 1.5  # m: the crown of a trunk debris.support_floating added (a fragment of a crown, no tree known)


def evergreen(species, leaf_type=None):
    if species:
        return phenology.classify({"sp": species}) == phenology.EVERGREEN
    return leaf_type == "needleleaved"


def columns(vol, trunk_id, band=128):
    """(rows, cols, z0, z1): every column holding trunk voxels, the lowest run of them [z0, z1)."""
    H, D, _ = vol.shape
    out = []
    zz = np.arange(H)[:, None]
    for r0 in range(0, D, band):
        m = vol[:, r0:r0 + band, :] == trunk_id
        rr, cc = np.nonzero(m.any(0))
        if not len(rr):
            continue
        col = m[:, rr, cc]
        z0 = col.argmax(0)
        z1 = np.where(~col & (zz > z0), zz, H).min(0)
        out.append((rr + r0, cc, z0, z1))
    return tuple(np.concatenate(a) for a in zip(*out)) if out else (np.zeros(0, int),) * 4


def girth_fit(tops, girths, note):
    """Median inventory girth (cm) per metre of crown top, made non-decreasing: the girth of a tree whose inventory
    has none (a crown the LiDAR found with no tree known, an OSM tree without a circumference tag)."""
    tops, girths = np.asarray(tops, float), np.asarray(girths, float)
    hmax = int(tops.max()) + 1 if len(tops) else 2
    med = np.full(hmax + 1, np.nan)
    for h in range(hmax + 1):
        sel = np.round(tops) == h
        if sel.sum() >= 20:
            med[h] = np.median(girths[sel])
    ok = ~np.isnan(med)
    if not ok.any():
        return lambda h: np.full(np.shape(h), 50.0)
    med = np.interp(np.arange(hmax + 1), np.nonzero(ok)[0], med[ok])
    med = np.maximum.accumulate(med)
    note("trunk girth by crown top (median cm, from", len(tops), "inventory trees):",
         {h: int(med[h]) for h in range(4, hmax + 1, 4)})
    return lambda h: med[np.clip(np.round(h).astype(int), 0, hmax)]


def build(vol, g, trunk_id, info, note, out):
    """info: (row, col) of a trunk cell -> dict(x, y, thick, girth, species, leaf_type, hb, top, radius, young);
    radius in metres, heights in cells, girth in cm or None. Writes out/trunks.bin; returns the record count."""
    rr, cc, _, z1 = columns(vol, trunk_id)
    at = {(int(r), int(c)): k for k, (r, c) in enumerate(zip(rr, cc))}
    used = np.zeros(len(rr), bool)
    fit_h = [t["top"] for t in info.values() if t.get("girth") and not t.get("young")]
    fit_g = [np.clip(t["girth"], *GIRTH_CM) for t in info.values() if t.get("girth") and not t.get("young")]
    girth_of = girth_fit(fit_h, fit_g, note)
    recs, n_missing = [], 0
    for (r, c), t in info.items():
        k = at.get((r, c))
        if k is None or used[k]:
            n_missing += 1  # under a building edge, or cleared by a landmark
            continue
        cells = [(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)] if t.get("thick") else [(r, c)]
        for cell in cells:
            if cell in at:
                used[at[cell]] = True
        if t.get("thick"):
            x, y = c + 1.0, r + 1.0
        elif int(t["x"]) == c and int(t["y"]) == r:
            x, y = t["x"], t["y"]  # the inventory's own point, inside its trunk cell
        else:
            x, y = c + 0.5, r + 0.5  # moved off a carriageway or onto its crown: the cell it stands in
        ht = int(z1[k] - g[r, c])
        girth = t.get("girth")
        flags = (EVERGREEN if evergreen(t.get("species"), t.get("leaf_type")) else 0) | (YOUNG if t.get("young") else 0)
        if not girth:
            girth, flags = float(girth_of(t["top"])), flags | ESTIMATED
        recs.append((x, y, int(g[r, c]), min(t.get("hb") or ht, ht), ht, max(t["top"], ht), t["radius"], girth, flags))
    n_support = 0
    for k in np.nonzero(~used)[0]:  # a trunk debris.support_floating put under a crown fragment
        r, c = int(rr[k]), int(cc[k])
        ht = int(z1[k] - g[r, c])
        recs.append((c + 0.5, r + 0.5, int(g[r, c]), ht, ht, ht + 2, SUPPORT_RADIUS, float(girth_of(ht + 2)), ESTIMATED))
        n_support += 1
    a = np.zeros(len(recs), REC)
    for k, (x, y, z, hb, ht, top, rad, girth, flags) in enumerate(recs):
        a[k] = (x, y, z, np.clip(hb, 0, 255), np.clip(ht, 0, 255), np.clip(top, 0, 255), np.clip(round(rad * 10), 1, 255),
                np.clip(round(np.clip(girth, *GIRTH_CM) / np.pi), 1, 255), flags)
    (out / "trunks.bin").write_bytes(gzip.compress(a.tobytes(), 9, mtime=0))
    d = a["d"].astype(float)
    note("trunks for the viewer:", len(a), "| from trunk voxels with no tree record (support):", n_support,
         "| tree records with no trunk voxels left:", n_missing,
         "| diameter cm p10/median/p90/max:", *(int(v) for v in np.percentile(d, [10, 50, 90, 100])) if len(d) else "-",
         "| estimated:", int((a["flags"] & ESTIMATED > 0).sum()), "evergreen:", int((a["flags"] & EVERGREEN > 0).sum()))
    return len(a)
