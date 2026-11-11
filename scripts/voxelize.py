"""Fuse the LiDAR rasters (prep.py: DSM, DTM, classes) + orthophoto + OSM + Catastro + the tree inventory into a
1 m voxel volume.

The 2D fusion of ground, buildings and roofs lives in layers.py; this script fills the 3D volume from its layers
and adds what is drawn voxel by voxel (vegetation and trunks, fountains, street furniture, bridge decks, underpasses,
landmarks), then exports the tiles and the viewer's data.

Output (web/public/data/): tiles/ (tiles.py), meta.json (palette, lamps, labels, views), trees.json, traffic.json,
qa_roadmask.bin.gz; {AREA}/ground.npz for terrain.py.
Volume axes: vol[z, row, col]; row grows south, col grows east, z up.
"""

import colorsys
import gzip
import json
import math
import os
from pathlib import Path

import numpy as np
from scipy import ndimage
from shapely.geometry import LineString

from aoi import AREA, CRS, CX, CY, D, THETA, VOXEL_SIZE, W, grid_to_lonlat
import landmarks
import roofgardens

import layers
from buildlog import DBG, OUT, note, report
from layers import burn, cells_of, tunnelish
from palette import C, LEAVES, M_CAR, M_CLOCK, M_GLASS, M_GRASS, M_LAMP, M_LEAF, M_METAL, M_ROOF, M_SOIL, M_WATER, PERENNIALS, pal, parse_len, stable_hash

L = layers.build()
BASE = L["BASE"]
CORE = L["CORE"]
GARDEN_ROOFS = L["GARDEN_ROOFS"]
H = L["H"]
LIDAR_BRIDGE = L["LIDAR_BRIDGE"]
LIDAR_VEG = L["LIDAR_VEG"]
MAX_TREE = L["MAX_TREE"]
OPEN_CUT = L["OPEN_CUT"]
SACRED = L["SACRED"]
bmask = L["bmask"]
boti = L["boti"]
bridge_lines = L["bridge_lines"]
bridge_rails = L["bridge_rails"]
bridge_roads = L["bridge_roads"]
bridge_shapes = L["bridge_shapes"]
cell_maxh = L["cell_maxh"]
cellcol = L["cellcol"]
cls = L["cls"]
dsm = L["dsm"]
dsm_mean = L["dsm_mean"]
dtm = L["dtm"]
exg = L["exg"]
feats = L["feats"]
g = L["g"]
gcol = L["gcol"]
is_road = L["is_road"]
lm = L["lm"]  # lane markings, before the decks
lum = L["lum"]
nd_max = L["nd_max"]
nd_mean = L["nd_mean"]
osm = L["osm"]
over = L["over"]
parking_mask = L["parking_mask"]
rails = L["rails"]
render = L["render"]
rgbsum = L["rgbsum"]
splash_pads = L["splash_pads"]
top = L["top"]
topi = L["topi"]
z = L["z"]
carriageway_sanity = L["carriageway_sanity"]
vol = np.zeros((H, D, W), np.uint16)

# ground column
for zz in range(H):
    m = zz < g - 1
    if not m.any():
        break
    vol[zz][m] = C["soil"]
rr, cc = np.nonzero(np.ones((D, W), bool))
vol[g[rr, cc] - 1, rr, cc] = gcol[rr, cc]
# a paved cell 2 m or more above a neighbour stands on a retaining wall (an underpass, a trench, a ramp's side, a
# station's cut): its exposed face concrete, not the brown soil of a garden's bank
_nb_lo = ndimage.minimum_filter(g, footprint=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
_mat = np.array([e[3] for e in pal.entries] + [0] * 256)
_wall = (g - _nb_lo >= 2) & ~np.isin(_mat[gcol], [M_GRASS, M_LEAF, M_SOIL, M_WATER])
n_rw = 0
for zz in range(int(_nb_lo[_wall].min()) if _wall.any() else 0, int(g.max())):
    m = _wall & (zz >= _nb_lo) & (zz < g - 1)
    vol[zz][m] = C["concrete"]
    n_rw += int(m.sum())
note("retaining walls (paved ground 2 m+ over a neighbour): concrete voxels", n_rw)

# buildings: base fill with the tallest covering feature's wall, then parts paint their own [minh, maxh)
basewall = np.zeros((D, W), np.uint16)
roofcol_fix = np.zeros((D, W), np.uint16)
for f in sorted(render, key=lambda f: f["maxh"] or float(np.median(top[f["rr"], f["cc"]]))):
    basewall[f["rr"], f["cc"]] = f["wall"]
# an outline's cell outside all its parts, where the LiDAR stands as tall as a part within 4 m, is that part mapped a
# little small (the Telecom tower's beige concrete came out in the outline's brown glass): the part's wall
_parts = sorted([f for f in render if f["part"] and f["maxh"]], key=lambda f: f["maxh"])
_pid = np.zeros((D, W), np.int32)
for i_, f in enumerate(_parts, 1):
    _pid[f["rr"], f["cc"]] = i_
n_pw = 0
for f in render:
    if f["part"] or not f.get("has_parts"):
        continue
    if f["tags"].get("building:colour"):
        continue  # the outline has its own facade colour (a glass upper storey round a white part): it stays
    rr_, cc_ = f["rr"], f["cc"]
    r0_, c0_ = max(rr_.min() - 5, 0), max(cc_.min() - 5, 0)
    sub_ = _pid[r0_:rr_.max() + 6, c0_:cc_.max() + 6]
    if not (sub_ > 0).any():
        continue
    d_, (ir_, ic_) = ndimage.distance_transform_edt(sub_ == 0, return_indices=True)
    k_ = _pid[rr_, cc_] == 0
    for r_, c_ in zip(rr_[k_], cc_[k_]):
        i_, j_ = r_ - r0_, c_ - c0_
        if d_[i_, j_] > 4:
            continue
        p_ = _parts[sub_[ir_[i_, j_], ic_[i_, j_]] - 1]
        # a rim up to 2 m wide round a part (Focus: one outline cell per step of its rotated walls, striping its
        # glass in the outline's dark grey) as soon as it stands 70 % of the part's height; up to 4 m when as tall
        ok_ = (d_[i_, j_] <= 2 and topi[r_, c_] >= 0.7 * p_["maxh"]) or abs(p_["maxh"] - topi[r_, c_]) <= 6
        if ok_ and p_["wall"] != basewall[r_, c_]:
            basewall[r_, c_] = p_["wall"]
            n_pw += 1
note("outline cells given their adjacent part's wall:", n_pw)
# LiDAR tower taller than the OSM part covering the cell (footprints misregistered, e.g. Marriott):
# take the facade from the nearest OSM part that is tall enough to explain the height
tall_id = np.zeros((D, W), np.int32)
tall_feats = sorted([f for f in render if (f["maxh"] or 0) >= 30], key=lambda f: f["maxh"])
for i, f in enumerate(tall_feats, 1):
    tall_id[f["rr"], f["cc"]] = i
need = bmask & np.isfinite(cell_maxh) & (topi > np.nan_to_num(cell_maxh) + 10) & (topi >= 30)
if need.any() and tall_feats:
    dist, (ir, ic) = ndimage.distance_transform_edt(tall_id == 0, return_indices=True)
    rr_, cc_ = np.nonzero(need)
    fid = tall_id[ir[rr_, cc_], ic[rr_, cc_]]
    ok = (dist[rr_, cc_] < 15) & (fid > 0)
    n_fix = 0
    for r_, c_, k_ in zip(rr_[ok], cc_[ok], fid[ok]):
        f = tall_feats[k_ - 1]
        if f["maxh"] >= topi[r_, c_] - 12:
            basewall[r_, c_] = f["wall"]
            roofcol_fix[r_, c_] = f["roof"]
            n_fix += 1
    note("tower cells recoloured from nearest tall OSM part:", n_fix)
zb = g + boti
zt = g + topi
for zz in range(int(g.min()), H):
    m = bmask & (zz >= zb) & (zz < zt)
    if not m.any():
        continue
    vol[zz][m] = basewall[m]
for f in sorted([f for f in render if f["part"] and f["maxh"]], key=lambda f: -f["maxh"]):
    rr_, cc_ = f["rr"], f["cc"]
    k = bmask[rr_, cc_]
    rr_, cc_ = rr_[k], cc_[k]
    lo = g[rr_, cc_] + int(round(f["minh"]))
    hi = np.minimum(g[rr_, cc_] + int(round(f["maxh"])), zt[rr_, cc_])
    for zz in range(int(lo.min()) if len(lo) else 0, int(hi.max()) if len(hi) else 0):
        m = (zz >= lo) & (zz < hi)
        vol[zz, rr_[m], cc_[m]] = f["wall"]
# roofs: topmost voxel of every building column (+ terraces: voxels with empty above)
roofcol = np.zeros((D, W), np.uint16)
for f in sorted(render, key=lambda f: f["maxh"] or 0):
    roofcol[f["rr"], f["cc"]] = f["roof"]
roofcol = np.where(roofcol_fix > 0, roofcol_fix, roofcol)
# (patina copper is green in the ortho too, but as blue as it is green: Holy Cross's and the palaces' roofs had grown
# lime gardens; planted roofs are yellow-green, blue under 0.85 of green -- BUW's garden 0.70, patina 0.98-0.99)
green_roof = bmask & (exg > 0.08) & (topi < 40) & ~over & (cellcol[..., 2] < 0.85 * cellcol[..., 1])
# a green roof is an area, not a rim: the ortho's green along parapets (crowns hanging over the edge, copper, moss)
# put lime garden voxels on cornices and ledges all over the city. Opened by 1 cell, patches of 12+ cells, and not
# where the LiDAR stands 2 m above the roof (a crown over it)
green_roof &= nd_max < topi + 2
green_roof = ndimage.binary_opening(green_roof, iterations=1)
_gl, _gn = ndimage.label(green_roof)
if _gn:
    green_roof &= np.r_[False, ndimage.sum(green_roof, _gl, range(1, _gn + 1)) >= 12][_gl]
# a small step in a facade (a 1-3 m setback, a stair of a sloping wing, an edge left lower by the LiDAR) is wall, not
# roof: the building's roof colour (taken from the ortho over its whole top) put cream blobs and checkerboards on glass
# towers (Rondo 1, Złota 44's wing). Patches under 25 cells more than 6 m below the highest top within 3 m.
_ledge = bmask & (topi < ndimage.maximum_filter(np.where(bmask, topi, 0), 7) - 6)
_lab, _n = ndimage.label(_ledge)
if _n:
    _sz = ndimage.sum(_ledge, _lab, range(1, _n + 1))
    _ledge &= np.r_[False, _sz < 25][_lab]
roofcol = np.where(_ledge & ~green_roof, basewall, roofcol)
note("facade steps topped with wall colour:", int(_ledge.sum()))
rr, cc = np.nonzero(bmask)
vol[zt[rr, cc] - 1, rr, cc] = np.where(green_roof[rr, cc], C["garden"], roofcol[rr, cc])
# a steep tiled roof steps 2-3 m from cell to cell: under its top voxel each step's side showed the wall's plaster, so
# from the street the Old Town's roofs read as more storeys of facade. In the historic core, the side of a step down
# to a lower cell of the same roof takes the roof's tiles or copper -- a dome's flanks step 3-4 m (a tower's side or a
# setback of 5 m or more stays wall)
core_m = np.zeros((D, W), bool)
core_m[cells_of(CORE)] = True
mats_of_ids = np.array([e[3] for e in pal.entries] + [0] * 256)
n_rs = 0
for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
    nb_t = np.roll(zt, (dr, dc), (0, 1)); nb_b = np.roll(bmask, (dr, dc), (0, 1))
    step = bmask & nb_b & core_m & ~green_roof & (zt - nb_t >= 2) & (zt - nb_t <= 4)
    for k in (2, 3, 4):
        m = step & (zt - nb_t >= k)
        rr_, cc_ = np.nonzero(m)
        z_ = zt[rr_, cc_] - k
        keep = mats_of_ids[vol[z_, rr_, cc_]] != M_ROOF
        vol[z_[keep], rr_[keep], cc_[keep]] = roofcol[rr_[keep], cc_[keep]]
        n_rs += int(keep.sum())
note("historic core: roof step sides tiled:", n_rs)
note("green roof cells:", int(green_roof.sum()))
# rooftop plant rooms, lift housings and stair heads (1.5-5 m over a building's main roof, under 80 cells) are roof
# material, not facade: they wore the facade's office windows and read as little houses on every roof (Metropolitan)
n_rb = 0
for f in render:
    rr_, cc_ = f["rr"], f["cc"]
    if len(rr_) < 100 or f["part"]:
        continue
    t_ = topi[rr_, cc_]
    med_ = int(np.median(t_))
    if med_ < 6:
        continue
    up_ = (t_ > med_ + 1.5) & (t_ <= med_ + 5)  # a plant room, lift housing or stair head: one storey
    if not up_.any():
        continue
    m_ = np.zeros((rr_.max() - rr_.min() + 1, cc_.max() - cc_.min() + 1), bool)
    m_[rr_[up_] - rr_.min(), cc_[up_] - cc_.min()] = True
    lab_, nl_ = ndimage.label(m_)
    small_ = np.r_[False, ndimage.sum(m_, lab_, range(1, nl_ + 1)) < 80]
    # set back from the facade (none of it within 2 m of the outline's edge): a top storey flush with the facade
    # (Fabryczna 2's crown) is building, not plant room
    fp_ = np.zeros(m_.shape, bool)
    fp_[rr_ - rr_.min(), cc_ - cc_.min()] = True
    near_edge_ = ndimage.distance_transform_edt(np.pad(fp_, 1))[1:-1, 1:-1] <= 2
    flush_ = np.r_[False, ndimage.maximum(near_edge_ & m_, lab_, range(1, nl_ + 1)) > 0] if nl_ else np.zeros(1, bool)
    small_ &= ~flush_
    k_ = up_ & small_[lab_[rr_ - rr_.min(), cc_ - cc_.min()]]
    for r_, c_ in zip(rr_[k_], cc_[k_]):
        z0_, z1_ = int(g[r_, c_]) + med_, int(zt[r_, c_]) - 1
        col_ = vol[z0_:z1_, r_, c_]
        col_[col_ != 0] = roofcol[r_, c_]
        n_rb += 1
note("rooftop structures in roof material:", n_rb)

# ---------------------------------------------------------------- vegetation (LiDAR canopy + OSM trees)
trees = [(oid, t, p) for oid, t, p in osm.nodes if t.get("natural") == "tree"]
# every known tree: the city's green-areas database (inventory number, species, trunk), OSM, the 2010-13 inventory
import trees as treedb
all_trees, _tc = treedb.load(trees)
note("trees from the databases:", _tc, "total", len(all_trees))
tree_rc = np.array([(int(t["y"]), int(t["x"])) for t in all_trees])
near_tree = np.zeros((D, W), bool)
if len(tree_rc):
    near_tree[tree_rc[:, 0], tree_rc[:, 1]] = True
    near_tree = ndimage.binary_dilation(near_tree, iterations=3)
# green in the (leaf-on) ortho, or the LiDAR's own vegetation class (the PNOA flight was leaf-off, so its class is the
# surer sign under a bare crown); not where the LiDAR says building (eaves and cornices over the street)
veg = (~bmask) & (nd_mean > 2.2) & ((exg > 0.025) | (near_tree & (exg > -0.03)) | LIDAR_VEG) & (cls != 6)
note("vegetation cells from the LiDAR class alone (not green in the ortho):", int((veg & LIDAR_VEG & ~(exg > 0.025)).sum()))
# nor inside any building's outline: one drawn only through its parts (Salvator church) left the cells between its
# parts out of bmask, and its green copper roof grew 1 800 leaf voxels, pillars up its front
_allb = np.zeros((D, W), bool)
for f in feats:
    if not f["part"] and f["tags"].get("building") not in ("roof", "carport", "canopy"):
        _allb[f["rr"], f["cc"]] = True
note("vegetation cells inside building outlines dropped:", int((veg & _allb).sum()))
veg &= ~_allb
# LiDAR wall edges outside OSM footprints look like tall "trees": reject cells next to a building
# whose height is close to that building's roof
btop_near = ndimage.maximum_filter(np.where(bmask, topi, 0), size=7)
wall_edge = (btop_near > 0) & (nd_mean > 0.6 * btop_near) & (nd_mean > 6)
veg &= ~wall_edge | (near_tree & (nd_mean < 25))
step = ndimage.maximum_filter(nd_mean, 3) - ndimage.minimum_filter(nd_mean, 3)
veg &= ~((btop_near > 0) & (step > 7) & (nd_mean > 0.5 * btop_near))
veg &= nd_mean < MAX_TREE  # taller is a structure, not a crown
# no trees growing out of a stadium shell (its fins and roof edge are LiDAR-high and greenish in the ortho)
stad = np.zeros((D, W), np.uint16)
burn(stad, [(geom, 1) for oid, typ, t, geom in osm.areas_with("leisure", ("stadium",))])
veg &= ~((stad > 0) & ~near_tree)
veg = ndimage.binary_opening(veg, iterations=1)
note("wall-edge cells rejected as vegetation:", int(wall_edge.sum()))
lab, n = ndimage.label(veg)
sizes = ndimage.sum(veg, lab, range(1, n + 1))
veg &= np.isin(lab, np.nonzero(sizes >= 4)[0] + 1)
hs = ndimage.gaussian_filter(np.where(veg, nd_mean, 0), 2) / np.maximum(ndimage.gaussian_filter(veg.astype(float), 2), 1e-3)
crown_top = np.round(np.minimum(nd_mean, 40)).astype(np.int32)
# against a wall the DSM is the wall's (Telecom tower, Salvator: 1 m green pillars 20-30 m up the facades): within 2 m
# of a building a crown is no taller than its canopy away from the walls (gaussian mean x 1.25 + 2 m), 12 m with none
_nearb = ndimage.binary_dilation(bmask, iterations=2) & veg
_far = veg & ~ndimage.binary_dilation(bmask, iterations=2)
_wf = ndimage.gaussian_filter(_far.astype(np.float32), 3)
_hf = ndimage.gaussian_filter(np.where(_far, nd_mean, 0).astype(np.float32), 3) / np.maximum(_wf, 1e-3)
_cap = np.where(_wf > 0.05, _hf * 1.25 + 2, 12)
_clip = _nearb & (crown_top > _cap)
crown_top = np.where(_clip, np.round(_cap), crown_top).astype(np.int32)
note("crowns against walls clipped to their canopy:", int(_clip.sum()))
crown_bot = np.clip(np.round(hs * 0.38), 2, None).astype(np.int32)
crown_bot = np.minimum(crown_bot, crown_top - 1)
# leaf colour from ortho: luminance x hue bins
hue = np.zeros((D, W), np.float32)
r_, g_, b_ = cellcol[..., 0], cellcol[..., 1], cellcol[..., 2]
yellowish = (r_ - b_) / rgbsum > 0.05
lbin = np.clip(((lum - 40) / 110 * 5).astype(int), 0, 4)
leafidx = np.array(LEAVES, np.uint16)[(4 - lbin) + 5 * (~yellowish)]

# trunks: every known tree standing under a LiDAR crown gets one, from the ground up into its crown (the crown's leaf
# columns start at crown_bot, so the trunk's top voxel touches them face to face: the crown stands, it does not float);
# a known tree with no crown in the 2025 LiDAR (planted since) is drawn procedurally. Crowns that no database tree
# stands under get trunks at their tops (local maxima of the canopy height, >= 5 m apart).
n_new = n_trunk = 0
from shapely.ops import unary_union
canopy_near = ndimage.binary_dilation(veg, iterations=2)
_vd, (_vr, _vc) = ndimage.distance_transform_edt(~veg, return_indices=True)
trunk_at = np.zeros((D, W), bool)
# where a trunk may stand: never on a carriageway, rails, tram bed or in the water; a trunk placed only from the canopy
# (no tree known there) also not on paths and squares -- it would stand in the walkers' way -- but on soft ground
_hard = np.isin(gcol, [C[k] for k in ("water", "asphalt", "asphalt_l", "rail", "trambed", "ballast", "cycle", "parking")]) | is_road
trunk_ok_db = ~_hard
trunk_ok_peak = np.isin(gcol, [C[k] for k in ("grass", "grass2", "garden", "scrub", "dirt", "dirt2", "fresh", "bare", "soil",
                                               "flower", "flower2", "gravel")]) & ~is_road
_okd, (_okr, _okc) = ndimage.distance_transform_edt(~(trunk_ok_peak & veg), return_indices=True)
_dbd, (_dbr, _dbc) = ndimage.distance_transform_edt(~(trunk_ok_db & veg), return_indices=True)


trunks = []  # (row, col, thick): drawn once the crowns are shaped around them


trunk_conifer = []  # per trunk: a conifer by the database's species (or OSM leaf_type)


def put_trunk(r, c, thick=False, conifer=False):
    trunks.append((r, c, thick))
    trunk_conifer.append(conifer)
    trunk_at[r, c] = True


for t in all_trees:
    c, r = int(t["x"]), int(t["y"])
    if not (2 <= c < W - 2 and 2 <= r < D - 2) or bmask[r, c]:
        t["drawn"] = "none"
        continue
    if canopy_near[r, c]:
        if not veg[r, c] and _vd[r, c] <= 2.5:  # the point just off its crown's LiDAR cells: under the nearest one
            r, c = int(_vr[r, c]), int(_vc[r, c])
        if veg[r, c] and not trunk_ok_db[r, c] and _dbd[r, c] <= 3:  # mapped onto the road edge: to the kerb side
            r, c = int(_dbr[r, c]), int(_dbc[r, c])
        if veg[r, c]:
            put_trunk(r, c, thick=(t.get("trunk_cm") or 0) >= 250, conifer=treedb.is_conifer(t))
            t["drawn"] = "lidar"
            t["z"] = int(g[r, c])
            t["h"] = int(crown_top[r, c])
            n_trunk += 1
            continue
        t["drawn"] = "none"  # under another tree's crown edge: its own crown is not resolved
        continue
    n_new += 1
    # a known tree the leaf-off LiDAR resolved no crown for: drawn young, at its inventory height when it has one
    hgt = t.get("height")
    landmarks.small_tree(vol, g, r, c, stable_hash(t["id"]), LEAVES, C["trunk"], height=hgt)
    t["drawn"] = "procedural"
    t["z"] = int(g[r, c])
note("trunks under LiDAR crowns at known trees:", n_trunk)
note("known trees without a 2025 LiDAR crown -> procedural:", n_new)
# crowns no database tree stands under: a trunk at each canopy top >= 5 m from any trunk
peak = veg & (nd_mean >= ndimage.maximum_filter(np.where(veg, nd_mean, 0), size=7)) & (nd_mean >= 4)
_td = ndimage.distance_transform_edt(~trunk_at)
pr_, pc_ = np.nonzero(peak & (_td >= 5))
order = np.argsort(-nd_mean[pr_, pc_])
taken = np.zeros((D, W), bool)
n_peak = 0
for k in order:
    r, c = int(pr_[k]), int(pc_[k])
    if taken[max(0, r - 4):r + 5, max(0, c - 4):c + 5].any():
        continue
    if not trunk_ok_peak[r, c]:  # the crown's top over a path or a road: the trunk on the nearest soft ground under it,
        if _okd[r, c] <= 4:      # else on the pavement (a street tree), never on the carriageway
            r, c = int(_okr[r, c]), int(_okc[r, c])
        elif not trunk_ok_db[r, c]:
            if _dbd[r, c] > 3:
                continue
            r, c = int(_dbr[r, c]), int(_dbc[r, c])
    put_trunk(r, c)
    taken[r, c] = True
    n_peak += 1
note("trunks at canopy tops with no known tree under them:", n_peak)
# crowns, one per trunk: every canopy cell belongs to its nearest trunk; the crown's underside is a dome -- lowest
# (38 % of the tree's height) over the trunk, rising to the LiDAR top at the crown's rim -- instead of one flat green
# ceiling over the whole park (the LiDAR gives only the top surface; the dome is the usual lime / maple / chestnut form)
if trunks:
    tidx = np.zeros((D, W), np.int32)
    for i_, (r_, c_, _) in enumerate(trunks, 1):
        tidx[r_, c_] = i_
    _dt, (_tr_, _tc_) = ndimage.distance_transform_edt(tidx == 0, return_indices=True)
    own = np.where(veg, tidx[_tr_, _tc_], 0)
    idx_ = np.arange(1, len(trunks) + 1)
    Rt = np.asarray(ndimage.maximum(np.where(veg, _dt, 0), labels=own, index=idx_), np.float32) + 0.7
    Ht = np.asarray(ndimage.maximum(np.where(veg, crown_top, 0), labels=own, index=idx_), np.float32)
    vr_, vc_ = np.nonzero(veg)
    k_ = own[vr_, vc_] - 1
    ok_ = k_ >= 0
    dep = 0.62 * Ht[k_] * np.sqrt(np.clip(1 - (_dt[vr_, vc_] / Rt[k_]) ** 2, 0, 1))
    bot = np.round(crown_top[vr_, vc_] - np.maximum(dep, 1)).astype(np.int32)
    bot = np.clip(bot, 2, crown_top[vr_, vc_] - 1)
    crown_bot[vr_[ok_], vc_[ok_]] = bot[ok_]
    # conifers (thuja, pine, spruce, yew...: the city database's species) in dark blue-green needles, not leaf green
    con = np.array(trunk_conifer, bool)
    cm_ = ok_.copy()
    cm_[ok_] = con[k_[ok_]]
    NEEDLES = np.array([pal(c_, M_LEAF) for c_ in ("#3f5f48", "#456a4f", "#4d7356", "#37553f", "#52785a")], np.uint16)
    leafidx[vr_[cm_], vc_[cm_]] = NEEDLES[(vr_[cm_] * 7 + vc_[cm_] * 3) % len(NEEDLES)]
    note("conifer crowns (database species):", int(con.sum()), "cells", int(cm_.sum()))
# clearance under the crowns: street trees in Madrid are pruned to keep the leaves well above walkers and traffic
# (Serrano's plane trees branch at about 4-5 m), so over carriageways, cycle lanes, parking and rails the leaves start
# at CLEAR_ROAD (buses and lorries), over pavements, squares, tree pits and the gravel and earth of boulevards and park
# paths (the Salón del Prado, the Retiro) at CLEAR_WALK, and over lawns, beds and scrub at CLEAR_PLANTED. A crown's
# rim left thinner than a voxel loses its leaves rather than hang as a slab (veg itself is kept: the parked-car test
# reads it)
CLEAR_ROAD, CLEAR_WALK, CLEAR_PLANTED = 6.0, 4.5, 3.0  # metres
_road_under = _hard & (gcol != C["water"])
_planted = np.isin(gcol, [C[k] for k in ("grass", "grass2", "garden", "flower", "flower2", "scrub")]) & ~is_road
_clear = np.where(_road_under, round(CLEAR_ROAD / VOXEL_SIZE),
                  np.where(_planted, round(CLEAR_PLANTED / VOXEL_SIZE), round(CLEAR_WALK / VOXEL_SIZE))).astype(np.int32)
crown_bot = np.maximum(crown_bot, _clear)
leaf_at = veg & (crown_top - crown_bot >= 1)
note("canopy cells raised to clear walkers and traffic:", int((veg & (_clear > 0)).sum()),
     "rim cells left bare:", int((veg & ~leaf_at).sum()))
rr, cc = np.nonzero(leaf_at)
for zz in range(int(g.min()) + 1, int((g + crown_top).max()) + 1):
    m = (zz >= g[rr, cc] + crown_bot[rr, cc]) & (zz < g[rr, cc] + crown_top[rr, cc])
    sel = (rr[m], cc[m])
    cur = vol[zz][sel]
    vol[zz][sel] = np.where(cur == 0, leafidx[sel], cur)
note("canopy cells:", int(veg.sum()), "crowns:", len(trunks))
for r_, c_, thick in trunks:  # from the ground one voxel into the crown's lowest point, over the trunk
    hb = min(int(crown_bot[r_, c_]) + 1, int(crown_top[r_, c_]))  # a bare rim cell: no higher than the crown
    for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)) if thick else ((0, 0),):
        rr_, cc_ = r_ + dr, c_ + dc
        if 0 <= rr_ < D and 0 <= cc_ < W and not bmask[rr_, cc_]:
            vol[g[rr_, cc_]:g[rr_, cc_] + hb, rr_, cc_] = C["trunk"]
# the tree register for the viewer (ids for later mapping: city inventory number / osm node / 2010-13 inventory)
note("trees inside a Mapa Koron Drzew crown:", treedb.attach_crowns(all_trees))
for r, c in zip(*np.nonzero(taken)):  # the trunks placed at canopy tops: no database tree, an id from the cell
    all_trees.append(dict(id=f"lidar:{r}_{c}", src="lidar", x=float(c) + 0.5, y=float(r) + 0.5, drawn="lidar",
                          z=int(g[r, c]), h=int(crown_top[r, c])))
_tr = []
for t in all_trees:
    rec = dict(id=t["id"], x=round(t["x"], 1), y=round(t["y"], 1), src=t["src"], drawn=t.get("drawn"))
    for k_src, k_out in (("z", "z"), ("h", "h"), ("species", "sp"), ("species_pl", "pl"), ("trunk_cm", "cm"),
                         ("osm", "osm"), ("um_id", "um"), ("height", "h_inv"), ("crown_d", "crown_d"),
                         ("condition", "cond"), ("manager", "mgr"), ("date", "date"), ("crown_id", "crown"),
                         ("crown_m2", "crown_m2"), ("crown_sp", "crown_sp")):
        if t.get(k_src) is not None:
            rec[k_out] = t[k_src]
    _tr.append(rec)
Path(OUT).mkdir(parents=True, exist_ok=True)
json.dump(dict(sources={"city": "Ayuntamiento de Madrid tree inventory, datos.madrid.es (CC BY 4.0)",
                        "osm": "OpenStreetMap natural=tree",
                        "lidar": "a crown in the PNOA-LiDAR with no known tree under it (trunk at its top)"},
               fields=dict(x="grid column", y="grid row", z="ground voxel", h="LiDAR crown top above ground, m",
                           sp="species (botanical)", cm="trunk circumference, cm", h_inv="inventory height, m",
                           drawn="lidar | procedural | none"), trees=_tr),
          open(Path(OUT) / "trees.json", "w"), ensure_ascii=False, separators=(",", ":"))

# ---------------------------------------------------------------- fountains (docs/warsaw/visual_ref.md, Commons photos Aug 2026)
# Flat walk-on fountain on the filled-in Marszałkowska tunnel ramp: dark speckled granite cut into irregular
# polygons, darker shard inlays, flush with the paving, slot drain round the edge, jets from steel rings ~2 m apart.
GRAN = [pal("#6a6e71"), pal("#62666a"), pal("#72767a")]
SHARD, DRAIN, RING = pal("#4a4d50"), pal("#3a3c3f", M_METAL), pal("#b9bdc0", M_METAL)
n_jets = 0
jets = []
for geom in splash_pads:
    rr, cc = cells_of(geom)
    if len(rr) == 0:
        continue
    m = np.zeros((D, W), bool)
    m[rr, cc] = True
    edge = m & ~ndimage.binary_erosion(m)
    # polygon slabs: Voronoi cells around a few random seeds
    rng = np.random.default_rng(stable_hash(int(rr.mean()), int(cc.mean())))
    seeds = np.stack([rng.uniform(rr.min(), rr.max() + 1, 14), rng.uniform(cc.min(), cc.max() + 1, 14)], 1)
    for r, c in zip(rr, cc):
        z0 = g[r, c] - 1
        d2 = ((seeds - (r + 0.5, c + 0.5)) ** 2).sum(1)
        o2 = np.sort(d2)
        k = int(np.argmin(d2))
        if edge[r, c]:
            v = DRAIN
        elif o2[1] - o2[0] < 1.6:  # seam between slabs
            v = SHARD
        elif r % 2 == 0 and c % 2 == 0:
            v = RING
            jets.append([c + 0.5, int(z0 + 1), r + 0.5])  # rendered as animated water columns in the viewer
            n_jets += 1
        else:
            v = SHARD if stable_hash(r, c, 7) % 23 == 0 else GRAN[k % 3]
        vol[z0, r, c] = v
note("splash-pad fountain jets:", n_jets)

# ---------------------------------------------------------------- planted beds
# small leisure=garden / flowerbed islands are raised perennial beds edged with concrete bench-kerbs (photos 2026)
n_beds = 0
for oid, typ, t, geom in osm.areas:
    if not (t.get("leisure") == "garden" or t.get("landuse") == "flowerbed") or tunnelish(t) or not (4 <= geom.area <= 400):
        continue
    rr, cc = cells_of(geom)
    k = ~bmask[rr, cc]
    rr, cc = rr[k], cc[k]
    if len(rr) == 0:
        continue
    m = np.zeros((D, W), bool)
    m[rr, cc] = True
    edge = m & ~ndimage.binary_erosion(m)
    for r, c in zip(rr, cc):
        z0 = g[r, c]
        if vol[z0, r, c] != 0:
            continue
        if edge[r, c] and geom.area > 12:
            vol[z0, r, c] = C["benchkerb"]
        elif stable_hash(oid, r, c) % 5:
            vol[z0, r, c] = PERENNIALS[stable_hash(r, c, oid) % len(PERENNIALS)]
    n_beds += 1
note("raised planting beds:", n_beds)

# ---------------------------------------------------------------- street furniture
# a post stands beside the carriageway and the tracks, not in them: OSM's lamp nodes sit on the kerb line, and 89 of
# them fell a metre or two inside the road as drawn (cars drove through the poles); such a post takes the nearest
# cell off the road within 4 m, and one deeper in (a lamp hung over the street) gets no pole
_driven = is_road | np.isin(gcol, [C["trambed"], C["rail"], C["ballast"]])
_kd, (_kr, _kc) = ndimage.distance_transform_edt(_driven, return_indices=True)


def kerb(c, r):
    if not (0 <= c < W and 0 <= r < D):
        return None
    return (int(_kc[r, c]), int(_kr[r, c])) if _kd[r, c] <= 4 else None


# lamp heights where OSM gives none, by the street beside the post: Madrid's avenues have columns of about 8 m, its
# ordinary streets lower ones (and wall brackets), squares and pedestrian streets the 4 m "fernandino" lantern posts;
# Warsaw's 10 m / 6 m stood over the walkers. A road at least LAMP_AVENUE_W wide within 6 m makes an avenue
LAMP_AVENUE, LAMP_STREET, LAMP_WALK, LAMP_AVENUE_W = 8.0, 5.0, 4.0, 12.0  # metres
_road_half = ndimage.maximum_filter(ndimage.distance_transform_edt(is_road), size=2 * round(6 / VOXEL_SIZE) + 1)


def lamp_height(r, c):
    if _road_half[r, c] * VOXEL_SIZE >= LAMP_AVENUE_W / 2:
        return round(LAMP_AVENUE / VOXEL_SIZE)
    near = round(6 / VOXEL_SIZE)
    if is_road[max(r - near, 0):r + near + 1, max(c - near, 0):c + near + 1].any():
        return round(LAMP_STREET / VOXEL_SIZE)
    return round(LAMP_WALK / VOXEL_SIZE)


lamps = []
for oid, t, p in osm.nodes_with("highway", ("street_lamp",)):
    c, r = kerb(int(p.x), int(p.y)) or (-1, -1)
    if not (0 <= c < W and 0 <= r < D) or bmask[r, c]:
        continue
    hgt = int(parse_len(t.get("height")) or lamp_height(r, c))
    z0 = g[r, c]
    vol[z0:z0 + hgt - 1, r, c] = np.where(vol[z0:z0 + hgt - 1, r, c] == 0, C["pole"], vol[z0:z0 + hgt - 1, r, c])
    vol[z0 + hgt - 1, r, c] = C["lamp"]
    lamps.append((c, r, int(z0 + hgt - 1)))
note("street lamps:", len(lamps))
lamp_xy = np.array([(c, r) for c, r, _ in lamps], float) if lamps else np.zeros((0, 2))  # for lamps inferred later
for oid, typ, t, geom in osm.areas_with("amenity", ("shelter",)):
    if t.get("shelter_type") not in (None, "public_transport", "basic_hut") or bmask[cells_of(geom)].any():
        continue
    rr, cc = cells_of(geom)
    zz = g[rr, cc] + 2
    vol[zz, rr, cc] = C["shelter"]
    vol[g[rr, cc], rr, cc] = np.where((rr + cc) % 3 == 0, C["pole"], 0)

for oid, t, p in osm.nodes_with("man_made", ("flagpole",)):
    c, r = int(p.x), int(p.y)
    if 0 <= c < W and 0 <= r < D and not bmask[r, c]:
        hgt = int(parse_len(t.get("height")) or 9)
        vol[g[r, c]:g[r, c] + hgt, r, c] = C["fence"]

# bridges / decks: over the rail cut (DTM drops below them) and the Vistula. The deck follows the bridge ways
# (bridge=yes roads, paths, tracks buffered to their width; man_made=bridge areas only near them). Its top takes the
# colour of the way on it (asphalt, pavement, cycle lane, tram bed).
deck_col = np.zeros((D, W), np.uint16)
deck_lay = np.zeros((D, W), np.uint16)  # the layer of the way that owns the cell
bridge_area = np.zeros((D, W), np.uint16)
burn(bridge_area, [(geom, 1) for oid, typ, t, geom in osm.areas_with("man_made", ("bridge",))])
for layer in sorted({l for _, _, l in bridge_shapes}):  # upper decks win
    burn(deck_col, [(p_, c_) for p_, c_, l in sorted(bridge_shapes, key=lambda x: -x[0].area) if l == layer])
    burn(deck_lay, [(p_, l + 1) for p_, c_, l in bridge_shapes if l == layer])
near_way = ndimage.binary_dilation(deck_col > 0, iterations=3)
deck_col = np.where((deck_col == 0) & (bridge_area > 0) & near_way, C["deck"], deck_col)
# and the LiDAR's bridge class (17) near a bridge way, where OSM's bridge outline falls short
_lb = (deck_col == 0) & LIDAR_BRIDGE & near_way
deck_col = np.where(_lb, C["deck"], deck_col)
note("deck cells from the LiDAR bridge class:", int(_lb.sum()))
deck = (deck_col > 0) & (nd_mean > 2)
deck = ndimage.binary_closing(deck, iterations=2)  # no slits of sky between the carriageways
deck_col = np.where(deck & (deck_col == 0), C["deck"], deck_col)
# the deck's height: a profile along each bridge way -- the DSM (0.5 m) sampled across the way every metre, its 30th
# percentile (the road surface, not the cars, railings or stays), samples dropped where a higher deck hides the way or
# nothing stands above the river, then a 25 m running median and a 15 m mean. Every deck cell takes the height of the
# nearest profile point of its own layer: one smooth level, so cars drive on it. (The cell-by-cell lowest return
# picked up cells half over the water at the deck edges and broke the decks into steps metres apart.)
from scipy.spatial import cKDTree
water_ = gcol == C["water"]
prof = []  # per way: (x, y, h, layer) every metre
for line, hw, layer, _ in bridge_lines:
    n_ = max(2, int(line.length) + 1)
    P_ = np.array([line.interpolate(v_).coords[0] for v_ in np.linspace(0, line.length, n_)])
    T_ = np.gradient(P_, axis=0)
    T_ /= np.maximum(np.linalg.norm(T_, axis=1, keepdims=True), 1e-6)
    a_, b_ = np.meshgrid(np.arange(-1.5, 1.6, 0.5), np.arange(-max(0.7 * hw, 0.5), max(0.7 * hw, 0.5) + 0.01, 0.5))
    a_, b_ = a_.ravel(), b_.ravel()
    X_ = P_[:, :1] + T_[:, :1] * a_ - T_[:, 1:] * b_
    Y_ = P_[:, 1:] + T_[:, 1:] * a_ + T_[:, :1] * b_
    h_ = np.nanpercentile(dsm[np.clip((Y_ * 2).astype(int), 0, 2 * D - 1), np.clip((X_ * 2).astype(int), 0, 2 * W - 1)], 30, axis=1)
    pr_, pc_ = np.clip(P_[:, 1].astype(int), 0, D - 1), np.clip(P_[:, 0].astype(int), 0, W - 1)
    gd_ = dtm[pr_, pc_]
    ok_ = np.isfinite(h_) & (deck_lay[pr_, pc_] <= layer + 1) & ((h_ > gd_ + 1.5) | (~water_[pr_, pc_] & (h_ > gd_ - 1.5)))
    if ok_.sum() >= 2:
        h_ = np.interp(np.arange(n_), np.nonzero(ok_)[0], h_[ok_])
    else:  # hidden all along (a walkway slung under a higher deck): straight between its ends' ground
        h_ = np.linspace(gd_[0], gd_[-1], n_)
    for win in (61, 31, 15):  # the deck is the lowest surface: knock down what stands on it (a pylon's legs, cables)
        hs_ = ndimage.median_filter(h_, min(win, n_), mode="nearest")
        h_ = np.where(h_ > hs_ + 0.6, hs_, h_)
    prof.append(np.column_stack([P_, h_, np.full(n_, layer + 1)]))
deck_abs = np.zeros((D, W), np.float32)
if prof:
    # across the deck the ways agree: one surface per layer, each point the low end (10th percentile) of its layer
    # within 10 m. Each way on its own rounded to a different metre from its neighbour (steps along the deck between
    # the lanes); and where they disagree, the higher ones stand under something -- Most Świętokrzyski's stays lean
    # over the outer lanes for 150 m each side of the pylon, so their profile climbed smoothly to the pylon (no spike
    # for the running median to knock down), and with the median of the lanes the deck rose 23 m in mounds round it
    allp = np.vstack(prof)
    for L_ in np.unique(allp[:, 3]):
        sel_ = allp[:, 3] == L_
        sub_ = allp[sel_]
        nb_ = cKDTree(sub_[:, :2]).query_ball_point(sub_[:, :2], 10.0)
        allp[sel_, 2] = [np.percentile(sub_[i_, 2], 10) for i_ in nb_]
    k0 = 0
    for i_, pw_ in enumerate(prof):
        h_ = allp[k0:k0 + len(pw_), 2]
        n_ = len(h_)
        pw_[:, 2] = ndimage.uniform_filter1d(ndimage.median_filter(h_, min(25, n_), mode="nearest"), min(15, n_), mode="nearest")
        k0 += n_
    # a bridge way often ends (in OSM) metres before the ground climbs back to the deck: the deck carries on along the
    # way's direction, level, until the ground is within 1.5 m of it (up to 15 m) -- no hole for the cars to drop into
    ext_shapes = []
    for (line, hw, layer, col_), pw_ in zip(bridge_lines, list(prof)):
        if len(pw_) < 3:
            continue
        for e0, e1 in ((0, 2), (-1, -3)):
            P0, h0 = pw_[e0, :2], pw_[e0, 2]
            u_ = P0 - pw_[e1, :2]
            u_ = u_ / max(np.linalg.norm(u_), 1e-6)
            ext = []
            for d_ in range(1, 16):
                q = P0 + u_ * d_
                r_, c_ = int(q[1]), int(q[0])
                if not (0 <= r_ < D and 0 <= c_ < W) or dtm[r_, c_] >= h0 - 1.5 or bmask[r_, c_]:
                    break
                ext.append(q)
            if not ext:
                continue
            ext_shapes.append((LineString([P0, ext[-1]]).buffer(max(hw, 1.5), cap_style="flat"), col_, layer + 1))
            prof.append(np.column_stack([np.array(ext), np.full(len(ext), h0), np.full(len(ext), layer + 1)]))
    for L_ in sorted({l for _, _, l in ext_shapes}):
        m_ = np.zeros((D, W), np.uint16)
        burn(m_, [(p_, c_) for p_, c_, l in ext_shapes if l == L_])
        m_ = np.where((m_ > 0) & ~bmask & (deck_lay <= L_) & ~deck, m_, 0)
        deck_col[m_ > 0] = m_[m_ > 0]
        deck_lay[m_ > 0] = L_
        deck |= m_ > 0
    note("bridge ends carried on to meet the ground:", len(ext_shapes))
    prof = np.vstack(prof)
    # where the ground climbs to the deck (an abutment, an embankment the DTM runs up under the deck) the LiDAR stands
    # less than 2 m over it: still the deck, if the surface is at the deck's level (else pits down to the ground)
    abut = (deck_col > 0) & ~bmask & ~deck & ndimage.binary_dilation(deck, iterations=15)
    rr, cc = np.nonzero(deck | abut)
    for L_ in np.unique(deck_lay[rr, cc]):
        sel = deck_lay[rr, cc] == L_
        pts = prof if L_ == 0 or not (prof[:, 3] == L_).any() else prof[prof[:, 3] == L_]
        d_, k_ = cKDTree(pts[:, :2]).query(np.column_stack([cc[sel] + 0.5, rr[sel] + 0.5]), k=min(12, len(pts)))
        w_ = 1 / np.maximum(d_, 0.5) ** 2  # a smooth surface between the ways: any step is a contour across the deck
        deck_abs[rr[sel], cc[sel]] = (pts[k_, 2] * w_).sum(1) / w_.sum(1)
zt_ = np.round(deck_abs - BASE).astype(np.int32)
if prof is not None and len(prof):
    deck |= abut & (np.abs(dsm_mean - deck_abs) < 1.0)
deck &= zt_ >= g + 1
# a building and a deck in one cell: the LiDAR says which is on top. A building whose roof is at the deck or under it
# stands under the bridge (the shops in the arcades of Poniatowski's viaduct, Warszawa Centralna's halls under Aleja
# Jana Pawła II: 160 and 180 m of carriageway and tram track were drawn as bare roofs); it keeps its walls up to the
# deck. A building rising over the deck stands beside it or on it (the viaduct's towers), and there is no deck in it
_btop = g + topi
_under = deck & bmask & (_btop <= zt_ + 2)
deck &= ~bmask | _under
_ru, _cu = np.nonzero(_under)
for _z in range(int(zt_[_ru, _cu].min()) if len(_ru) else 0, int(_btop[_ru, _cu].max()) + 4 if len(_ru) else 0):
    _m = _z >= zt_[_ru, _cu]
    vol[_z, _ru[_m], _cu[_m]] = 0
note("deck cells over buildings under a bridge:", int(_under.sum()), "building cells that keep the deck out:", int(((deck_col > 0) & bmask & ~_under).sum()))
deck_h = np.where(deck, zt_ - g, 0).astype(np.float32)
landmarks.DECK = np.where(deck, zt_, 0).astype(np.int16)  # the deck top, for the curated bridge structures
# under a deck over the river nothing hangs but the bridge's own structure (landmarks.py): LiDAR columns caught at the
# deck edge (catenary masts, railings, green from the ortho) were extruded into dangling bits; and no tree crown grows
# into the underside of a deck anywhere
_leafy = np.zeros(len(pal.entries) + 64, bool)
_leafy[[i for i, e in enumerate(pal.entries) if e[3] == M_LEAF] + [C["trunk"]]] = True
_rw, _cw = np.nonzero(deck)
_wet = water_[_rw, _cw]
for _z in range(int(g.min()), int(zt_.max()) + 6):
    _m = (_z >= g[_rw, _cw]) & (_z < zt_[_rw, _cw] + 6)
    _v = vol[_z, _rw[_m], _cw[_m]]
    _under = _z < zt_[_rw[_m], _cw[_m]] - 2
    vol[_z, _rw[_m], _cw[_m]] = np.where((_under & _wet[_m]) | _leafy[_v], 0, _v)  # (a crown poking through the deck too)
# and beside a deck over the water (3 m): the LiDAR's returns off the deck's edge, green in the ortho, stood as crowns
# hanging from the edge down to the river (Most Śląsko-Dąbrowski); no tree grows in the river there
_rim = ndimage.binary_dilation(deck, iterations=3) & ~deck & water_
_rr, _cr = np.nonzero(_rim)
n_rim = 0
for _z in range(int(g.min()), int(zt_.max()) + 6):
    _v = vol[_z, _rr, _cr]
    _k = _leafy[_v]
    vol[_z, _rr[_k], _cr[_k]] = 0
    n_rim += int(_k.sum())
note("leaves off the water beside the decks:", n_rim)
# a railway bridge carries its track across: the rails on the ballast, and ballast (not the grey road deck) between
# tracks and to the deck edges -- the rail bridge read as a road with a step where the track left the embankment
_way = (deck_col > 0) & (deck_col != C["deck"])
_dw, (_iw, _jw) = ndimage.distance_transform_edt(~_way, return_indices=True)
_fill = deck & (deck_col == C["deck"]) & (deck_col[_iw, _jw] == C["ballast"]) & (_dw <= 4)
deck_col[_fill] = C["ballast"]
# the lane markings of the roads on the bridges (they were painted on the ground under the deck)
_lm_deck = deck & (lm > 0) & (deck_col == C["asphalt"])
deck_col[_lm_deck] = C["mark"]
note("lane marking cells on decks:", int(_lm_deck.sum()))
_rl = np.zeros((D, W), np.uint16)
burn(_rl, bridge_rails + rails, all_touched=True)  # (the ground track's too: the deck runs on over the abutments)
_on = deck & (_rl > 0) & np.isin(deck_col, [C["ballast"], C["trambed"]])  # rails lie on a track bed, a tram's too
deck_col[_on] = _rl[_on]
note("rail decks: ballast fill", int(_fill.sum()), "rail cells", int(_on.sum()))
rr, cc = np.nonzero(deck)
if len(rr):
    zt_ = zt_[rr, cc]
    for dz in (1, 2):
        vol[zt_ - dz, rr, cc] = C["deck"]
    vol[zt_ - 1, rr, cc] = deck_col[rr, cc]
note("bridge deck cells:", int(deck.sum()))
# bridge pylons (Most Świętokrzyski's ~90 m mast): compact LiDAR blobs far above the deck inside a bridge
pyl = (bridge_area > 0) & (nd_max > np.where(deck_h > 0, deck_h, nd_mean) + 45) & ~bmask  # the stays fan out low; only the mast stands this high
pyl = ndimage.binary_opening(pyl, iterations=2)  # the cable-stay fan is a thin sheet in the LiDAR; the mast is thick
lab_, n_ = ndimage.label(pyl)
n_pyl = 0
for i_, sl in enumerate(ndimage.find_objects(lab_), 1):
    m_ = lab_[sl] == i_
    if m_.sum() < 6 or max(m_.shape) > 25:  # a mast is compact; a long sheet is the cable fan
        continue
    for r_, c_ in zip(*np.nonzero(m_)):
        r_, c_ = r_ + sl[0].start, c_ + sl[1].start
        z0_, z1_ = int(g[r_, c_]), int(g[r_, c_] + round(float(nd_max[r_, c_])))
        vol[z0_:z1_, r_, c_] = np.where(vol[z0_:z1_, r_, c_] == 0, C["fence"], vol[z0_:z1_, r_, c_])
    n_pyl += 1
note("bridge pylons from LiDAR:", n_pyl)
# lamps on the bridges: OSM maps almost none on the Vistula bridges (0 on Świętokrzyski and Poniatowskiego), but they
# are lit -- put one every 32 m on each kerb of the deck, as for Złota, unless OSM has a lamp within 12 m. A kerb is
# deck that carries no way of its own, with no carriageway or track within 4 m beyond it: the inner side of a
# carriageway with tram tracks beside it (Poniatowski) has none, and its lamps stood in the trams' way
_bed = np.isin(deck_col, [C["asphalt"], C["mark"], C["trambed"], C["ballast"], C["rail"]])
n_bl = 0
for line, w in bridge_roads:
    for k_, dist in enumerate(np.arange(10, line.length - 6, 32.0)):
        p = line.interpolate(dist)
        q_ = line.interpolate(min(dist + 1, line.length))
        tx, ty = q_.x - p.x, q_.y - p.y
        tl = max(np.hypot(tx, ty), 1e-6)
        for side in (-1, 1):
            off = side * (w / 2 + 0.4)
            c, r = int(p.x - ty / tl * off), int(p.y + tx / tl * off)
            if not (0 <= c < W and 0 <= r < D) or not deck[r, c] or _bed[r, c]:
                continue
            if any(_bed[min(max(int(p.y + tx / tl * (off + side * d_)), 0), D - 1), min(max(int(p.x - ty / tl * (off + side * d_)), 0), W - 1)]
                   for d_ in (1, 2, 3, 4)):
                continue
            if len(lamp_xy) and np.min(np.hypot(lamp_xy[:, 0] - c, lamp_xy[:, 1] - r)) < 12:
                continue
            z0 = int(g[r, c] + round(float(deck_h[r, c])))
            vol[z0:z0 + 8, r, c] = np.where(vol[z0:z0 + 8, r, c] == 0, C["pole"], vol[z0:z0 + 8, r, c])
            vol[z0 + 8, r, c] = C["lamp"]
            lamps.append((c, r, int(z0 + 8)))
            lamp_xy = np.vstack([lamp_xy, [c, r]])
            n_bl += 1
note("inferred lamps on bridge decks (OSM has almost none):", n_bl)

# ---------------------------------------------------------------- vehicles frozen from the 2025 LiDAR + ortho
# only parked cars stay frozen; cars caught mid-carriageway by the 2025 flight are replaced by the live simulation
veh = (~bmask) & (~veg) & (parking_mask > 0) & (nd_mean > 1.1) & (nd_mean < 4.2)
lab, n = ndimage.label(veh)
objs = ndimage.find_objects(lab)
n_cars = n_bus = 0
for i, sl in enumerate(objs, 1):
    m = lab[sl] == i
    area = int(m.sum())
    if area < 4 or area > 70:
        continue
    rr, cc = np.nonzero(m)
    rr, cc = rr + sl[0].start, cc + sl[1].start
    hmean = float(nd_mean[rr, cc].mean())
    col = np.median(cellcol[rr, cc], axis=0)
    hsv = list(colorsys.rgb_to_hsv(*(col / 255)))
    hsv[1] = min(1, hsv[1] * 1.4)
    hsv[2] = min(1, hsv[2] * 1.1)
    col = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(*hsv))
    idx = pal(col, M_CAR, q=16)
    big = area > 22 and hmean > 2.4
    z0 = g[rr, cc]
    vol[z0, rr, cc] = idx
    if big:
        vol[z0 + 1, rr, cc] = idx
        vol[z0 + 2, rr, cc] = pal((235, 235, 235), M_CAR)
        n_bus += 1
    else:
        # cabin: inner cells only
        er = ndimage.binary_erosion(m)
        r2, c2 = np.nonzero(er)
        if len(r2):
            vol[g[r2 + sl[0].start, c2 + sl[1].start] + 1, r2 + sl[0].start, c2 + sl[1].start] = pal((60, 72, 86), M_GLASS)
        n_cars += 1
note("vehicles from LiDAR:", n_cars, "cars,", n_bus, "buses/trams/trucks")

# churches' walls are the plain classic material (no grid of office storeys): without windows of their own they read
# as blank blocks (Holy Cross, the Carmelites, St Alexander's). Tall windows on every straight outer edge, a second
# row under the eaves of the tall ones; the curated churches redraw theirs later
_win = pal((58, 70, 68), 21)
n_cw = 0
for f in render:
    t_ = f["tags"]
    if f["part"] or f["geom"].geom_type != "Polygon" or len(f["rr"]) < 150 or \
            not (t_.get("building") in SACRED or t_.get("amenity") == "place_of_worship"):
        continue
    h30 = float(np.percentile(topi[f["rr"], f["cc"]], 30))
    if h30 < 9:
        continue
    rows = [(3, int(min(7, h30 - 5)))] + ([(int(h30) - 7, 4)] if h30 >= 20 else [])
    n_cw += landmarks.edge_windows(vol, g, f["geom"], _win, rows, 4.5)
note("church windows:", n_cw)

# ---------------------------------------------------------------- curated landmark details
landmarks.apply_zones(vol, g, feats, pal, bmask, note)
floods = landmarks.apply_stripes(vol, g, bmask, pal, osm, cells_of, note)
leaf_ids = {i for i, e in enumerate(pal.entries) if e[3] in (M_LEAF,)}
# where a hanging building piece may carry its walls down (1: inside a building outline) or needs posts (2: roof-only)
bkind = np.zeros((D, W), np.uint8)
ROOFY = {"roof", "carport", "canopy", "shelter"}
for f in feats:  # walls may come down only inside an outline that itself stands on the ground (not a part on stilts,
    # not a raised passage: a connector 4-9 m over the street got filled solid to the ground)
    if not f["part"] and (f["minh"] or 0) < 2.5 and f["tags"].get("building") not in ROOFY:
        bkind[f["rr"], f["cc"]] = 1
for f in feats:
    if f["tags"].get("building") in ROOFY or f["tags"].get("building:part") == "roof":
        bkind[f["rr"], f["cc"]] = 2
from shapely.geometry import Polygon as _Poly
landmarks.PIERS = [_Poly(l.coords) for oid, t, l in osm.lines if t.get("bridge:support") and l.is_closed and len(l.coords) >= 4]
import underpass
underpass.build(vol, g, pal, C, osm, note)
carriageway_sanity(lambda r, c: vol[g[r, c] - 1, r, c], "after the underpasses")
if os.environ.get("LMCACHE"):  # the volume before the curated landmark details, for scripts/patch.py
    import pickle
    Path("data/cache").mkdir(parents=True, exist_ok=True)
    np.save("data/cache/pre_vol.npy", vol)
    pickle.dump(dict(g=g, feats=feats, deck=landmarks.DECK, bkind=bkind, trunk=C["trunk"], pole=C["pole"],
                     trunk_ok=trunk_ok_db, piers=landmarks.PIERS),
                open("data/cache/pre_state.pkl", "wb"))
labels, views = landmarks.details(vol, g, top, topi, bmask, feats, pal, C, osm, cells_of, note, leaf_ids)

import labels as labels_mod
labels = labels_mod.assemble(labels, osm, lambda r, c: max(int(g[r, c] + (topi[r, c] if bmask[r, c] else 0)),
                                                            int(landmarks.MON_TOP[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max())))
labels_mod.radii(labels, g, g + np.where(bmask, topi, 0))
views.update(landmarks.landmark_views(labels, g))

# ---------------------------------------------------------------- floating debris
import debris
debris.drop_debris(vol, g, np.array([i for i, e in enumerate(pal.entries) if e[3] == M_LEAF] + [C["trunk"]], dtype=vol.dtype), note)

# ---------------------------------------------------------------- export
Hm = int(np.nonzero(vol.reshape(H, -1).any(axis=1))[0].max()) + 1
vol = vol[:Hm]
note("final height", Hm, "palette", len(pal.entries))
# the ground as the tiles show it before the foliage (grass as bare earth), for terrain.py: the first moment of loading
_ids = vol[g - 1, np.arange(D)[:, None], np.arange(W)[None, :]]
_lut = np.array([e[:3] for e in pal.entries], np.uint8)
_lut[[i for i, e in enumerate(pal.entries) if e[3] == M_GRASS]] = _lut[C["bare"]]
np.savez_compressed(AREA / "ground.npz", g=g.astype(np.int16), rgb=_lut[_ids],
                    b=np.where(bmask, topi, 0).astype(np.int16))  # building height above ground (photo-pose tools)
import tiles
EXPORT_IDS = dict(face_ids={i for i, e in enumerate(pal.entries) if e[3] == M_CLOCK},
                         fol_ids={i for i, e in enumerate(pal.entries) if e[3] == M_LEAF} | {C["trunk"]},
                         grass_ids={i for i, e in enumerate(pal.entries) if e[3] == M_GRASS}, bare_id=C["bare"])
# nothing hangs in the air: crowns get trunks, building pieces walls or posts, specks go (debris.support_floating)
debris.support_floating(vol, g, pal, bkind, note, C["trunk"], C["pole"], trunk_ok=trunk_ok_db)
if os.environ.get("FINALDUMP"):  # the finished volume, for whole-city checks (scripts/floating.py)
    np.save("data/cache/final_vol.npy", vol)
    np.save("data/cache/final_g.npy", g)
tile_info = tiles.export(vol, g, OUT / "tiles", note, **EXPORT_IDS)
if os.environ.get("LMCACHE"):
    pickle.dump(dict(EXPORT_IDS, debris_keep=[i for i, e in enumerate(pal.entries) if e[3] == M_LEAF] + [C["trunk"]]),
                open("data/cache/export_ids.pkl", "wb"))
# tram routes for the animated trams: merged open-air tram tracks, sampled every metre with ground z
from shapely.ops import linemerge
tram_lines = linemerge([l for oid, t, l in osm.lines_with("railway", ("tram",)) if not tunnelish(t)])
tram_lines = list(getattr(tram_lines, "geoms", [tram_lines]))
trams = []
for ln in sorted(tram_lines, key=lambda l: -l.length):
    if ln.length < 180:
        continue
    pts = [ln.interpolate(d) for d in np.arange(0, ln.length, 2.0)]
    path = []
    for p in pts:
        c, r = min(max(int(p.x), 0), W - 1), min(max(int(p.y), 0), D - 1)
        path.append([round(p.x, 1), round(p.y, 1), int(g[r, c])])
    trams.append(path)
note("tram paths:", len(trams), "total km", round(sum(len(p) for p in trams) * 2 / 1000, 2))
meta = dict(W=W, D=D, H=Hm, base=BASE, voxel=VOXEL_SIZE, tiles=tile_info, center=[CX, CY], theta_deg=math.degrees(THETA),
            crs=CRS, lonlat=[round(float(v), 6) for v in grid_to_lonlat(W / 2, D / 2)], trams=trams, jets=jets,
            palette=[list(e) for e in pal.entries], lamps=lamps, floods=floods, labels=labels, views=views,
            sources=dict(osm=osm.timestamp, lidar=json.loads(str(z["info"]))["description"] if "info" in z else "",
                         ortho="PNOA most recent orthophoto (IGN), 0.25 m", buildings="Catastro INSPIRE + OSM",
                         trees="Ayuntamiento de Madrid tree inventory"))
json.dump(meta, open(OUT / "meta.json", "w"))
import traffic
# QA aid: drivable-surface mask (1 = carriageway/road area, 2 = tram bed) for web/tools/qa.mjs
qa = np.zeros((D, W), np.uint8)
qa[is_road] = 1
qa[np.isin(gcol, [C["trambed"], C["rail"]])] = 2
with gzip.GzipFile(OUT / "qa_roadmask.bin.gz", "wb", compresslevel=9, mtime=0) as fh:  # mostly zeros: 12 MB -> ~0.3 MB
    fh.write(qa.tobytes())
# vehicles on a bridge way take the deck under them, or the nearest deck cell within 2 m (a way's centreline can run
# just off the deck)
_dd, (_ir, _ic) = ndimage.distance_transform_edt(~deck, return_indices=True)
deck_near = np.where(_dd <= 2, deck_h[_ir, _ic], 0).astype(np.float32)
# off the deck mask, on a bridge way (a viaduct whose arches are OSM buildings, a deck end): the top of what the
# voxels hold there -- lamps, poles and leaves aside -- within the LiDAR's reach
_skip = np.zeros(len(pal.entries) + 64, bool)
_skip[[i for i, e in enumerate(pal.entries) if e[3] in (M_LEAF, M_LAMP, M_CAR)] + [C["trunk"], C["pole"], C["fence"]]] = True
_rb, _cb = np.nonzero((deck_col > 0) & (_dd > 2))
_lim = g[_rb, _cb] + np.clip(np.round(nd_mean[_rb, _cb]), 0, 40).astype(int) + 3
_top = g[_rb, _cb].copy()
for _z in range(int(g.min()), int(_lim.max()) + 1 if len(_lim) else 0):  # no bridge-way cells off a deck: nothing to do
    _m = (_z >= g[_rb, _cb]) & (_z < _lim)
    _v = vol[_z, _rb[_m], _cb[_m]]
    _top[np.nonzero(_m)[0][(_v != 0) & ~_skip[_v]]] = _z + 1
deck_near[_rb, _cb] = _top - g[_rb, _cb]
_solid = ~_skip
_solid[0] = False
traffic.OPEN_CUT = OPEN_CUT
_tin = dict(g=g, nd_mean=deck_near, surf=qa, water=(gcol == C["water"]) & (_dd <= 2), solid=_solid,
            roofs=unary_union([b for b, *_ in GARDEN_ROOFS.values()]), paths=roofgardens.PATHS)
if os.environ.get("LMCACHE"):  # what traffic.py takes, to rebuild traffic.json alone (uv run python scripts/traffic.py)
    pickle.dump(dict(_tin, open_cut=OPEN_CUT, walk=underpass.WALK, ids=underpass.IDS), open("data/cache/traffic_in.pkl", "wb"))
json.dump(traffic.build(note=note, vol=vol, **_tin), open(OUT / "traffic.json", "w"), separators=(",", ":"))
json.dump(report, open(DBG / "report.json", "w"), indent=1, ensure_ascii=False)

# debug: top-down colour of highest voxel
topz = Hm - 1 - np.argmax(vol[::-1] != 0, axis=0)
topv = np.take_along_axis(vol, topz[None], 0)[0]
palarr = np.array([e[:3] for e in pal.entries], np.uint8)
from PIL import Image
shade = np.clip(0.55 + topz / 120, 0, 1.2)[..., None]
Image.fromarray(np.clip(palarr[topv] * shade, 0, 255).astype(np.uint8)).save(DBG / "topdown.png")
Image.fromarray(palarr[gcol]).save(DBG / "ground.png")
print("done")
