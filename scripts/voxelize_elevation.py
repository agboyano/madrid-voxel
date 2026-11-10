"""Phase 2 test: voxels from the elevation rasters alone (ground and surface), generic palette.

Reads the common elevation format (prep_lidar.py) and fills each 1-voxel column from the ground up to the surface,
coloured by the cloud's class: buildings and other structures solid to the roof, vegetation as a crown hanging
below the surface, bridges as a deck. No OSM, Catastro, trees or orthophoto: this checks what the LiDAR heights alone
give before the full fusion (Phase 3).

Writes the minimum the viewer needs into web/public/data/ (tiles through the unchanged tiles.py, meta.json,
terrain.bin, zones.bin/json with no buildings and one block per tile) and removes the Warsaw data files that would
not match the new grid. climate.json stays until Phase 4.

usage: PYTHONPATH=scripts uv run python scripts/voxelize_elevation.py
"""
import gzip
import json
import math

import numpy as np
from scipy import ndimage

import tiles
from aoi import CACHE, CRS, CX, CY, D, THETA, VOXEL_SIZE, W, WEB_DATA, lonlat_to_grid
from config import ELEVATION
from prep import regrid
from prep_lidar import GROUPS, UNCLASSIFIED

# material ids, as in web/src/voxelMaterial.ts
M_SOLID, M_LEAF, M_SOIL, M_ROOF, M_CONCRETE = 0, 3, 10, 12, 13
PALETTE = [(0, 0, 0, 0),  # 0: empty
           (156, 146, 132, M_SOLID),  # 1: ground (paving)
           (214, 200, 178, M_SOLID),  # 2: wall
           (178, 92, 70, M_ROOF),  # 3: roof
           (88, 132, 64, M_LEAF),  # 4: leaves
           (168, 168, 160, M_CONCRETE),  # 5: bridge deck
           (190, 186, 180, M_SOLID),  # 6: other structure (unclassified)
           (120, 104, 86, M_SOIL)]  # 7: soil under the ground surface
GROUND, WALL, ROOF, LEAF, DECK, OTHER, SOIL = range(1, 8)
MIN_HEIGHT = 1.5  # metres above ground for a cell to hold anything but ground
CROWN = 0.6  # share of a tree's height that is crown
DECK_THICK = 1.5  # metres
WARSAW_FILES = ("flood.bin", "flood.json", "foliage.bin", "phenology.json", "windows.bin", "windows.json",
                "traffic.json", "places.json", "qa_roadmask.bin.gz", "trees.json")


def note(*a):
    print(*a, flush=True)


def fill_surface(dsm, ground):
    """Empty DSM cells: the median of their valid 3 x 3 neighbours (twice, for 2-cell gaps), then the ground."""
    a = dsm.copy()
    for _ in range(2):
        hole = np.isnan(a)
        if not hole.any():
            break
        med = ndimage.generic_filter(a, np.nanmedian, size=3, mode="nearest")
        a = np.where(hole, med, a)
    return np.where(np.isnan(a), ground, a)


def main():
    z = np.load(CACHE / "work" / f"elevation_{ELEVATION['source']}.npz")
    info = json.loads(str(z["info"]))
    res = info["res"]
    on_grid = lambda a: regrid(a, res, VOXEL_SIZE)  # noqa: E731  # raster cells -> voxel columns
    dtm, dsm, cls = on_grid(z["dtm"]), on_grid(z["dsm"]), on_grid(z["cls"])
    empty = np.isnan(dsm)
    surf = fill_surface(dsm, dtm)

    base = math.floor(dtm.min()) - 3
    g = np.round((dtm - base) / VOXEL_SIZE).astype(np.int32)  # ground fills z in [0, g)
    top = np.maximum(np.round((surf - base) / VOXEL_SIZE).astype(np.int32), g)
    tall = (surf - dtm) >= MIN_HEIGHT
    is_b = np.isin(cls, GROUPS["building"]) & tall
    is_v = np.isin(cls, GROUPS["vegetation"]) & tall
    is_d = np.isin(cls, GROUPS["bridge"]) & tall
    is_o = (cls == UNCLASSIFIED) & tall
    H = int(top.max()) + 2

    vol = np.zeros((H, D, W), np.uint16)
    zz = np.arange(H)[:, None, None]
    vol[zz < g - 1] = SOIL
    vol[(zz == g - 1)] = GROUND
    above = (zz >= g) & (zz < top)
    vol[above & is_b] = WALL
    vol[above & is_o] = OTHER
    vol[(zz == top - 1) & is_b] = ROOF
    crown0 = np.maximum(g, top - np.maximum(2, np.round((top - g) * CROWN)).astype(np.int32))
    vol[(zz >= crown0) & (zz < top) & is_v] = LEAF
    deck0 = np.maximum(g, top - round(DECK_THICK / VOXEL_SIZE))
    vol[(zz >= deck0) & (zz < top) & is_d] = DECK
    del zz

    out = WEB_DATA
    # overwrite in place and drop only stale node files: deleting the folder makes a running Vite dev server stop
    # serving the new files (it answers index.html)
    old_nodes = set((out / "tiles").rglob("*.bin"))
    for f in WARSAW_FILES:
        (out / f).unlink(missing_ok=True)
    tile_info = tiles.export(vol, g, out / "tiles", note, fol_ids={LEAF})
    new_nodes = {out / "tiles" / str(l["s"]) / f"{tx}_{ty}.bin" for l in tile_info["levels"]
                 for tx in range(l["nx"]) for ty in range(l["ny"])}
    new_nodes |= {p.parent.parent / "1f" / p.name for p in new_nodes if p.parent.name == "1"}
    for p in old_nodes - new_nodes:
        p.unlink()

    # terrain.bin, as scripts/terrain.py: heights every 4 m in decimetres above base, then ground colours every 2 m
    step = round(4 / VOXEL_SIZE)
    h = np.round(ndimage.uniform_filter(g.astype(np.float32), step)[::step, ::step] * VOXEL_SIZE * 10).astype(np.uint16)
    rgb = np.array([p[:3] for p in PALETTE], np.uint8)[np.full((D, W), GROUND)][1::2, 1::2]
    with gzip.GzipFile(out / "terrain.bin", "wb", compresslevel=9, mtime=0) as fh:
        fh.write(h.tobytes() + np.ascontiguousarray(rgb).tobytes())

    # zones: one block per 128-cell tile, no buildings (nothing waits to be shown whole)
    T = tiles.N
    rr, cc = np.mgrid[0:D, 0:W]
    blk = ((rr // T) * math.ceil(W / T) + cc // T + 1).astype(np.uint16)
    blocks = []
    for b in range(1, int(blk.max()) + 1):
        r, c = np.nonzero(blk == b)
        blocks.append([round(float(c.mean()), 1), round(float(r.mean()), 1), int(len(r)),
                       int(c.min()), int(r.min()), int(c.max()) + 1, int(r.max()) + 1])
    with gzip.GzipFile(out / "zones.bin", "wb", compresslevel=9, mtime=0) as fh:
        fh.write(blk.tobytes() + np.zeros((D, W), np.uint16).tobytes())
    json.dump({"blocks": blocks, "buildings": []}, open(out / "zones.json", "w"))

    # views for the screenshots: top-down, oblique over Sol, street level on Calle Mayor looking east to Sol
    si, sj = W / 2, D / 2  # Puerta del Sol: the AOI centre is the centre of the OSM square
    mi, mj = (float(v) for v in lonlat_to_grid(-3.704580, 40.416602))  # Calle Mayor centreline (OSM), 125 m west of Sol
    gz = lambda i, j: float(g[int(j), int(i)])  # noqa: E731
    views = {
        "overview": dict(label="Overview", target=[W / 2, gz(si, sj), D / 2], pos=[W / 2 + 330, 380, D / 2 + 420]),
        "top": dict(label="Top-down", target=[W / 2, gz(si, sj), D / 2], pos=[W / 2, 900, D / 2 + 1]),
        "sol": dict(label="Puerta del Sol", target=[si, gz(si, sj) + 8, sj], pos=[si + 150, gz(si, sj) + 110, sj + 170]),
        # at street level the target sits just below the eye, as in Warsaw's views: OrbitControls' tilt limit
        # lifts a camera that looks up
        "street": dict(label="Calle Mayor", target=[si, gz(mi, mj) + 1.5, sj], pos=[mi, gz(mi, mj) + 2.5, mj]),
    }
    meta = dict(W=W, D=D, H=int(H), base=base, voxel=VOXEL_SIZE, tiles=tile_info, center=[CX, CY],
                theta_deg=math.degrees(THETA), crs=CRS, trams=[], jets=[],
                palette=[list(p) for p in PALETTE], lamps=[], floods=[], labels=[], views=views,
                sources=dict(osm="", lidar=info["description"], ortho=""))
    json.dump(meta, open(out / "meta.json", "w"))
    note(f"columns: building {is_b.mean() * 100:.1f} %, vegetation {is_v.mean() * 100:.1f} %, bridge "
         f"{is_d.mean() * 100:.1f} %, other {is_o.mean() * 100:.1f} %; surface cells filled {empty.mean() * 100:.2f} %; "
         f"H {H}, base {base} m")


if __name__ == "__main__":
    main()
