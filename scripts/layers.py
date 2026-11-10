"""2D layers of the city, one value per cell of the grid (D rows x W columns, see aoi.py), following the structure
of dtla-voxel's layers.py (https://github.com/sigman78/dtla-voxel, commit 90bc1a6c, MIT, see LICENSE-dtla-voxel):
the fusion of the LiDAR rasters (prep.py), the orthophoto, OSM, Catastro and the tree inventory into ground, buildings
and roofs, before any voxel exists. The rules are Warsaw's (warsaw-vibe-voxel), adapted to Madrid's sources.

build() returns the layers by name; voxelize.py fills the 3D volume from them:
  ground   g (ground level, voxels), gcol (ground palette id), is_road, parking_mask, OPEN_CUT, splash_pads, rails
  rasters  dsm, dtm, dsm_mean, nd_max, nd_mean (heights over the DTM), cellcol, exg, lum, rgbsum (ortho), cls and
           LIDAR_VEG, LIDAR_BRIDGE (point classes)
  buildings feats (OSM + Catastro features with their styles), render, bmask, top / topi (roof height over ground),
           boti (underside), cell_maxh, over (roofs clipped under tree crowns), CORE, GARDEN_ROOFS
  bridges  bridge_shapes, bridge_lines, bridge_rails, bridge_roads (decks are drawn from these in voxelize.py)
  scalars  BASE (metres a.s.l. of voxel 0), H (volume height), MAX_TREE, SACRED; osm, z (the raw inputs)
"""

import json
import math
from pathlib import Path

import numpy as np
import rasterio.features
from affine import Affine
from scipy import ndimage
from shapely.geometry import Point
from shapely.ops import substring
from shapely.strtree import STRtree

from aoi import AREA, D, W
from osm import OSM
import landmarks
import roofgardens

from buildlog import note
from palette import (AUSTRIAS_WALLS, C, M_GLASS, M_ROOF, M_WALL, ROOF_MATERIALS, ROOF_SHADES, WALL_BRICK, WALL_DEFAULTS,
                     WALL_GRANITE, hex_rgb, pal, parse_colour, parse_len, soften, stable_hash)


def ground_walls(dtm, dtm_s):
    """The terrain smoothed over 3 m, except at its walls: a box filter made every retaining wall (an underpass, a
    trench, a ramp's sides, a building pit, a deck's abutment) a 3 m ramp, and rounding cut the ramp into ragged 1-2 m
    stairs that zigzagged along the wall -- rubble along every sunken road. Where the terrain drops 3 m or more within
    a cell's neighbours, the cell takes the upper or the lower level around it (5 x 5, of the 3 x 3 median): the upper
    where the terrain smoothed over ~3 m stands above the middle of the two -- one clean contour along the wall (each
    cell deciding on its own sample flickered between the levels along a diagonal wall). Gentle slopes (embankments,
    the escarpment) stay smooth."""
    med = ndimage.median_filter(dtm, 3)
    lo, hi = ndimage.minimum_filter(med, 5), ndimage.maximum_filter(med, 5)
    wall = (ndimage.maximum_filter(dtm, 3) - ndimage.minimum_filter(dtm, 3) >= 3) & (hi - lo >= 3)
    note("ground: wall cells snapped to their level:", int(wall.sum()))
    return np.where(wall, np.where(ndimage.gaussian_filter(dtm, 1.5) >= (lo + hi) / 2, hi, lo), dtm_s)


def wall_clean(dsm):
    """The DSM is interpolated across vertical walls: a sample on a tower's edge reads 69, 95, 115 m between a 150 m
    roof and a 21 m podium (Rondo 1). Taken as the cell's max, each became a 1 m column of partial height glued to
    the facade, ending mid-air (dark streaks down the towers). A sample on a step of 10 m or more (7x7), 3 m or more
    from both levels around it and steep goes to the nearer level."""
    # the two levels from 3.5 m around: a wall the DSM ramps across in 3-4 samples (Górnośląska 3: 12, 25, 36, 43 m
    # between a 4 m podium and a 50 m roof) snapped sample by sample to its ramp neighbours stayed a ramp
    lo = ndimage.minimum_filter(dsm, 7)
    hi = ndimage.maximum_filter(dsm, 7)
    mixed = (hi - lo >= 10) & (dsm - lo >= 3) & (hi - dsm >= 3)
    # and steep: 3 m or more to a 4-neighbour (6 m per metre; a pitched roof rises under 2) -- a ramp along a straight
    # wall repeats row after row, so similar neighbours along the wall do not make it a surface
    pad = np.pad(dsm, 1, mode="edge")
    steep = np.zeros(dsm.shape, bool)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        steep |= np.abs(pad[1 + dr:1 + dr + dsm.shape[0], 1 + dc:1 + dc + dsm.shape[1]] - dsm) >= 3
    mixed &= steep
    # below a broad upper level only: spires, lanterns and stepped crowns (All Saints' towers, Hotel Warszawa's crown)
    # were cut down to flat boxes; a wall edge has a roof beside it
    # (the upper level must survive a 6.5 m opening: a roof does, a spire's tip or a tower's stepped crown does not)
    mixed &= ndimage.maximum_filter(ndimage.grey_opening(dsm, size=(13, 13)), 7) >= hi - 3
    up = mixed & (dsm - lo >= hi - dsm)
    # a cell (2x2 samples) takes its highest: one sample snapped up pushed the wall out a cell, a sawtooth along every
    # wall top (Bagno 5). Up only where at least two of the cell's samples go up
    n_up = up.reshape(dsm.shape[0] // 2, 2, dsm.shape[1] // 2, 2).sum((1, 3))
    up &= np.repeat(np.repeat(n_up >= 2, 2, 0), 2, 1)
    out = np.where(mixed, np.where(up, hi, lo), dsm)
    note("DSM wall-edge samples snapped to roof or street:", int(mixed.sum()))
    return out


def cells_of(geom, all_touched=False):
    if geom.is_empty:
        return np.zeros(0, int), np.zeros(0, int)
    minx, miny, maxx, maxy = geom.bounds
    c0, r0 = max(int(math.floor(minx)), 0), max(int(math.floor(miny)), 0)
    c1, r1 = min(int(math.ceil(maxx)), W), min(int(math.ceil(maxy)), D)
    if c0 >= c1 or r0 >= r1:
        return np.zeros(0, int), np.zeros(0, int)
    m = rasterio.features.rasterize([(geom, 1)], out_shape=(r1 - r0, c1 - c0),
                                    transform=Affine.translation(c0, r0), all_touched=all_touched, dtype=np.uint8)
    rr, cc = np.nonzero(m)
    if len(rr) == 0 and not all_touched:
        return cells_of(geom, True)
    return rr + r0, cc + c0


def burn(target, shapes, all_touched=False):
    shapes = [(s, int(v)) for s, v in shapes if s is not None and not s.is_empty]
    if not shapes:
        return
    m = rasterio.features.rasterize(shapes, out_shape=(D, W), transform=Affine.identity(), fill=0,
                                    all_touched=all_touched, dtype=np.uint16)
    target[m > 0] = m[m > 0]


def tunnelish(t):
    return t.get("tunnel") in ("yes", "building_passage", "culvert") or parse_len(t.get("layer", 0)) < 0 \
        or t.get("covered") == "yes" or t.get("indoor") == "yes" or t.get("location") == "underground" \
        or parse_len(t.get("level", "0").split(";")[0] or 0) and parse_len(t.get("level", "0").split(";")[0]) < 0


def on_bridge(t):
    return t.get("bridge") not in (None, "no") or t.get("man_made") == "bridge"


def tag(f, k):
    v = f["tags"].get(k)
    if v is None and f.get("parent") is not None:
        v = f["parent"]["tags"].get(k)
    return v


def build():
    """Every 2D layer of the fusion, by name."""

    # ---------------------------------------------------------------- rasters
    z = np.load(AREA / "prep.npz")
    dsm, dtm, orto = z["dsm"], z["dtm"], z["orto"]
    # the point cloud's class per cell (prep.py), where the source has one: 0 everywhere otherwise
    cls = z["cls"] if "cls" in z else np.zeros(dtm.shape, np.uint8)
    LIDAR_VEG = np.isin(cls, (3, 4, 5))
    LIDAR_BRIDGE = cls == 17
    d4 = dsm.reshape(D, 2, W, 2)
    dsm_max = d4.max((1, 3))
    dsm_mean = d4.mean((1, 3))
    dtm_s = ndimage.uniform_filter(dtm, 3)
    SLAB = 3
    BASE = math.floor(dtm.min()) - SLAB
    MAX_TREE = 40  # metres: the tallest crowns in central Madrid (Retiro's plane trees and cedars) stay under it


    g = np.round(ground_walls(dtm, dtm_s) - BASE).astype(np.int32)  # ground occupies z in [0, g)
    # rounding a smooth slope leaves single cells 1 m under all eight neighbours (38.49 to 38, round 38.51 to 39): a dark
    # hole in a pavement or a lawn every few metres; such a cell takes their level
    _gpit = ndimage.minimum_filter(g, footprint=np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])) - g == 1
    g[_gpit] += 1
    note("ground: rounding pits lifted:", int(_gpit.sum()))
    nd_max = dsm_max - dtm
    nd_mean = dsm_mean - dtm


    nd_max_b = wall_clean(dsm).reshape(D, 2, W, 2).max((1, 3)) - dtm  # building tops
    cellcol = np.median(orto.reshape(D, 5, W, 5, 3), axis=(1, 3)).astype(np.float32)
    rgbsum = cellcol.sum(-1) + 1
    exg = (2 * cellcol[..., 1] - cellcol[..., 0] - cellcol[..., 2]) / rgbsum
    lum = cellcol @ np.array([0.299, 0.587, 0.114], np.float32)
    note(f"ground: BASE={BASE} m a.s.l., g range {g.min()}..{g.max()}")

    osm = OSM()
    note("OSM timestamp", osm.timestamp, "areas", len(osm.areas), "lines", len(osm.lines), "nodes", len(osm.nodes))


    # the street over a road tunnel: the LiDAR's ground sagged 3 m over the trasa under Marszałkowska, and the trams and
    # cars on it dipped into the cut. A short tunnelled carriageway (under 150 m) crossed by surface ways: the street level
    # is where those ways stand 4 m clear of it on either side; its footprint lower than that by 1.5-6 m is lifted to it
    _surf = [l_ for _, t_, l_ in osm.lines if (t_.get("highway") or t_.get("railway") == "tram") and t_.get("tunnel") is None
             and parse_len(t_.get("layer", 0)) >= 0]
    _stree = STRtree(_surf)
    n_tun = 0
    _tun = [l_.buffer((parse_len(t_.get("lanes")) or 2) * 1.6 + 2, cap_style="flat") for _, t_, l_ in osm.lines
            if t_.get("tunnel") == "yes" and l_.length <= 150 and (t_.get("highway") or "").replace("_link", "") in
            ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential")]
    # a dual carriageway's two tunnels and the strip between them are one crossing
    from shapely.ops import unary_union as _uu
    _tun = _uu(_tun).buffer(6).buffer(-6) if _tun else None
    for foot in getattr(_tun, "geoms", [_tun] if _tun else []):
        levels = []
        for k in _stree.query(foot):
            sl = _surf[k]
            x_ = sl.intersection(foot)
            if x_.is_empty or x_.length < 3:
                continue
            pr = [sl.project(Point(c_)) for g_ in getattr(x_, "geoms", [x_]) for c_ in g_.coords]
            for q in (sl.interpolate(max(min(pr) - 4, 0)), sl.interpolate(min(max(pr) + 4, sl.length))):
                if 0 <= q.y < D and 0 <= q.x < W and not foot.contains(q):
                    levels.append(int(g[int(q.y), int(q.x)]))
        if len(levels) < 2 or np.percentile(levels, 80) - np.percentile(levels, 20) > 2:
            continue
        street = int(np.median(levels))
        rr_, cc_ = cells_of(foot)
        low = (street - g[rr_, cc_] >= 1.5) & (street - g[rr_, cc_] <= 6)
        g[rr_[low], cc_[low]] = street
        n_tun += int(low.sum())
    note("ground over short road tunnels lifted to the street crossing them:", n_tun)
    # a carriageway or a railway tagged one layer down but with no tunnel is an open cut (Trasa Łazienkowska east and west
    # of Marszałkowska, the cross-city line's cutting): it had been left out as if underground. Where the ground along it
    # stands 2 m or more under the ground 6-24 m to its sides (a dual carriageway's cut is 30 m wide), it is drawn and driven, its layer set to 0
    OPEN_CUT = set()
    for oid, t, line in osm.lines:
        if not ((t.get("highway") or "").replace("_link", "") in ("motorway", "trunk", "primary", "secondary", "tertiary",
                                                                    "unclassified", "residential") or t.get("railway") == "rail"):
            continue
        if parse_len(t.get("layer", 0)) >= 0 or t.get("tunnel") not in (None, "no") or t.get("covered") not in (None, "no") \
                or t.get("location") == "underground" or t.get("indoor") == "yes" or line.length < 10:
            continue
        rr_, cc_ = cells_of(line.buffer(1.5, cap_style="flat"))
        sr, sc = cells_of(line.buffer(24, cap_style="flat").difference(line.buffer(6, cap_style="flat")))
        if len(rr_) and len(sr) and np.percentile(g[sr, sc], 85) - np.median(g[rr_, cc_]) >= 2:
            OPEN_CUT.add(oid)
            t["layer"] = "0"
    note("open cuts (layer -1, no tunnel) drawn:", len(OPEN_CUT))

    # ---------------------------------------------------------------- ground classes
    gcol = np.full((D, W), C["paving"], np.uint16)
    is_road = np.zeros((D, W), bool)
    LANDUSE = {"grass": "grass", "meadow": "grass", "village_green": "grass", "flowerbed": "flower", "construction": "dirt",
               "railway": "ballast", "brownfield": "dirt", "greenfield": "grass"}
    LEISURE = {"park": "grass2", "garden": "garden", "pitch": "grass", "playground": "gravel", "dog_park": "gravel"}
    SURF = {"asphalt": "asphalt", "paving_stones": "paving", "sett": "sett", "cobblestone": "sett", "concrete": "concrete",
            "concrete:plates": "concrete", "gravel": "gravel", "fine_gravel": "gravel", "compacted": "gravel",
            "grass": "grass", "ground": "dirt", "dirt": "dirt", "unhewn_cobblestone": "sett", "paved": "paving",
            "wood": "track", "metal": "rail", "rubber": "cycle", "tartan": "cycle", "artificial_turf": "grass"}


    containers, soft, hard = [], [], []
    for oid, typ, t, geom in osm.areas:
        if tunnelish(t) or "building" in t or "building:part" in t:
            continue
        if t.get("place") == "square" or t.get("highway") == "pedestrian" or t.get("landuse") in ("commercial", "retail", "residential"):
            containers.append((geom, C[SURF.get(t.get("surface"), "paving")]))
        if t.get("landuse") in LANDUSE:
            key = LANDUSE[t["landuse"]]
            if key == "grass":  # a lawn the 2025 ortho sees paved over (a pavement widened along Jana Pawła II) is paving
                rr_, cc_ = cells_of(geom)
                if len(rr_) >= 30 and np.median(exg[rr_, cc_]) < 0 and np.median(lum[rr_, cc_]) > 120:
                    key = "paving2"
            soft.append((geom, C[key]))
        if t.get("leisure") in ("pitch", "track"):  # its colour as the ortho sees it: red tartan, green turf or a grey court; the
            # surface tags disagree with it (a green turf pitch tagged tartan by Zamoyski's school, red courts untagged)
            inner = geom.buffer(-1) if geom.area > 60 else geom
            rr_, cc_ = cells_of(geom if inner.is_empty else inner)
            if len(rr_) >= 10:
                r_, g_, b_ = np.median(cellcol[rr_, cc_], axis=0)
                key = "tartan" if r_ > g_ + 18 and r_ > b_ + 25 else "court" if b_ > r_ + 25 else \
                    "grass" if (2 * g_ - r_ - b_) / (r_ + g_ + b_ + 1) > 0.03 else "paving" if r_ + g_ + b_ > 560 else "asphalt_l"  # (white: an air hall)
                soft.append((geom, C[key]))
                continue
        if t.get("leisure") in LEISURE:
            soft.append((geom, C[SURF.get(t.get("surface"), LEISURE[t["leisure"]])]))
        if t.get("natural") in ("scrub", "heath", "grassland"):
            soft.append((geom, C["scrub" if t["natural"] == "scrub" else "grass"]))
        if t.get("natural") in ("wood",):
            soft.append((geom, C["garden"]))
        if "construction:leisure" in t or "construction:landuse" in t:
            soft.append((geom, C["fresh"]))
        if t.get("amenity") == "parking" and t.get("parking") not in ("underground", "multi-storey", "rooftop"):
            key = SURF.get(t.get("surface"), "parking")
            if "surface" not in t:  # an untagged car park the 2025 ortho sees pale is paved (Plac Centralny's south end,
                # mapped as 9000 m2 of parking, is the new square's paving with a few cars)
                rr_, cc_ = cells_of(geom)
                if len(rr_) >= 20 and np.percentile(lum[rr_, cc_], 60) > 150:
                    key = "paving2"
            hard.append((geom, C[key]))
    containers.sort(key=lambda s: -s[0].area)
    soft.sort(key=lambda s: -s[0].area)
    burn(gcol, containers)
    burn(gcol, soft)
    burn(gcol, hard)
    # a lawn island inside a car park (the stadium's) is drawn over it, not under
    _hard_u = _uu([h_ for h_, _ in hard]) if hard else None
    burn(gcol, [(g_, c_) for g_, c_ in soft if c_ in (C["grass"], C["grass2"]) and _hard_u is not None and g_.area < 20000
                and _hard_u.contains(g_.representative_point())])
    # a construction site is bare earth only where the 2025 ortho sees it so (the Saxon Palace's and Twórcza Twarda's
    # fenced plots were lawn and trees then)
    _con = np.zeros((D, W), np.uint16)
    burn(_con, [(g_, 1) for _, _, t_, g_ in osm.areas if t_.get("landuse") == "construction" and not tunnelish(t_)])
    _cm = (_con > 0) & (gcol == C["dirt"])
    _cg = ndimage.median_filter(((exg > 0.04) | (lum < 70)).astype(np.uint8), 9) > 0  # (a crown's shadow on the lawn is lawn)
    _cp = ndimage.median_filter(((exg <= 0.04) & (lum >= 70) & (cellcol[..., 0] < cellcol[..., 2] + 12)).astype(np.uint8), 9) > 0
    gcol[_cm & _cg] = C["grass"]
    gcol[_cm & ~_cg & _cp] = C["paving2"]  # grey hardstanding, not earth
    parking_mask = np.zeros((D, W), np.uint16)
    burn(parking_mask, [(geom, 1) for geom, _ in hard])

    # ortho says grass where OSM is silent (cross-check, only on default paving cells, low & green)
    ortho_grass = (gcol == C["paving"]) & (exg > 0.09) & (nd_mean < 0.8)
    ortho_grass = ndimage.binary_opening(ortho_grass, iterations=1)
    gcol[ortho_grass] = C["grass"]
    note("ortho-detected grass cells (OSM silent):", int(ortho_grass.sum()))

    HW = {"motorway": 20, "trunk": 14, "primary": 12, "secondary": 10, "tertiary": 8, "unclassified": 6,
          "residential": 6, "living_street": 5, "service": 4, "pedestrian": 5, "footway": 2.5, "path": 2,
          "cycleway": 2, "steps": 2.5, "platform": 3, "bridleway": 2, "track": 3, "corridor": 0}
    ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
             "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "living_street"}


    foot_shapes, road_shapes, bridge_shapes, cycle_shapes, road_lines = [], [], [], [], []  # bridge ways are painted on the deck, not on the river below
    bridge_rails = []  # (line, colour) the rails of tracks on bridges, drawn on the deck like those on the ground
    bridge_lines = []  # (line, half width, layer) of every way on a bridge: the deck's height profile is taken along them
    bridge_roads = []  # (line, width) of carriageways on bridges, for the inferred deck lamps
    crossing_roads = []  # (id, tags, centreline, width) of surface carriageways, for road_markings.py
    _paved = [(g_, t_["surface"]) for _, _, t_, g_ in osm.areas
              if t_.get("surface") in SURF and ("area:highway" in t_ or (t_.get("highway") and t_.get("area") == "yes"))]
    _ptree = STRtree([g_ for g_, _ in _paved])
    n_inherit = 0


    def area_surface(line):
        """the surface of the paved square or courtyard a road without its own runs through (the palace's driveway)"""
        for i in _ptree.query(line):
            g_, s_ = _paved[i]
            if line.intersection(g_).length > 0.6 * line.length:
                return s_
        return None


    for oid, t, line in osm.lines:
        hw = t.get("highway")
        if hw == "construction":
            hw = t.get("construction")
        if not hw or tunnelish(t) or hw in ("corridor", "elevator", "proposed"):
            continue
        base = hw.replace("_link", "")
        w = parse_len(t.get("width")) or (parse_len(t.get("lanes")) * 3.1 if t.get("lanes") and base in HW and base in ROADS else None) or HW.get(base, 0)
        if t.get("footway") == "sidewalk":
            w = max(w, 3)
        if base == "service" and t.get("service") in ("parking_aisle", "driveway", "alley"):
            w = 3.5
        if w <= 0:
            continue
        poly = line.buffer(w / 2, cap_style="flat" if base in ROADS else "round")
        if on_bridge(t):
            key = SURF.get(t.get("surface"), "asphalt") if (hw in ROADS or base in ROADS) else ("cycle" if hw == "cycleway" else SURF.get(t.get("surface"), "paving"))
            bridge_shapes.append((poly, C[key], int(parse_len(t.get("layer")) or 1)))
            bridge_lines.append((line, w / 2, int(parse_len(t.get("layer")) or 1), C[key]))
            if (hw in ROADS or base in ROADS) and line.length > 60 and t.get("motor_vehicle") not in ("no", "private"):
                bridge_roads.append((line, w))  # (not the Karowa footbridge, a living_street for service vans only)
            continue
        if hw in ROADS or base in ROADS:
            _s = t.get("surface") or (area_surface(line) if base in ("service", "living_street") else None)
            n_inherit += _s is not None and "surface" not in t
            # a carriageway of paving stones in the sidewalks' colour vanished into them (Plac Krasińskich, Krakowskie
            # Przedmieście): granite carriageways a darker grey
            _k = "road_paving" if SURF.get(_s) == "paving" else SURF.get(_s, "asphalt")
            if base in ("trunk", "primary", "secondary", "tertiary", "unclassified", "residential"):
                road_lines.append((oid, line, C[_k]))
            road_shapes.append((poly, C[_k]))
            crossing_roads.append((oid, t, line, w))
        elif hw == "cycleway":  # one red the whole way, whatever its stretches are tagged (asphalt, paving stones): drawn last
            cycle_shapes.append((poly, C["cycle"]))
        elif hw == "steps":
            foot_shapes.append((poly, C["steps"]))
        elif hw in ("footway", "path", "pedestrian", "platform", "track", "bridleway"):
            foot_shapes.append((poly, C[SURF.get(t.get("surface"), "paving")]))
    note(f"roads taking their square's surface: {n_inherit}")
    burn(gcol, foot_shapes + cycle_shapes)
    road_mask = np.zeros((D, W), np.uint16)
    burn(road_mask, [(s, 1) for s, _ in road_shapes])
    burn(gcol, road_shapes)

    AH = {"footway": "paving", "pedestrian": "paving", "cycleway": "cycle", "traffic_island": "kerb", "steps": "steps",
          "emergency": "asphalt_l", "yes": "paving", "platform": "platform", "busway": "asphalt", "parking": "parking",
          "junction": "asphalt", "bus_bay": "asphalt", "bus": "asphalt", "crossing": "asphalt", "tram": "asphalt", "taxi_stop": "asphalt",
          "passing_place": "asphalt", "shoulder": "asphalt", "prohibited": "asphalt_l", "parking_lane": "parking"}
    area_hw = []
    for oid, typ, t, geom in osm.areas_with("area:highway"):
        if tunnelish(t) or t.get("landuse") == "grass":  # (a lawn mapped as a pedestrian area: the castle gardens')
            continue
        v = t["area:highway"]
        if v == "yes" and t.get("junction"):  # a junction's square of carriageway (Rondo Dmowskiego's five)
            v = "junction"
        key = SURF.get(t.get("surface")) if v in ("footway", "pedestrian", "yes") else None
        key = key or AH.get(v) or ("asphalt" if v in HW or v.replace("_link", "") in ROADS else "paving")
        area_hw.append((geom, C[key]))
        if key in ("asphalt", "asphalt_l"):
            burn(road_mask, [(geom, 1)])
    area_hw.sort(key=lambda s: -s[0].area)
    burn(gcol, area_hw)
    burn(gcol, [(line.buffer(1.0, cap_style="flat"), own) for _, line, own in road_lines])  # no area drawn over a carriageway cuts it
    _cyc = np.zeros((D, W), np.uint16)  # a footway area drawn over a cycleway beside it does not cut it
    burn(_cyc, [(sh, 1) for sh, _ in cycle_shapes])
    gcol[(_cyc > 0) & (road_mask == 0)] = C["cycle"]
    is_road = road_mask > 0
    _ped = [C[k] for k in ("paving", "paving2", "kerb", "steps", "platform", "gravel", "grass", "dirt")]  # (a cycle crossing's red is road)


    def carriageway_sanity(surface, stage):
        """every carriageway's centreline in its own colour: the build stops if a road has 6 m or more of it painted as
        pavement (a junction square, an area drawn over it, a pit filled over a road ramp)"""
        bad = []
        for oid, line, own in road_lines:
            pts = [line.interpolate(d) for d in np.arange(0, line.length, 1.0)]
            rc = [(int(p.y), int(p.x)) for p in pts if 0 <= p.y < D and 0 <= p.x < W]
            off = sum(surface(r, c) in _ped and surface(r, c) != own for r, c in rc)
            if off >= 6:
                bad.append((int(off), oid, rc[0]))
        bad.sort(reverse=True)
        note(f"carriageway sanity ({stage}): {len(bad)} roads with 6+ m of their centreline painted as pavement: {bad[:8]}")
        if bad:
            raise SystemExit("carriageways painted as pavement; see the sanity line above")


    carriageway_sanity(lambda r, c: gcol[r, c], "ground colours")

    # rails & trams (only open-air)
    rail_beds, rails = [], []
    for oid, t, line in osm.lines_with("railway"):
        if tunnelish(t) or t["railway"] not in ("rail", "tram", "light_rail", "subway"):
            continue
        if t["railway"] == "subway":
            continue
        tram = t["railway"] == "tram"
        if on_bridge(t):
            bridge_shapes.append((line.buffer(1.4 if tram else 1.9, cap_style="flat"), C["trambed" if tram else "ballast"], int(parse_len(t.get("layer")) or 1)))
            bridge_lines.append((line, 1.4 if tram else 1.9, int(parse_len(t.get("layer")) or 1), C["trambed" if tram else "ballast"]))
            for off in (-0.72, 0.72):
                try:
                    bridge_rails.append((line.offset_curve(off), C["rail"]))
                except Exception:
                    pass
            continue
        rail_beds.append((line.buffer(1.4 if tram else 1.9, cap_style="flat"), C["trambed" if tram else "ballast"]))
        for off in (-0.72, 0.72):
            try:
                rails.append((line.offset_curve(off), C["rail"]))
            except Exception:
                pass
    burn(gcol, rail_beds)
    _pf = np.zeros((D, W), np.uint16)  # a platform mapped over the carriageway beside it (Wybrzeże Kościuszkowskie) stops at the road
    burn(_pf, [(geom, 1) for oid, typ, t, geom in osm.areas_with("railway", ("platform",)) if not tunnelish(t)])
    gcol[(_pf > 0) & (road_mask == 0)] = C["platform"]
    burn(gcol, rails, all_touched=True)

    # water
    # the dark disc in the garden by Kopernik is mapped as natural=water + surface=paving_stones, but it is a wooden
    # floor (zouk evenings are danced on it: web/src/sim/dance.ts): weathered dark wood
    WOOD_FLOOR = {603145360}
    water = [(geom, C["granite_d"] if t.get("fountain") == "splash_pad" else C["woodfloor"] if oid in WOOD_FLOOR
              else C["water"]) for oid, typ, t, geom in osm.areas
             if (t.get("amenity") == "fountain" or t.get("natural") == "water" or t.get("water")) and not tunnelish(t)]
    burn(gcol, water)
    # the Vistula (and ponds): one flat surface per water body -- the DTM over water steps in 1 m terraces that show as
    # lines across the river; it drops ~0.3 m across the map, so a single level is truthful
    wlab, wn = ndimage.label(gcol == C["water"])
    wsize = np.bincount(wlab.ravel())
    n_flat = 0
    for i_, sl in enumerate(ndimage.find_objects(wlab), 1):
        if sl is None or wsize[i_] < 400:
            continue
        m_ = wlab[sl] == i_
        sub = g[sl]
        sub[m_] = int(np.median(sub[m_]))
        n_flat += 1
    note("water bodies flattened:", n_flat)
    from shapely.ops import unary_union as _uu
    splash_pads = [geom for oid, typ, t, geom in osm.areas if t.get("fountain") == "splash_pad" and not tunnelish(t)]

    # crossings (road_markings.py, from dtla-voxel): bars across the carriageway, following traffic, from the OSM
    # crossing ways, else from marked crossing nodes; cycle crossings red across the road; lane markings on asphalt
    import road_markings
    asph = np.isin(gcol, [C["asphalt"], C["asphalt_l"], C["parking"], C["road_paving"], C["trambed"]])
    _xw, _xd = road_markings.build_crosswalk_mask(osm.lines, osm.nodes, crossing_roads, road_mask)
    gcol[_xw & asph] = C["mark"]
    note("zebra crossings:", _xd)
    for oid, t, line in osm.lines:
        if not (t.get("highway") == "cycleway" or t.get("cycleway") == "crossing") or "crossing" not in t \
                or t.get("crossing") in ("unmarked", "no") or tunnelish(t):
            continue
        rr, cc = cells_of(line.buffer(1.5, cap_style="flat"))
        k = asph[rr, cc] & ~_xw[rr, cc]
        gcol[rr[k], cc[k]] = C["cycle"]

    lane_lines = []
    for oid, t, line in osm.lines:
        hw = t.get("highway")
        if hw not in ("primary", "secondary", "trunk", "primary_link", "secondary_link") or tunnelish(t):
            continue
        lanes = int(parse_len(t.get("lanes")) or (2 if hw in ("primary", "secondary", "tertiary") else 1))
        if lanes < 2:
            continue
        width = parse_len(t.get("width")) or lanes * 3.1
        lw = width / lanes
        oneway = t.get("oneway") in ("yes", "-1")
        for k in range(1, lanes):
            off = -width / 2 + k * lw
            try:
                ln = line.offset_curve(off) if abs(off) > 0.2 else line
            except Exception:
                continue
            if ln.is_empty or ln.length < 4:
                continue
            solid = (not oneway) and abs(off) < 0.6
            if solid:
                lane_lines.append(ln)
            else:
                L = ln.length
                for s in np.arange(1.0, L - 1, 9.0):
                    lane_lines.append(substring(ln, s, min(s + 3, L)))
    _deg, _hw = {}, {}
    for oid, t, line in osm.lines:
        b = (t.get("highway") or "").replace("_link", "")
        if b not in HW or b not in ROADS or tunnelish(t) or on_bridge(t):
            continue
        xy = [tuple(np.round(p, 1)) for p in line.coords]
        for k, p in enumerate(xy):
            _deg[p] = _deg.get(p, 0) + (k > 0) + (k < len(xy) - 1)
            _hw[p] = max(_hw.get(p, 0), HW[b] / 2)
    _junc = [Point(p).buffer(_hw[p] + 4) for p, d in _deg.items() if d >= 3]
    _junc += [geom for oid, typ, t, geom in osm.areas_with("area:highway") if t.get("junction") and not tunnelish(t)]
    lm = np.zeros((D, W), np.uint16)
    burn(lm, [(l, 1) for l in lane_lines], all_touched=False)
    _jm = np.zeros((D, W), np.uint16)
    burn(_jm, [(j, 1) for j in _junc])
    lm_mask = (lm > 0) & (_jm == 0) & np.isin(gcol, [C["asphalt"]])
    gcol[lm_mask] = C["mark"]
    note("lane marking cells:", int(lm_mask.sum()))

    # ---------------------------------------------------------------- buildings
    feats = []
    for oid, typ, t, geom in osm.areas:
        part = t.get("building:part") not in (None, "no")
        bld = t.get("building") not in (None, "no") and not part
        if not (part or bld) or t.get("building") == "construction" or t.get("location") == "underground":
            continue
        if parse_len(t.get("layer", 0)) < 0 and not part:
            continue
        h = parse_len(t.get("height"))
        lv = parse_len(t.get("building:levels"))
        if h is None and lv is not None:
            h = lv * 3.2 + (parse_len(t.get("roof:height")) or (parse_len(t.get("roof:levels")) or 0) * 2.8)
        mh = parse_len(t.get("min_height"))
        if mh is None and t.get("building:min_level"):
            mh = parse_len(t["building:min_level"]) * 3.2
        if t.get("building") in ("roof", "carport") and mh is None:
            mh = 2.5
        rr, cc = cells_of(geom)
        if len(rr) == 0:
            continue
        feats.append(dict(id=oid, typ=typ, tags=t, geom=geom, part=part, rr=rr, cc=cc, maxh=h, minh=mh or 0.0,
                          area=geom.area))
    note("building features:", len(feats), "parts:", sum(f["part"] for f in feats))
    # Catastro (DECISIONS.md 2026-11-11): OSM footprints stay, with their tags and parts; where OSM gives no height or
    # levels, the floors of the Catastro parts under the footprint stand in; Catastro buildings OSM lacks are added
    import catastro
    _floors = catastro.Floors()
    n_cfl = 0
    for f in feats:
        if f["maxh"] is None:
            n = _floors.under(f["geom"])
            if n:
                f["maxh"], f["h_src"] = n * catastro.FLOOR_H, "catastro"
                n_cfl += 1
    _osm_b = _uu([f["geom"] for f in feats if not f["part"]]) if feats else Point(-1e6, -1e6)
    n_cnew = 0
    for k, (cid, props, geom) in enumerate(catastro.load("buildings")):
        if geom.area < 10 or geom.intersection(_osm_b).area > 0.3 * geom.area:
            continue
        rr, cc = cells_of(geom)
        if len(rr) == 0:
            continue
        n = _floors.under(geom)
        feats.append(dict(id=-(k + 1), typ="catastro", tags={"building": "yes", "source": "Catastro", "ref:catastro": cid},
                          geom=geom, part=False, rr=rr, cc=cc, maxh=n * catastro.FLOOR_H if n else None, minh=0.0,
                          area=geom.area, h_src="catastro"))
        n_cnew += 1
    note("Catastro: floors for OSM features without height", n_cfl, "| buildings missing from OSM added", n_cnew)

    outlines = [f for f in feats if not f["part"]]
    parts = [f for f in feats if f["part"]]
    otree = STRtree([f["geom"] for f in outlines])
    PART_PARENTS = json.load(open(Path(__file__).with_name("part_parents.json")))["parents"]
    for p in parts:  # parts inherit colours/material/name from their outline
        rp = p["geom"].representative_point()
        # inside several outlines (a block relation, the same outline mapped twice): the one it had when the landmarks
        # were curated (part_parents.json), else the smallest -- never the spatial index's order, which changes with the map
        hits = sorted((outlines[i] for i in otree.query(rp, predicate="within")), key=lambda o: (round(o["area"], 1), -o["id"]))
        for o in hits:
            o["has_parts"] = True
        if hits:
            p["parent"] = next((o for o in hits if o["id"] == PART_PARENTS.get(str(p["id"]))), hits[0])
    for p in parts:
        if "parent" not in p:
            cands = [outlines[i] for i in otree.query(p["geom"], predicate="intersects")]
            if cands:
                p["parent"] = max(cands, key=lambda o: (round(o["geom"].intersection(p["geom"]).area, 1), -o["id"]))
                p["parent"]["has_parts"] = True
    for o in outlines:
        # outline with parts not rendered (OSM simple-3D convention) if parts cover most of it
        if o.get("has_parts"):
            covered = sum(p["geom"].intersection(o["geom"]).area for p in parts if p.get("parent") is o)
            o["render"] = covered < 0.6 * o["area"]
        else:
            o["render"] = True
    for p in parts:
        p["render"] = True
    render = [f for f in feats if f["render"]]


    bmask = np.zeros((D, W), bool)
    for f in render:
        bmask[f["rr"], f["cc"]] = True

    # feature-level source decision (LiDAR 2025 vs OSM 2026)
    top = np.where(bmask, nd_max_b, 0.0).astype(np.float32)
    src_osm = []
    for f in render:
        if f["maxh"] is None:
            continue
        v = nd_max_b[f["rr"], f["cc"]]
        med, p90 = float(np.median(v)), float(np.percentile(v, 90))
        f["dsm_med"] = med
        if f["maxh"] - p90 > 8:
            small = f["area"] < 80 and p90 > 0.7 * f["maxh"]  # needle on top of a tall building
            rh = parse_len(f["tags"].get("roof:height")) or 0
            pointed = f["tags"].get("roof:shape") in ("pyramidal", "conical", "onion", "spire", "dome") and rh >= 3
            if pointed and len(f["rr"]) >= 9 and p90 > 0.6 * (f["maxh"] - rh):
                # a tower's pointed roof the LiDAR missed (Salvator's two bell towers: 61 m of tower, a 15 m pyramid): it
                # rises from the eaves to its peak by distance from the part's edge -- not the whole footprint at 76 m
                rr_, cc_ = f["rr"], f["cc"]
                m_ = np.zeros((rr_.max() - rr_.min() + 3, cc_.max() - cc_.min() + 3), bool)
                m_[rr_ - rr_.min() + 1, cc_ - cc_.min() + 1] = True
                dep = ndimage.distance_transform_edt(m_)[rr_ - rr_.min() + 1, cc_ - cc_.min() + 1]
                roof_ = (f["maxh"] - rh) + rh * (dep - 1) / max(dep.max() - 1, 1)
                top[rr_, cc_] = np.maximum(top[rr_, cc_], roof_)
                src_osm.append((f["id"], tag(f, "name"), round(p90, 1), f["maxh"], "pointed roof"))
            elif small or p90 < 0.35 * f["maxh"]:  # else: nothing tall there in 2025 -> built after the flight
                # spire/needle under-sampled by LiDAR, or built after the 2025 flight
                top[f["rr"], f["cc"]] = np.maximum(top[f["rr"], f["cc"]], f["maxh"])
                src_osm.append((f["id"], tag(f, "name"), round(p90, 1), f["maxh"], "spire" if small else "new"))
    for s in src_osm:
        note("OSM height used (LiDAR lower):", s)
    # OSM buildings absent in LiDAR without height info
    for f in render:
        if f["maxh"] is None and np.median(nd_max[f["rr"], f["cc"]]) < 1.5:
            top[f["rr"], f["cc"]] = 3.2 * (parse_len(tag(f, "building:levels")) or 1)
            note("no LiDAR + no height -> levels:", f["id"], tag(f, "name"))

    # tree canopy over low roofs: clip to OSM height; not a garden's beds on its roof (Kopernik's, 6 m over its 3 levels)
    GARDEN_ROOFS = roofgardens.hosts(osm)
    cell_maxh = np.full((D, W), np.nan, np.float32)
    for f in sorted(render, key=lambda f: f["maxh"] or 0):
        if f["maxh"] is not None:
            cell_maxh[f["rr"], f["cc"]] = np.fmax(cell_maxh[f["rr"], f["cc"]], f["maxh"])
    # a crown that is not green (a copper beech over Jazdów 3/6) is still rough: the DSM's spread over 3 m is ~4 m in a
    # crown, under 1 m on a roof. Only over a small low house standing among crowns (a ring round it, away from other
    # buildings, tall and green or rough) whose raised cells are mostly rough: a mistagged tower is smooth on top
    _m = ndimage.uniform_filter(dsm, 6)
    rough = np.sqrt(np.maximum(ndimage.uniform_filter(dsm * dsm, 6) - _m * _m, 0)).reshape(D, 2, W, 2).max((1, 3))
    under_tree = np.zeros((D, W), bool)
    for f in render:
        if f["part"] or f.get("has_parts") or f["maxh"] is None or f["maxh"] > 8 or f["area"] >= 400:
            continue
        r0, r1, c0, c1 = max(f["rr"].min() - 5, 0), min(f["rr"].max() + 6, D), max(f["cc"].min() - 5, 0), min(f["cc"].max() + 6, W)
        own = np.zeros((r1 - r0, c1 - c0), bool)
        own[f["rr"] - r0, f["cc"] - c0] = True
        ring = ndimage.binary_dilation(own, iterations=4) & ~ndimage.binary_dilation(bmask[r0:r1, c0:c1] & ~own, iterations=3) & ~own
        crown = (nd_max[r0:r1, c0:c1] > f["maxh"] + 3) & ((exg[r0:r1, c0:c1] > 0.06) | (rough[r0:r1, c0:c1] > 2.5))
        raised = nd_max[f["rr"], f["cc"]] > f["maxh"] + 3
        if ring.sum() > 10 and crown[ring].mean() > 0.25 and raised.any() and (rough[f["rr"], f["cc"]][raised] > 2.5).mean() > 0.6:
            under_tree[f["rr"], f["cc"]] = True
    over = bmask & ((exg > 0.06) | under_tree) & np.isfinite(cell_maxh) & (top > cell_maxh + 3)
    for _b, *_ in GARDEN_ROOFS.values():
        over[cells_of(_b)] = False
    top[over] = cell_maxh[over]
    note("roof cells under tree canopy clipped:", int(over.sum()), "of them rough, not green:", int((over & ~(exg > 0.06)).sum()))

    # bottoms (overhangs: roofs/carports/stacked parts with no part below)
    bot_rel = np.full((D, W), 1e9, np.float32)
    # outlines drawn only through their parts count too: a part starting at 19 m with no part mapped under it (the WFC
    # tower, InterContinental, a ministry's top floors) stands on its outline's walls, it does not hover over the street
    for f in feats:
        if f["render"] or f.get("has_parts"):
            bot_rel[f["rr"], f["cc"]] = np.minimum(bot_rel[f["rr"], f["cc"]], f["minh"])
    bot_rel[~bmask] = 0
    bot_rel[bot_rel < 2.5] = 0

    landmarks.adjust_heights(top, feats, note)  # curated fixes from research.md

    # de-noise low roofs (LiDAR clutter) in building interiors; keep towers/spires untouched
    interior = ndimage.binary_erosion(bmask, iterations=1)
    top_med = ndimage.median_filter(top, size=3)
    smooth_roof = interior & (top < 45) & (np.abs(top_med - top) < 4)
    top = np.where(smooth_roof, top_med, top)


    def flatten_roofs(top):
        """Flat roofs flat: per building part, if most of the roof lies within 1.5 m of its median, snap every cell within
        2.5 m to it, and snap blobs above or below it smaller than 15 cells (LiDAR speckle on the roof, a 1 m slot down a
        wall where the edge returns came low). Rooftop structures bigger than that, pitched roofs and towers stay."""
        n_f = n_c = 0
        for f in sorted(render, key=lambda f: -len(f["rr"])):  # parents first, their parts after
            rr, cc = f["rr"], f["cc"]
            if len(rr) < 30 or ((f.get("minh") or 0) >= 2.5 and np.median(bot_rel[rr, cc]) >= 2.5):
                continue  # parts on stilts (canopies, cantilevers): snapping their top under their bottom left fragments
                # (a part on its podium -- IBC's curved wing from 8 m -- stands on something: its roof is snapped too)
            v = top[rr, cc]
            med = float(np.median(v))
            if med < 3:
                continue
            if np.mean(np.abs(v - med) <= 1.5) < 0.6:
                # several roof levels (one OSM outline over a whole theatre or palace): snap each column to its 5x5
                # neighbourhood's median within 2.5 m, so every terrace is flat and the real setbacks stay
                if len(rr) >= 200:
                    r0, c0 = rr.min(), cc.min()
                    box = np.zeros((rr.max() - r0 + 3, cc.max() - c0 + 3), np.float32)
                    inside = np.zeros(box.shape, bool)
                    box[rr - r0 + 1, cc - c0 + 1] = v
                    inside[rr - r0 + 1, cc - c0 + 1] = True
                    # outside the outline: the nearest inside height (zeros there pulled the median down at every edge,
                    # notching the roofline)
                    _, (ir, ic) = ndimage.distance_transform_edt(~inside, return_indices=True)
                    lm = ndimage.median_filter(box[ir, ic], 5)[rr - r0 + 1, cc - c0 + 1]
                    k = (np.abs(v - lm) <= 2.5) & (lm > 3)
                    n_c += int((k & (v != lm)).sum())
                    top[rr[k], cc[k]] = lm[k]
                    # then the roof's own levels: peaks of its height histogram (1 m bins, 6 % of the roof or 40 cells);
                    # cells within 1.5 m of a level go to it -- 1 m terraces of LiDAR noise between them (lumpy
                    # podium roofs, LIM, Metropolitan) were drawn as steps
                    v2 = top[rr, cc]
                    hist = np.bincount(np.clip(np.round(v2).astype(int), 0, 400), minlength=402)
                    lev = [h for h in range(1, 401) if hist[h] >= max(40, 0.06 * len(v2)) and hist[h] >= hist[h - 1] and hist[h] >= hist[h + 1]]
                    if lev:
                        # levels closer than 2.5 m are one level with noise (two neighbouring 1 m bins): the larger stays
                        lev = sorted(lev, key=lambda h: -hist[h])
                        keep_ = []
                        for h in lev:
                            if all(abs(h - k_) >= 2.5 for k_ in keep_):
                                keep_.append(h)
                        lev = np.array(sorted(keep_), np.float32)
                        j = np.argmin(np.abs(v2[:, None] - lev[None]), axis=1)
                        k2 = np.abs(v2 - lev[j]) <= 1.5
                        n_c += int((k2 & (v2 != lev[j])).sum())
                        top[rr[k2], cc[k2]] = lev[j][k2]
                    n_f += 1
                continue
            r0, c0 = rr.min(), cc.min()
            off = np.zeros((rr.max() - r0 + 1, cc.max() - c0 + 1), bool)
            off[rr - r0, cc - c0] = np.abs(v - med) > 2.5
            lab, n = ndimage.label(off)
            if n:
                size = ndimage.sum(off, lab, range(1, n + 1))
                keep = np.concatenate([[False], size >= 15])  # big blobs: real structures
                snap = ~keep[lab[rr - r0, cc - c0]]
            else:
                snap = np.ones(len(rr), bool)
            n_c += int((snap & (v != med)).sum())
            top[rr[snap], cc[snap]] = med
            n_f += 1
        note(f"flat roofs: {n_f} parts, {n_c} cells snapped")


    flatten_roofs(top)


    def core_roofs(top):
        """The Old Town's tiled roofs as the ortho shows them: clean slopes from the street and the courtyard up to a
        ridge. The 1 m LiDAR made them noisy terraces (every dormer, chimney and sample). Per house in the historic core
        whose roof is pitched (3 m or more between its eaves and its top): height = eave + slope x distance to the nearest
        open cell (street or courtyard; through party walls, as a terrace of houses is roofed), fitted to the LiDAR on the
        cells within 8 m of the open side, capped at the house's ridge (95th percentile)."""
        core = np.zeros((D, W), bool)
        core[cells_of(CORE_GEOM)] = True
        dist = ndimage.distance_transform_edt(bmask)
        n_h = 0
        for f in render:
            rr, cc = f["rr"], f["cc"]
            # a garden roof stays flat: the hedges and lawns on the Kubicki Arcades read as a ridge
            if len(rr) < 20 or not core[rr, cc].mean() > 0.5 or (f.get("minh") or 0) > 2 or f["id"] in GARDEN_ROOFS:
                continue
            v, d = top[rr, cc].astype(float), dist[rr, cc]
            if np.percentile(v, 95) - np.percentile(v, 10) < 3:
                continue
            m = (d <= 8) & (v > 3)
            if m.sum() < 8:
                continue
            for _ in range(3):  # least squares, dropping dormers and chimneys (2 m+ off the slope) each round
                A = np.c_[np.ones(m.sum()), d[m]]
                (e, k), *_ = np.linalg.lstsq(A, v[m], rcond=None)
                m &= np.abs(v - (e + k * d)) < 2
                if m.sum() < 8:
                    break
            if not (0.4 <= k <= 2.5) or m.sum() < 8:
                continue
            ridge = np.percentile(v, 95)
            top[rr, cc] = np.minimum(e + k * d, ridge)
            n_h += 1
        note("historic core: pitched roofs fitted:", n_h)


    CORE_GEOM = landmarks.historic_core()
    core_roofs(top)
    topi = np.where(bmask, np.round(top), 0).astype(np.int32)
    # single LiDAR pits in a flat roof (1-3 m deep, up to 3 cells, building all round): each read as a black speck under
    # the ambient occlusion (Bristol's, Europejski's, BGK's roofs); outside the old town's fitted pitched roofs
    _cl = ndimage.grey_closing(topi, size=(3, 3))
    _pit = bmask & (_cl - topi >= 1) & (_cl - topi <= 3) & (ndimage.minimum_filter(bmask.astype(np.uint8), 3) > 0)
    _pit[cells_of(CORE_GEOM)] = False
    _pl, _pn = ndimage.label(_pit)
    if _pn:
        _pit &= np.r_[False, ndimage.sum(_pit, _pl, range(1, _pn + 1)) <= 3][_pl]
    topi[_pit] = _cl[_pit]
    note("roof pits filled:", int(_pit.sum()))
    boti = np.round(bot_rel).astype(np.int32)
    bmask &= topi >= 2


    # colours/materials per feature
    SACRED = {"church", "cathedral", "chapel", "basilica", "synagogue", "mosque", "temple", "shrine"}
    M_CLASSIC, M_TENEMENT = 20, 22
    CORE = CORE_GEOM
    # the historic core's walls where OSM gives no colour (Madrid de los Austrias, palette.AUSTRIAS_WALLS)
    CORE_WALLS = AUSTRIAS_WALLS


    def wall_style(f):
        t = f["tags"]
        mat_tag = (tag(f, "building:material") or "").lower()
        col = parse_colour(t.get("building:colour") or t.get("colour")) or \
            (parse_colour(f["parent"]["tags"].get("building:colour")) if f.get("parent") else None)
        btype = tag(f, "building") or ""
        h = f["maxh"] or float(np.median(top[f["rr"], f["cc"]]))
        glass = "glass" in mat_tag or (not mat_tag and h > 45 and btype in ("office", "commercial", "hotel", "yes", "retail")
                                       and "building:colour" not in t)
        if glass:
            return pal(soften(col or hex_rgb("#8aa4b4"), 0.08), M_GLASS)
        if mat_tag in ("concrete",) and col is None:
            col = hex_rgb("#c9c6bd")
        if mat_tag in ("brick",) and col is None:
            col = hex_rgb(WALL_BRICK[stable_hash(f["id"]) % len(WALL_BRICK)])
        if mat_tag in ("stone", "granite") and col is None:
            col = hex_rgb(WALL_GRANITE[stable_hash(f["id"]) % len(WALL_GRANITE)])
        core = CORE.contains(f["geom"].representative_point())
        sacred = btype in SACRED or tag(f, "amenity") == "place_of_worship"
        if col is None:
            walls = WALL_GRANITE if sacred else CORE_WALLS if core else WALL_DEFAULTS
            col = hex_rgb(walls[stable_hash(f["id"]) % len(walls)])
        if btype in SACRED or tag(f, "amenity") == "place_of_worship":
            return pal(soften(col), M_CLASSIC)  # stone or brick, tall windows: not the shader's office grid of storeys
        if core:
            return pal(soften(col), M_TENEMENT)
        return pal(soften(col), M_WALL)


    ROOF_OVERRULED = []


    def roof_material(col, shape):
        """Madrid's roof material for an ortho colour: clay tile where red-orange, slate where dark; a grey roof is a
        flat terrace (azotea, ~40 % of the roofs round Sol), zinc only on a mansard."""
        c_ = np.asarray(col, float)
        if c_[0] > c_[2] + 30 and c_[0] > c_[1] + 12:
            return "tile"
        lum_c = 0.299 * c_[0] + 0.587 * c_[1] + 0.114 * c_[2]
        if lum_c < 95:
            return "slate"
        return "zinc" if shape in ("mansard", "gambrel") else "terrace"


    def roof_style(f):
        col = parse_colour(tag(f, "roof:colour"))
        from_osm = col is not None
        if col is None and (f["tags"].get("roof:material") or "").lower() == "glass":
            return pal(soften(hex_rgb("#93adbf"), 0.06), M_GLASS)  # glass atrium roofs (Politechnika's hall): blue-grey
        h = float(np.median(top[f["rr"], f["cc"]]))
        lum_ = lambda c_: 0.299 * c_[0] + 0.587 * c_[1] + 0.114 * c_[2]
        # (a near-black tag on a tower too: the slabs on Wola tagged #170106 tar paper read light grey in the ortho; an
        # untagged roof up to 80 m as well, the 49 m slabs by Grzybowska had the dark default grey over light roofs;
        # higher, the ortho's lean puts facade and street into the roof's cells)
        if h < 40 or (col is not None and lum_(col) < 110) or (col is None and h < 80):
            cc = cellcol[f["rr"], f["cc"]]
            L = lum[f["rr"], f["cc"]]
            if len(L) >= 3:
                sel = cc[(L >= np.percentile(L, 25)) & (L <= np.percentile(L, 85))]
                oc = tuple(np.median(sel, axis=0))
                # an OSM roof colour far from what the ortho sees (a palace's #003300, near black, over a mid-green copper
                # roof) gives way to the ortho
                # (never towards darker: a roof in a tower's shadow reads dark in the ortho)
                # (only dark OSM colours, the near-black tags; a red or green roof tag is usually right)
                if col is None or (np.linalg.norm(np.subtract(col, oc)) > 110 and lum_(col) < 110 and lum_(oc) > lum_(col) - 15):
                    if col is not None:
                        ROOF_OVERRULED.append((f["id"], tag(f, "roof:colour")))
                    col, from_osm = oc, False
        if col is None:
            col = hex_rgb("#7d7f84")
        col = np.array(col, float) * 1.05  # ortho is slightly dark
        glassy = pal.entries[f["wall"]][3] == M_GLASS if "wall" in f else False
        # (an untagged roof the ortho sees clearly orange is tiles too: 422 of them, palaces and friaries off the old town,
        # had been washed out to beige)
        tiles = (tag(f, "roof:material") or "") in ("roof_tiles", "tile", "tiles") or CORE.contains(f["geom"].representative_point()) \
            or (col[0] > col[2] + 35 and col[0] > col[1] + 18)
        # and carries blue sky reflections -- but not a tiled roof's red, which went pink (the Old Town: Rynek photos)
        red = tiles and col[0] > col[2] + 25  # the ortho's sunlit tiles read orange; in photos they are a brick red-brown
        # copper patina: the ortho sees it pale green-blue (red well under green and blue), the 0.6 desaturation below drew
        # it near white (Pac Palace, the Blue Palace, Holy Cross); photos show a soft grey-green, in two shades
        if not glassy and col[1] > col[0] + 14 and col[2] > col[0] + 4 and col.mean() > 110:
            return pal(soften(hex_rgb(["#86a99a", "#7d9f91"][stable_hash(f["id"]) % 2]), 0.05), M_ROOF, q=12)
        # Madrid's roof materials (palette.ROOF_SHADES): from the OSM roof:material, else, where OSM gives no colour,
        # from the ortho colour; one shade per building. A roof:colour tag from OSM keeps its own colour.
        mat = ROOF_MATERIALS.get((tag(f, "roof:material") or "").lower())
        if mat is None and red:
            mat = "tile"
        if mat is None and not from_osm and not glassy:
            mat = roof_material(col, tag(f, "roof:shape"))
        if mat:
            shades = ROOF_SHADES[mat]
            return pal(soften(hex_rgb(shades[stable_hash(f["id"]) % len(shades)]), 0.05), M_ROOF, q=12)
        col = tuple(np.clip(col.mean() + (col - col.mean()) * 0.6, 0, 255))
        return pal(soften(col, 0.1), M_ROOF, q=12)


    for f in render:
        f["wall"] = landmarks.wall_override(f, pal) or wall_style(f)
        f["roof"] = landmarks.roof_override(f, pal) or roof_style(f)
        wc, rc = parse_colour(tag(f, "building:colour")), parse_colour(tag(f, "roof:colour"))
        if pal.entries[f["wall"]][3] == M_GLASS and wc is not None and wc == rc:
            f["roof"] = f["wall"]

    # parts under 1 m wide along a bigger one (Focus's dark frame round its glass box, trims, fins): at 1 m they are one
    # cell per step of a rotated wall, a dotted staircase that striped the whole facade -- they take the bigger part's wall
    THIN_LOG = []
    _pl = [f for f in render if f["part"] and f["maxh"]]
    _thin, _thk = [], []
    for f in _pl:
        rr_, cc_ = f["rr"], f["cc"]
        m_ = np.zeros((rr_.max() - rr_.min() + 3, cc_.max() - cc_.min() + 3), bool)
        m_[rr_ - rr_.min() + 1, cc_ - cc_.min() + 1] = True
        _mr = f["geom"].minimum_rotated_rectangle
        _xy = np.array(_mr.exterior.coords)
        _ang = math.degrees(math.atan2(_xy[1, 1] - _xy[0, 1], _xy[1, 0] - _xy[0, 0])) % 90
        rotated = 12 < _ang < 78  # on the grid a 1 m frame or band draws cleanly (Oxford Tower's white frame, Varso's bands)
        (_thin if ndimage.distance_transform_edt(m_).max() <= 1.5 and rotated else _thk).append(f)  # (1.41: 2 across on a diagonal)
    _bb = np.array([(f["rr"].min(), f["rr"].max(), f["cc"].min(), f["cc"].max()) for f in _thk]) if _thk else np.zeros((0, 4))
    n_thin = 0
    for f in _thin:
        rr_, cc_ = f["rr"], f["cc"]
        lo_ = f["minh"] or 0
        # parts overlap (a lobby under a tower): every thick part within 2 m spanning the same storeys, the biggest wins
        k_ = np.nonzero((_bb[:, 0] <= rr_.max() + 2) & (_bb[:, 1] >= rr_.min() - 2) & (_bb[:, 2] <= cc_.max() + 2) & (_bb[:, 3] >= cc_.min() - 2))[0]
        best = None
        for k in k_:
            p_ = _thk[k]
            if abs(p_["maxh"] - f["maxh"]) > 6 or abs((p_["minh"] or 0) - lo_) > 6:
                continue
            r0_, c0_ = rr_.min() - 2, cc_.min() - 2
            m_ = np.zeros((rr_.max() - r0_ + 3, cc_.max() - c0_ + 3), bool)
            m_[rr_ - r0_, cc_ - c0_] = True
            m_ = ndimage.binary_dilation(m_, iterations=2)
            q_ = (p_["rr"] >= r0_) & (p_["rr"] < r0_ + m_.shape[0]) & (p_["cc"] >= c0_) & (p_["cc"] < c0_ + m_.shape[1])
            if q_.any() and m_[p_["rr"][q_] - r0_, p_["cc"][q_] - c0_].any() and (best is None or len(p_["rr"]) > len(best["rr"])):
                best = p_
        if best is not None:
            if best["wall"] != f["wall"]:
                THIN_LOG.append((f["id"], int(rr_.mean()), int(cc_.mean()), pal.entries[f["wall"]][:4], pal.entries[best["wall"]][:4], len(rr_)))
            f["wall"] = best["wall"]
            n_thin += 1
    note("thin parts given their neighbour's wall:", n_thin, "of", len(_thin))
    json.dump(THIN_LOG, open("data/debug/thin_parts.json", "w"))

    note("OSM roof colours overruled by the ortho:", len(ROOF_OVERRULED), ROOF_OVERRULED[:8])
    H = int(max(topi.max() + g.max(), g.max()) + 12)
    note("volume height", H)

    return dict(
        BASE=BASE,
        CORE=CORE,
        GARDEN_ROOFS=GARDEN_ROOFS,
        H=H,
        LIDAR_BRIDGE=LIDAR_BRIDGE,
        LIDAR_VEG=LIDAR_VEG,
        MAX_TREE=MAX_TREE,
        OPEN_CUT=OPEN_CUT,
        SACRED=SACRED,
        bmask=bmask,
        boti=boti,
        bridge_lines=bridge_lines,
        bridge_rails=bridge_rails,
        bridge_roads=bridge_roads,
        bridge_shapes=bridge_shapes,
        cell_maxh=cell_maxh,
        cellcol=cellcol,
        cls=cls,
        dsm=dsm,
        dsm_mean=dsm_mean,
        dtm=dtm,
        exg=exg,
        feats=feats,
        g=g,
        gcol=gcol,
        is_road=is_road,
        lm=lm,
        lum=lum,
        nd_max=nd_max,
        nd_mean=nd_mean,
        osm=osm,
        over=over,
        parking_mask=parking_mask,
        rails=rails,
        render=render,
        rgbsum=rgbsum,
        splash_pads=splash_pads,
        top=top,
        topi=topi,
        z=z,
        carriageway_sanity=carriageway_sanity,
    )
