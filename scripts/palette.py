"""Materials, the voxel palette and colour helpers shared by the fusion (layers.py) and the 3D fill (voxelize.py).

Material ids must match web/src/voxelMaterial.ts (MAT).
"""
import colorsys
import hashlib
import re

import webcolors

# ---------------------------------------------------------------- materials / palette
M_SOLID, M_WALL, M_GLASS, M_LEAF, M_WATER, M_LAMP, M_METAL, M_FLOODLIT, M_GRASS, M_MARK, M_SOIL, M_CAR, M_ROOF, M_CONCRETE, M_CLOCK, M_BRONZE, M_SIGN = range(17)


class Palette:
    def __init__(self):
        self.entries = [(0, 0, 0, 0)]
        self.index = {}

    def __call__(self, rgb, mat=M_SOLID, q=4):
        if isinstance(rgb, str):
            rgb = hex_rgb(rgb)
        r, g, b = (min(255, int(round(v / q)) * q) for v in rgb)
        key = (r, g, b, mat)
        if key not in self.index:
            self.index[key] = len(self.entries)
            self.entries.append(key)
        return self.index[key]


def hex_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


COLOUR_ALIASES = {"#e37b42": "#cf9a5e",  # (Hale Mirowskie's ~200 parts, the only use: their brick is ochre-yellow in photos)
                  "grey": "gray", "lightgrey": "lightgray", "darkgrey": "darkgray", "cream": "#f1e9d2",
                  "sand": "#d8c79f", "beige": "#ddd2b8", "brick": "#a5553f", "terracotta": "#c0623f",
                  "glass": "#9fb5c2", "concrete": "#b8b5ae", "gold": "#cfae5c", "bronze": "#8c6c47",
                  "copper": "#5f9c87", "ochre": "#cc9a4a", "salmon": "#e19a85", "pink": "#e6b3b3",
                  "white": "#efede6", "black": "#3a3a3d", "red": "#b5513f", "brown": "#7e5a43",
                  "yellow": "#e3c86a", "green": "#6e9a5e", "blue": "#6c8cad", "orange": "#d98b4e",
                  "silver": "#c3c6c9", "gray": "#9a9a9a", "darkgray": "#6e6f72", "lightgray": "#cfcfcc"}


def parse_colour(s):
    if not s:
        return None
    s = s.split(";")[0].strip().lower().replace(" ", "")
    s = COLOUR_ALIASES.get(s, s)
    s = COLOUR_ALIASES.get(s, s)
    try:
        rgb = hex_rgb(s) if re.fullmatch(r"#?[0-9a-f]{6}|#?[0-9a-f]{3}", s) else hex_rgb(webcolors.name_to_hex(s))
    except ValueError:
        return None
    # building paint is never neon: a kiosk tagged "red" was #ff0000, a roof "lime" #00ff00 -- cap the saturation at
    # 0.62 (a deep brick red, a strong but real green) and keep hue and lightness
    h_, l_, s_ = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    if s_ > 0.62 and 0.12 < l_ < 0.9:
        rgb = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h_, l_, 0.62))
    return rgb


def parse_len(s):
    if s is None:
        return None
    m = re.match(r"\s*(-?[0-9]+(?:[.,][0-9]+)?)", str(s))
    return float(m.group(1).replace(",", ".")) if m else None


def soften(rgb, amt=0.12):
    """MagicaVoxel-ish grading: pull slightly toward warm light grey, keep hue."""
    return tuple(v * (1 - amt) + w * amt for v, w in zip(rgb, (226, 220, 208)))


def stable_hash(*a):
    return int(hashlib.md5("/".join(map(str, a)).encode()).hexdigest()[:8], 16)


pal = Palette()
C = {  # ground & misc palette (MagicaVoxel-like pastel)
    "paving": pal("#c6c2b8"), "paving2": pal("#b5b4af"), "asphalt": pal("#5f636b"), "asphalt_l": pal("#6e7178"),
    "sett": pal("#8f8981"), "road_paving": pal("#a49f97"), "tartan": pal("#b3604c"), "court": pal("#4f8db3"), "concrete": pal("#bdbab2"), "cycle": pal("#8a5a52"), "gravel": pal("#d8ccb5"),
    "grass": pal("#86b45a", M_GRASS), "grass2": pal("#79a852", M_GRASS), "garden": pal("#73a34e", M_GRASS),
    "scrub": pal("#5f8f45", M_LEAF), "flower": pal("#d98fb3", M_GRASS), "flower2": pal("#e8c25e", M_GRASS),
    "dirt": pal("#a58a66"), "dirt2": pal("#8e7455"), "fresh": pal("#93865a", M_GRASS),
    "ballast": pal("#8a8178"), "rail": pal("#55575d", M_METAL), "trambed": pal("#a9a59c"),
    "platform": pal("#b7b1a6"), "water": pal("#68654f", M_WATER), "mark": pal("#f1efe8", M_MARK),
    "bare": pal("#a8977c", M_SOIL),  # lawns before their grass arrives (tiles.py: grass is its own file)
    "soil": pal("#7a5c45", M_SOIL), "trunk": pal("#6b4f3a"), "lamp": pal("#ffe2a8", M_LAMP),
    "pole": pal("#3a3e42", M_METAL),
    "lampiron": pal("#2b3a33", M_METAL), "lampbase": pal("#24272a", M_METAL),  # Madrid's dark green cast-iron lamps
    "steps": pal("#a8a296"), "hatch": pal("#d9c860", M_MARK),
    "fence": pal("#dfe3e6", M_METAL), "crane": pal("#e7b23c", M_METAL), "crane_d": pal("#3d4249", M_METAL),
    "shelter": pal("#a9c3cf", M_GLASS), "deck": pal("#a7a49d", M_CONCRETE), "parking": pal("#6a6d73"),
    "track": pal("#b8875a"), "kerb": pal("#cfc7b8"), "granite_d": pal("#55595c"), "woodfloor": pal("#6b5847"), "jet": pal("#dff1f7", 17),
    "benchkerb": pal("#dcd9d1", M_CONCRETE),
}
PERENNIALS = [pal(c, M_LEAF) for c in ["#8e6fae", "#a690c4", "#6f9a4f", "#8aa27a", "#5f8a49", "#7c9c5a", "#c98fb0"]]
LEAVES = [pal(c, M_LEAF) for c in ["#a3c65c", "#8db552", "#76a24a", "#618f43", "#4f7c3c",
                                    "#93bb6a", "#7da95f", "#689655", "#56834c", "#456f43"]]
# Central Madrid's materials (Phase 4), shades per material; a building takes one by a stable hash of its id.
# Roofs: Arab clay tile (most roofs), slate (Madrid de los Austrias' spires and mansards, palaces), zinc (19th-century
# mansards), flat terraces (azoteas, light grey-beige). Walls: light render (revoco: cream, ochre, pale yellow, warm
# white, salmon), exposed brick (ladrillo visto, neo-mudejar and post-war housing), granite (berroquena, monuments).
ROOF_TILE = ["#b0603f", "#a65a3c", "#b96b49"]
ROOF_SLATE = ["#4f545a", "#5a5f65"]
ROOF_ZINC = ["#8d9397", "#999fa3"]
ROOF_TERRACE = ["#bbb4a8", "#c5bfb3", "#aea89d"]
ROOF_SHADES = {"tile": ROOF_TILE, "slate": ROOF_SLATE, "zinc": ROOF_ZINC, "terrace": ROOF_TERRACE}
# OSM roof:material -> one of the above
ROOF_MATERIALS = {"roof_tiles": "tile", "tile": "tile", "tiles": "tile", "slate": "slate", "metal": "zinc", "zinc": "zinc",
                  "tin": "zinc", "copper": None, "concrete": "terrace", "gravel": "terrace", "asphalt": "terrace",
                  "tar_paper": "terrace", "stone": "terrace"}
WALL_RENDER = ["#e8dcc2", "#e3cfa3", "#ead9b0", "#efe6d2", "#dcc39a", "#e7c9a6", "#d9b98f", "#f0e8d8"]
WALL_BRICK = ["#a85f42", "#b36b4b", "#9d5a40"]
WALL_GRANITE = ["#a9a69e", "#b3b0a8"]
# Madrid de los Austrias: Madrid red (almagre), ochre, cream and brick
AUSTRIAS_WALLS = ["#9e4a32", "#b5643f", "#d1a15e", "#e2cfa6", "#c58a52", "#a85f42"]
WALL_DEFAULTS = WALL_RENDER + WALL_BRICK  # about one building in four of exposed brick
