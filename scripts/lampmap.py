"""The street lamps' light on the ground, baked (web/public/data/lampmap.bin), for the viewer's night shading.

Each lamp in lamps.bin (lamps.py) lights the ground around it as a point source at its lantern's height h: illuminance
on a horizontal plane falls as (1 + (d / (SPREAD h))^2)^-1.5, so a tall mast lights a wider patch as brightly as a short
lantern lights its own (the masts are brighter in proportion). SPREAD widens the bare point source to what street
optics do, throwing light along the street rather than straight down. The light is cut by the buildings, in plan:
rays from the lantern stop one texel into the first building they meet, so the facade the lamp faces is lit and the
courtyard behind it is not, and a wall bracket lights only its own side of the street.

The light is summed in float and compressed into 8 bits as 1 - exp(-K x), so where lamps crowd (Sol, Gran Vía) the
ground brightens towards white without clipping, and a lone lantern in a park still shows.

Lamps on a bridge deck are left out: the map has one level, and the light would fall on the street under the deck.

lampmap.bin, gzip of two uint8 planes one after the other, each row-major (TEXEL metres per texel, the grid's columns
across, rows down; 2200 x 1425 over the AOI):
  light   1 - exp(-K x), x the summed illuminance (1 = under a lone lantern)
  colour  from 0 cool white (floodlights) through 0.55 the warm white LEDs to 1 the amber of sodium discharge, in 16
          steps (planes, and the coarse colour, compress to 2.0 MB against 2.5 MB for interleaved full-precision pairs)

usage: PYTHONPATH=scripts uv run python scripts/lampmap.py  (after lamps.py)
"""
import gzip
import json
import math

import numpy as np

from aoi import AREA, VOXEL_SIZE, WEB_DATA, D, W

TEXEL = 2.0  # metres per texel of the map
SPREAD = 1.8  # the optics' spread, in lantern heights
CUT = 0.05  # a lamp's light ends where it falls to this share of the light under it (and is lowered by it, to end smoothly):
# the night exposure brightens faint light, and longer tails summed into a glow over every lawn and courtyard
K = 0.5  # compression: a lone lantern's own light (x = 1) becomes 1 - exp(-K) = 0.39, the crowd at Sol (x = 3) 0.78
RAYS = 256  # rays per lamp for the buildings' shadow
# light under a lantern of each style (lamps.py: Villa, Fernando VII, globe, modern); a globe throws half its light up
STRENGTH = (1.0, 1.0, 0.6, 1.2)
WARMTH = (0.55, 1.0, 0.78)  # LED, discharge, both on one support
ARM = {0: 0.3, 1: 0.3, 2: 0.0, 3: 1.5}  # metres from the post to the light: the lantern's bracket, a modern mast's arm
WALL_OUT = 0.6  # metres from the facade to a wall bracket's lantern
FLOOD_WARMTH = 0.0
PARK = 0.35  # a park lantern (lamps.py flag 4) is dimmer: the Retiro at night is its lit paths, not its lawns


def blocking(tw, td):
    """Texels mostly inside a building: the 1 m building mask, 3 of 4 cells (a 4 m lane stays open)."""
    b = np.load(AREA / "ground.npz")["b"] > 0
    f = round(TEXEL / VOXEL_SIZE)
    pad = np.zeros((td * f, tw * f), bool)
    pad[:b.shape[0], :b.shape[1]] = b
    return pad.reshape(td, f, tw, f).mean(axis=(1, 3)) >= 0.75


def bake(lamps, floods, block):
    td, tw = block.shape
    light = np.zeros((td, tw), np.float64)
    warm = np.zeros((td, tw), np.float64)
    ang = np.arange(RAYS) * (2 * math.pi / RAYS)
    cos, sin = np.cos(ang), np.sin(ang)
    reach_k = math.sqrt(CUT ** (-2 / 3) - 1) * SPREAD  # (1 + x^2)^-1.5 = CUT at x = reach_k / SPREAD lantern heights

    def add(px, py, h, strength, warmth):
        """A source at (px, py) texels, h texels up."""
        R = reach_k * h
        steps = np.arange(0.5, R + 1, 0.5)
        sx = (px + cos[:, None] * steps).astype(int)
        sy = (py + sin[:, None] * steps).astype(int)
        inside = (sx >= 0) & (sx < tw) & (sy >= 0) & (sy < td)
        hit = np.zeros(sx.shape, bool)
        hit[inside] = block[sy[inside], sx[inside]]
        if 0 <= int(px) < tw and 0 <= int(py) < td and block[int(py), int(px)]:
            hit[:, steps <= 1.5] = False  # a bracket in a facade's texel: the rays start in its own building
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), len(steps))
        reach = np.append(steps, steps[-1] + 0.5)[first] + 1.0  # one texel into the wall: the facade is lit
        x0, x1 = max(int(px - R), 0), min(int(px + R) + 1, tw)
        y0, y1 = max(int(py - R), 0), min(int(py + R) + 1, td)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dx, dy = xx + 0.5 - px, yy + 0.5 - py
        d = np.hypot(dx, dy)
        ray = np.round(np.arctan2(dy, dx) / (2 * math.pi) * RAYS).astype(int) % RAYS
        e = strength * np.maximum((1 + (d / (SPREAD * h)) ** 2) ** -1.5 - CUT, 0) / (1 - CUT)
        e[(d > reach[ray]) | (d > R)] = 0
        light[y0:y1, x0:x1] += e
        warm[y0:y1, x0:x1] += e * warmth

    t = VOXEL_SIZE / TEXEL  # cells to texels
    for L in lamps:
        if L["flags"] & 8:
            continue
        a = L["heading"] / 256 * 2 * math.pi
        out = WALL_OUT if L["flags"] & 1 else ARM[int(L["style"])]
        h = max(L["height"] / 10, 2.0) / TEXEL
        s, w = STRENGTH[int(L["style"])] * (PARK if L["flags"] & 4 else 1), WARMTH[min(int(L["light"]), 2)]
        for side in ((1,) if L["arms"] < 2 else (1, -1)):
            ox, oy = math.cos(a) * out * side / VOXEL_SIZE, math.sin(a) * out * side / VOXEL_SIZE
            add((L["x"] + ox) * t, (L["y"] + oy) * t, h, s, w)
    for x, y, r in floods:  # a floodlit pitch: an even wash out to its edge (landmarks.py)
        yy, xx = np.mgrid[0:td, 0:tw]
        d = np.hypot((xx + 0.5) / t - x, (yy + 0.5) / t - y)
        e = 1.2 * np.clip((r * 1.35 - d) / (r * 0.4), 0, 1)
        light += e
        warm += e * FLOOD_WARMTH
    return light, warm


def main():
    from lamps import REC
    lamps = np.frombuffer(gzip.decompress((WEB_DATA / "lamps.bin").read_bytes()), REC)
    floods = json.loads((WEB_DATA / "meta.json").read_text()).get("floods") or []
    tw, td = math.ceil(W * VOXEL_SIZE / TEXEL), math.ceil(D * VOXEL_SIZE / TEXEL)
    light, warm = bake(lamps, floods, blocking(tw, td))
    r = 1 - np.exp(-K * light)
    g = np.where(light > 1e-6, warm / np.maximum(light, 1e-6), 0.55)
    out = np.concatenate([np.round(r * 255).astype(np.uint8).ravel(), (np.minimum(g * 16, 15) * 16 + 8).astype(np.uint8).ravel()])
    (WEB_DATA / "lampmap.bin").write_bytes(gzip.compress(out.tobytes(), 9, mtime=0))
    lit = light > CUT
    print(f"lamp map: {tw} x {td} texels of {TEXEL:g} m, {len(lamps)} lamps, {len(floods)} floodlit pitches;"
          f" lit {lit.mean():.0%} of the map, light under the lit part: median {np.median(light[lit]):.2f},"
          f" 95th percentile {np.percentile(light[lit], 95):.2f}, max {light.max():.2f}")


if __name__ == "__main__":
    main()
