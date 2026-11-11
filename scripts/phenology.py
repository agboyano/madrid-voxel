"""When each kind of tree leafs out, colours and drops its leaves, for Madrid's commonest trees.

Classes: the 13 commonest deciduous genera of the municipal inventory (Platanus, Styphnolobium, Aesculus, Ulmus,
Celtis, Acer, Prunus, Robinia + Gleditsia, Populus + Salix, Melia, Fraxinus, Pyrus, Tilia), the purple-leaved plum
(Prunus cerasifera) on its own, the other deciduous trees together, and the evergreens (conifers, the evergreen
broadleaves Madrid plants: privet, holm oak, olive, magnolia..., and the cherry laurels).

Dates: iNaturalist's "Leaves" annotations (breaking buds, green, coloured) on observations in regions with Madrid's
climate (INAT_PLACES), per week of the year; a class can be queried by one species (INAT_TAXON) or without one
(INAT_WITHOUT). Leaf-out: the mean day of breaking buds; colouring: the day coloured observations outnumber green
ones; leaf fall: colouring plus GAP days. A phase the source does not give takes the median over the classes. The
spread between trees in one year (SD) is the one measured on Warsaw's DWD series: iNaturalist gives no per-tree spread.

Autumn colours: measured on Wikimedia Commons photos of each taxon's canopy (scripts/foliage_photos.json: the method,
the photos, the medians): Warsaw's where a Madrid class shares the genus (Acer, Tilia, Fraxinus, Robinia, Populus,
Aesculus), Madrid's own (scripts/foliage_measure.py) for Platanus, Styphnolobium, Ulmus, Celtis and Melia; the others
take their median. The renderer keeps its own summer greens, so all autumn colours are scaled by how much brighter
those greens are than the photos' summer canopies. The purple plum's measured summer colour is its base tint on the
greens all season.

Lawns through the year: irrigated lawns and dry meadows from Sentinel-2 (scripts/lawns_s2.py), a factor per month on
the palette's grass green for each: the satellite's change per channel against irrigated lawns in summer, applied to
the summer lawn colour of the dated Commons photos (scripts/grass_photos.json), which alone give the months without
that file. Summer leaves: the photos' median summer canopy, as
one factor on the renderer's greens.

Output: web/public/data/phenology.json (per class: dates, spread, source, autumn colour, base tint) and, with the trees'
positions (web/public/data/trees.json), web/public/data/foliage.bin: per 2 m cell the class of the tree whose crown it
is in (nearest trunk within 9 m; the high bit set on a dry meadow), then a byte of that tree's index (so one tree turns
as one), gzip.
"""
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from aoi import AREA, D, RAW, W  # noqa: E402

# iNaturalist places with Madrid's climate (Koeppen Csa, BSk), Northern Hemisphere only: Spain, Portugal, Italy, Greece,
# Provence-Alpes-Cote d'Azur, Corsica, Cyprus, Turkey, Israel, Lebanon, Morocco, Tunisia, Algeria, California. Spain,
# Portugal and Italy alone had too few annotations; a 34-44 N band was tried and rejected (continental North America and
# China leaf out weeks later than Madrid). DECISIONS.md
INAT_PLACES = "6774,7122,6973,7094,96863,10574,10289,7183,6815,10299,7306,7312,7300,14"
INAT_REGIONS = "Mediterranean-climate regions"
INAT = ("https://api.inaturalist.org/v1/observations/histogram?place_id=" + INAT_PLACES +
        "&term_id=36&term_value_id={v}&interval=week_of_year&taxon_id={t}&verifiable=true{x}")
INAT_TAXA = "https://api.inaturalist.org/v1/taxa?q={q}"
UA = {"User-Agent": "madrid-voxel phenology"}
CACHE = Path(RAW) / "phenology"
OUT = Path(__file__).parent.parent / "web/public/data"
PHASES = ("leaf", "colour", "fall")
PHOTOS = Path(__file__).parent / "foliage_photos.json"
LAWNS = Path(__file__).parent / "grass_photos.json"
GRASS = "#86b45a"
MIN_LAWN_PIXELS = 50  # Sentinel-2 pixels a lawn class needs before its own colours are used (lawns_s2.py)
# the renderer's leaf greens (palette.py LEAVES)
GREENS = ["#a3c65c", "#8db552", "#76a24a", "#618f43", "#4f7c3c", "#93bb6a", "#7da95f", "#689655", "#56834c", "#456f43"]
GAP = 17  # days from colouring to leaf fall: the median gap in Warsaw's DWD series
SD = dict(leaf=8.0, colour=12.0, fall=11.0)  # spread between trees in one year, days (Warsaw's DWD series)
# class: genera it stands for (the first is looked up on iNaturalist). 0 = no tree here.
CLASSES = {
    1: ["Platanus"], 2: ["Styphnolobium", "Sophora"], 3: ["Aesculus"], 4: ["Ulmus"], 5: ["Celtis"], 6: ["Acer"],
    7: ["Prunus", "Malus"], 8: ["Robinia", "Gleditsia"], 9: ["Populus", "Salix"], 10: ["Melia"], 11: ["Fraxinus"],
    12: ["Pyrus"], 15: ["Tilia"], 16: ["Prunus cerasifera"],
}
OTHER, EVERGREEN = 13, 14  # deciduous trees with no class of their own (Morus, Catalpa, Koelreuteria, ...); evergreens
PURPLE_PLUM = 16  # Prunus cerasifera ('Pissardii' in Madrid): purple all season, so its own class with a base colour
# taxa a class's iNaturalist query leaves out: the purple plum is not counted with the other Prunus
INAT_WITHOUT = {7: ["Prunus cerasifera"]}
# classes queried on iNaturalist by one species rather than the genus: in California the genus Aesculus is the
# California buckeye, which leafs out in February and drops its leaves in the summer drought, unlike the horse chestnut
INAT_TAXON = {3: "Aesculus hippocastanum"}
# classes whose "coloured leaves" annotations do not mean autumn: the purple plum's leaves are coloured all summer
NO_COLOUR_SIGNAL = {PURPLE_PLUM}
# the class in foliage_photos.json measured for a class's genus: Warsaw's, then Madrid's (scripts/foliage_measure.py)
PHOTO_CLASS = {6: "1", 15: "2", 11: "3", 8: "4", 9: "6", 3: "7"}
MADRID_PHOTOS = {1: "platanus", 2: "styphnolobium", 4: "ulmus", 5: "celtis", 10: "melia"}
BASE_PHOTOS = {PURPLE_PLUM: "prunus_cerasifera"}  # classes whose summer canopy is not green: measured summer colour
CONIFERS = {"Pinus", "Cupressus", "Cedrus", "Picea", "Thuja", "Taxus", "Abies", "Juniperus", "Chamaecyparis",
            "Cupressocyparis", "Sequoiadendron", "Araucaria", "Platycladus"}
EVERGREEN_BROADLEAF = {"Ligustrum", "Olea", "Magnolia", "Laurus", "Arbutus", "Citrus", "Photinia", "Eriobotrya",
                       "Pittosporum", "Ceratonia", "Nerium", "Ilex", "Phillyrea", "Eucalyptus", "Schinus"}
EVERGREEN_OAKS = ("Quercus ilex", "Quercus rotundifolia", "Quercus suber", "Quercus coccifera")
EVERGREEN_SPECIES = EVERGREEN_OAKS + ("Prunus laurocerasus", "Prunus lusitanica")  # the cherry laurels keep their leaves


def fetch_json(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=UA)
        path.write_text(urllib.request.urlopen(req).read().decode())
        time.sleep(1.1)
    return json.loads(path.read_text())


def taxon_id(name):
    """iNaturalist id of a genus (one word) or a species ("Prunus cerasifera")."""
    rank = "genus" if " " not in name else "species"
    res = fetch_json(INAT_TAXA.format(q=urllib.parse.quote(name)), CACHE / f"taxon_{name.replace(' ', '_')}.json")["results"]
    return next(r["id"] for r in res if r["name"] == name and r["rank"] == rank)


def inat(taxon, without=()):
    h, x = {}, "".join(f"&without_taxon_id={t}" for t in without)
    places = INAT_PLACES.replace(",", "-") + "".join(f"_w{t}" for t in without)
    for v, key in ((37, "bud"), (38, "green"), (39, "coloured")):
        d = fetch_json(INAT.format(t=taxon, v=v, x=x), CACHE / f"inat_{taxon}_{v}_{places}.json")["results"]["week_of_year"]
        h[key] = np.array([d.get(str(w), 0) for w in range(1, 54)], float)
    doy, k3 = np.arange(53) * 7 + 4.0, np.ones(3) / 3
    g, c = np.convolve(h["green"], k3, "same"), np.convolve(h["coloured"], k3, "same")
    share, out = c / np.maximum(g + c, 1e-9), {}
    for i in range(29, 52):
        if share[i] < 0.5 <= share[i + 1] and h["coloured"].sum() >= 20:
            out["colour"] = dict(day=float(doy[i] + (0.5 - share[i]) / (share[i + 1] - share[i]) * 7), n=int(h["coloured"].sum()))
            break
    if h["bud"].sum() >= 10:
        out["leaf"] = dict(day=float((h["bud"] * doy).sum() / h["bud"].sum()), n=int(h["bud"].sum()))
    return out


def phenology():
    table = {}
    for k, genera in CLASSES.items():
        nat = inat(taxon_id(INAT_TAXON.get(k, genera[0])), [taxon_id(t) for t in INAT_WITHOUT.get(k, ())])
        if k in NO_COLOUR_SIGNAL:
            nat.pop("colour", None)
        row = dict(species=genera[0], genera=genera)
        for ph in ("leaf", "colour"):
            row[ph] = dict(day=nat[ph]["day"], sd=SD[ph], n=nat[ph]["n"], source=f"iNaturalist ({INAT_REGIONS})") if ph in nat else None
        row["fall"] = dict(day=row["colour"]["day"] + GAP, sd=SD["fall"], n=0, source=f"colouring + {GAP} d") if row["colour"] else None
        table[k] = row
    med = {ph: dict(day=float(np.median([v[ph]["day"] for v in table.values() if v[ph]])), sd=SD[ph], n=0,
                    source="median of the classes") for ph in PHASES}
    for v in table.values():
        v.update({ph: v[ph] or med[ph] for ph in PHASES})
    table[OTHER] = dict(species="median of the classes", genera=[], **med)
    table[EVERGREEN] = dict(species="evergreens", genera=sorted(CONIFERS | EVERGREEN_BROADLEAF), leaf=None, colour=None, fall=None)
    autumn, base = autumn_colours()
    for k in table:
        if k != EVERGREEN:  # a class with no photos of its own takes the median of those measured
            table[k]["autumn"] = autumn.get(k, autumn[OTHER])
        if k in base:
            table[k]["base"] = base[k]
    for k in sorted(table):
        v = table[k]
        print(k, v["species"], v.get("autumn"), {ph: (round(v[ph]["day"]), v[ph]["source"][:11]) for ph in PHASES if v[ph]})
    return table


def linear(hex_):
    c = np.array([int(hex_[i:i + 2], 16) for i in (1, 3, 5)]) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0, 1)
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return "#" + "".join(f"{round(v * 255):02x}" for v in c)


def leaf_tint():
    photos = json.load(open(PHOTOS))
    summer = np.median([linear(photos[p]["summer_lit_hex"]) for p in PHOTO_CLASS.values()], axis=0)
    greens = np.mean([linear(h) for h in GREENS], axis=0)
    return [round(float(v), 3) for v in summer * lawns()[1] / greens]


def autumn_colours():
    """Autumn colour per class at the renderer's brightness, and the base tint of classes whose summer canopy is not
    green (on the renderer's greens: the measured summer colour over the photos' median green summer canopy)."""
    photos = json.load(open(PHOTOS))
    lum = lambda c: float(c @ [0.2126, 0.7152, 0.0722])
    summer = np.median([linear(photos[p]["summer_lit_hex"]) for p in PHOTO_CLASS.values()], axis=0)
    k_ = np.mean([lum(linear(h)) for h in GREENS]) / lum(summer)
    out = {k: srgb(linear(photos[p]["autumn_lit_hex"]) * k_) for k, p in {**PHOTO_CLASS, **MADRID_PHOTOS}.items()}
    out[OTHER] = srgb(np.median([linear(c) for c in out.values()], axis=0))
    base = {}
    for k, p in BASE_PHOTOS.items():
        own = linear(photos[p]["summer_lit_hex"])
        base[k] = [round(float(v), 3) for v in own / summer]
        out[k] = srgb(own * k_)  # it drops its leaves without turning: its autumn colour is its summer one
    return out, base


def lum(c):
    return float(c @ [0.2126, 0.7152, 0.0722])


def lab_to_linear(L, a, b):
    fy = (L + 16) / 116
    f = np.array([fy + a / 500, fy, fy - b / 200])
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * [0.95047, 1.0, 1.08883]
    return np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]) @ xyz


def lawns():
    photos = json.load(open(LAWNS))["photos"]
    lab = np.array([np.median([p["lit_lab"] for p in photos if p["month"] == m], axis=0) for m in range(1, 13)])
    lab = 0.25 * np.roll(lab, 1, 0) + 0.5 * lab + 0.25 * np.roll(lab, -1, 0)
    lin = np.array([lab_to_linear(*v) for v in lab])
    k = lum(linear(GRASS)) / np.mean([lum(lin[m]) for m in (5, 6, 7)])
    return lin, k


def grass_tints():
    """Per month, the factor on the palette's grass green: irrigated lawns and dry meadows from Sentinel-2
    (lawns_s2.py), both at the renderer's brightness for irrigated lawns in summer; Warsaw's photos without it."""
    s2 = AREA / "lawns_s2.json"
    if not s2.exists():
        lin, k = lawns()
        t = [[round(float(v), 3) for v in lin[m] * k / linear(GRASS)] for m in range(12)]
        return t, t
    # Sentinel-2's surface reflectance is bluer and duller than a photo, so it gives only the changes: each month and
    # the dry meadows relative to irrigated lawns in summer, per channel, on the photos' summer lawn colour
    d = json.loads(s2.read_text())
    series = {c: np.array(v) for c, v in d["linear_rgb"].items()}
    ref = series["irrigated"][[5, 6, 7]].mean(0)
    lin, k = lawns()
    photo = lin[[5, 6, 7]].mean(0) * k / linear(GRASS)
    tint = lambda c: [[round(float(v), 3) for v in series[c][m] / ref * photo] for m in range(12)]  # noqa: E731
    dry_ok = d["pixels"]["dry"] >= MIN_LAWN_PIXELS  # too few dry meadows measured: every lawn follows the irrigated one
    return tint("irrigated"), tint("dry" if dry_ok else "irrigated")


def city_median(table, cls, ph):
    # the day by which half of the city's deciduous trees have reached a phase
    days = [(table[k][ph]["day"], int((cls == k).sum())) for k in table if table[k][ph]]
    d, w = np.array(days).T
    o = np.argsort(d)
    return round(float(d[o][np.searchsorted(np.cumsum(w[o]), w.sum() / 2)]))


def classify(t):
    sp = t.get("sp") or ""
    genus = sp.split(" ")[0]
    if genus in CONIFERS or genus in EVERGREEN_BROADLEAF or sp.startswith(EVERGREEN_SPECIES):
        return EVERGREEN
    if sp.startswith("Prunus cerasifera"):
        return PURPLE_PLUM
    for k, genera in CLASSES.items():
        if genus in genera:
            return k
    return OTHER


def check(table):
    """Every deciduous class leafs out, colours and drops its leaves in that order, within the year; evergreens do none."""
    for k, v in table.items():
        if k == EVERGREEN:
            assert not any(v[ph] for ph in PHASES), v
            continue
        d = [v[ph]["day"] for ph in PHASES]
        assert d[0] < d[1] < d[2] <= 365, (k, v["species"], d)
        assert d[1] <= 340, (k, v["species"], "colours too late", d[1])


def main():
    table = phenology()
    check(table)
    trees = json.load(open(OUT / "trees.json"))["trees"]
    cls = np.array([classify(t) for t in trees], np.uint8)
    city = {ph: city_median(table, cls, ph) for ph in PHASES}
    grass, grass_dry = grass_tints()
    print("city medians:", city)
    lawn_src = ("lawns by month: Copernicus Sentinel-2 L2A via the Microsoft Planetary Computer, scripts/lawns_s2.py"
                if (AREA / "lawns_s2.json").exists() else "lawns by month: Wikimedia Commons photos, scripts/grass_photos.json")
    json.dump(dict(city=city, sources=[f"iNaturalist: Leaves annotations, {INAT_REGIONS}",
                            "spread between trees and leaf-fall gap: Warsaw's DWD series (warsaw-vibe-voxel)",
                            "autumn colours: Wikimedia Commons photos, scripts/foliage_photos.json", lawn_src],
                   classes=table, grass=grass, grass_dry=grass_dry, leaf=leaf_tint()), open(OUT / "phenology.json", "w"), indent=1, ensure_ascii=False)

    xy = np.array([(t["x"], t["y"]) for t in trees])
    print("trees per class:", {int(k): int((cls == k).sum()) for k in np.unique(cls)})
    gx, gy = np.meshgrid(np.arange(W // 2) * 2 + 1, np.arange(D // 2) * 2 + 1)
    dist, idx = cKDTree(xy).query(np.c_[gx.ravel(), gy.ravel()], distance_upper_bound=9)
    ok = np.isfinite(dist)
    idx = np.minimum(idx, len(cls) - 1)
    grid = np.where(ok, cls[idx], 0).astype(np.uint8).reshape(gy.shape)
    dry = AREA / "lawns_s2.npz"  # the high bit of the class byte: an unwatered meadow (lawns_s2.py); classes stay < 128
    if dry.exists():
        grid |= np.load(dry)["dry"].astype(np.uint8) << 7
    tree = np.where(ok, (idx * 2654435761 >> 13) & 255, 0).astype(np.uint8).reshape(gy.shape)
    (OUT / "foliage.bin").write_bytes(gzip.compress(grid.tobytes() + tree.tobytes(), 9, mtime=0))
    print("foliage grid", grid.shape, "cells with a class:", int((grid > 0).sum()))


if __name__ == "__main__":
    main()
