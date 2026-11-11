"""Measure a tree's autumn and summer canopy colours on Wikimedia Commons photos -> scripts/foliage_photos.json.

Warsaw's foliage_photos.json holds the results and, under "_method", how they were measured; this is that method
as a script, for the taxa Madrid needs and Warsaw never measured. Two steps, with a person (or a model) between them:

  candidates KEY TAXON SEASON   walk TAXON's Commons category tree (skipping bark, fruit, flowers, leaves, buds,
                                herbaria, illustrations, seedlings, wood, pollards), keep the photos taken in SEASON's months
                                (EXIF or metadata date: autumn Oct-Nov, summer Jun-Aug), cache 640 px thumbnails in
                                {RAW}/foliage_photos/ and write a numbered contact sheet to look at
  measure KEY                   measure the photos listed under KEY ("commons_autumn", "commons_summer": file pages
                                accepted from the sheet: the canopy of that taxon, no close-ups, no other cultivar)

Per image, as "_method" says: the top 75 % of the frame; sky (HSV hue 170-300, or V > 0.85 with S < 0.35), V < 0.15
and S < 0.2 dropped; "green" = CIELAB hue 103-220 deg. Autumn colour: the median of the non-green leaf pixels;
summer colour: the median of the green ones; "lit": the brighter half (by L*) of those pixels. Medians in CIELAB, per
image, then over the images. A taxon whose leaves are not green in summer (PURPLE, the purple-leaved plum) takes its
non-green leaf pixels in summer instead.

usage: PYTHONPATH=scripts uv run python scripts/foliage_measure.py candidates platanus "Platanus × hispanica" autumn
       PYTHONPATH=scripts uv run python scripts/foliage_measure.py measure platanus
"""
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from aoi import RAW

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "madrid-voxel foliage colours (https://github.com/agboyano/madrid-voxel)"}
CACHE = Path(RAW) / "foliage_photos"
PHOTOS = Path(__file__).parent / "foliage_photos.json"
MONTHS = {"autumn": (10, 11), "summer": (6, 7, 8)}
# subcategories of close-ups and parts, not canopies; cultivars stay (the purple plum is one) and are judged on the sheet
SKIP = re.compile(r"bark|fruit|flower|leaves|leaf|buds|herbari|illustration|seedling|wood|trunk|bole|label|nursery|"
                  r"bonsai|pollard", re.I)
PURPLE = {"prunus_cerasifera"}  # leaves purple all season: no green pixels to take in summer


def api(**params):
    body = urllib.parse.urlencode({**params, "format": "json"}).encode()  # POST: 50 titles overflow a GET URL
    out = json.loads(urllib.request.urlopen(urllib.request.Request(API, data=body, headers=UA), timeout=60).read())
    time.sleep(0.3)
    return out


def walk(category, depth=3, seen=None):
    """File titles in a category and its subcategories (minus the SKIP ones), depth levels down."""
    seen = set() if seen is None else seen
    if category in seen:
        return []
    seen.add(category)
    files, cont = [], {}
    while True:
        r = api(action="query", list="categorymembers", cmtitle=category, cmlimit=500, cmtype="file|subcat", **cont)
        for m in r["query"]["categorymembers"]:
            if m["ns"] == 6 and m["title"].lower().endswith((".jpg", ".jpeg")):
                files.append(m["title"])
            elif m["ns"] == 14 and depth > 0 and not SKIP.search(m["title"].split(":", 1)[1]):
                files += walk(m["title"], depth - 1, seen)
        if "continue" not in r:
            return files
        cont = {"cmcontinue": r["continue"]["cmcontinue"]}


def info(titles):
    """title -> (thumbnail url, month taken or None, file page url)."""
    out = {}
    for i in range(0, len(titles), 50):
        r = api(action="query", titles="|".join(titles[i:i + 50]), prop="imageinfo", iiprop="url|extmetadata",
                iiurlwidth=640)
        for p in r["query"]["pages"].values():
            ii = (p.get("imageinfo") or [None])[0]
            if not ii:
                continue
            meta = ii.get("extmetadata", {})
            date = (meta.get("DateTimeOriginal") or meta.get("DateTime") or {}).get("value", "")
            m = re.search(r"(?:19|20)\d\d[-:/](\d\d)", date)
            out[p["title"]] = (ii["thumburl"], int(m.group(1)) if m else None, ii["descriptionurl"])
    return out


def thumb(url):
    path = CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
        time.sleep(0.3)
    return Image.open(path).convert("RGB")


def candidates(key, taxon, season):
    titles = walk("Category:" + taxon)
    meta = info(sorted(set(titles)))
    keep = [(t, *v) for t, v in sorted(meta.items()) if v[1] in MONTHS[season]]
    print(f"{taxon}: {len(meta)} photos in the category tree, {len(keep)} taken in {season}", file=sys.stderr)
    cell, cols, per = 260, 6, 36  # sheets of 36 numbered photos, small enough to look at one by one
    listing = []
    for p0 in range(0, len(keep), per):
        part = keep[p0:p0 + per]
        sheet = Image.new("RGB", (cols * cell, -(-len(part) // cols) * cell), "white")
        draw = ImageDraw.Draw(sheet)
        for j, (_title, url, month, page) in enumerate(part):
            i = p0 + j
            im = thumb(url)
            im.thumbnail((cell - 4, cell - 24))
            x, y = (j % cols) * cell, (j // cols) * cell
            sheet.paste(im, (x + 2, y + 20))
            draw.text((x + 4, y + 4), f"{i}  m{month}", fill="black")
            listing.append(dict(i=i, page=page, month=month))
        out = CACHE / f"sheet_{key}_{season}_{p0 // per}.jpg"
        sheet.save(out, quality=85)
        print(out)
    (CACHE / f"sheet_{key}_{season}.json").write_text(json.dumps(listing, indent=1))


# ---------------------------------------------------------------- colour
def srgb_to_lab(rgb):
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= [0.95047, 1.0, 1.08883]
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def lab_to_hex(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    f = np.array([fy + a / 500, fy, fy - b / 200])
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * [0.95047, 1.0, 1.08883]
    lin = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]) @ xyz
    lin = np.clip(lin, 0, 1)
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return "#" + "".join(f"{round(v * 255):02x}" for v in s)


def leaf_pixels(im):
    """Lab of the leaf pixels in the top 75 % of the frame, and which of them are green."""
    a = np.asarray(im, np.float64)
    a = a[: int(a.shape[0] * 0.75)].reshape(-1, 3)
    mx, mn = a.max(1), a.min(1)
    v, s = mx / 255, np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    d = np.maximum(mx - mn, 1e-9)
    r, g, b = a.T
    h = np.select([mx == r, mx == g], [(g - b) / d % 6, (b - r) / d + 2], (r - g) / d + 4) * 60
    sky = ((h >= 170) & (h <= 300)) | ((v > 0.85) & (s < 0.35))
    keep = ~sky & (v >= 0.15) & (s >= 0.2)
    lab = srgb_to_lab(a[keep])
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    return lab, (hue >= 103) & (hue <= 220)


def medians(labs):
    """Median Lab and median of the brighter half, per image, then over the images."""
    per, lit = [], []
    for lab in labs:
        if len(lab) < 200:
            continue
        per.append(np.median(lab, 0))
        lit.append(np.median(lab[lab[:, 0] >= np.median(lab[:, 0])], 0))
    return np.median(per, 0), np.median(lit, 0), len(per)


def measure(key):
    photos = json.loads(PHOTOS.read_text())
    e = photos[key]
    pages = {s: e.get(f"commons_{s}", []) for s in MONTHS}
    thumbs = {}
    for s, urls in pages.items():
        titles = [urllib.parse.unquote(u.rsplit("/wiki/", 1)[1]).replace("_", " ") for u in urls]
        meta = info(titles)
        thumbs[s] = [thumb(meta[t][0]) for t in titles if t in meta]
    aut = [leaf_pixels(im) for im in thumbs["autumn"]]
    summ = [leaf_pixels(im) for im in thumbs["summer"]]
    if aut:
        med, lit, n = medians([lab[~green] for lab, green in aut])
        e.update(autumn_hex=lab_to_hex(med), autumn_lit_hex=lab_to_hex(lit), autumn_measure="non-green leaf pixels",
                 autumn_lab=[round(float(v), 1) for v in med], n_photos_autumn=n,
                 green_fraction_autumn=round(float(np.median([g.mean() for _, g in aut])), 3))
    if summ:
        # the purple plum's leaves are the non-green pixels (the green ones are the trees and lawn behind it)
        take = (lambda lab, green: lab[~green]) if key in PURPLE else (lambda lab, green: lab[green])
        med, lit, n = medians([take(lab, green) for lab, green in summ])
        e.update(summer_hex=lab_to_hex(med), summer_lit_hex=lab_to_hex(lit),
                 summer_lab=[round(float(v), 1) for v in med], n_photos_summer=n,
                 summer_measure="non-green leaf pixels" if key in PURPLE else "green leaf pixels")
    PHOTOS.write_text(json.dumps(photos, indent=1, ensure_ascii=False) + "\n")
    print(key, {k: v for k, v in e.items() if not k.startswith("commons_")})


if __name__ == "__main__":
    if sys.argv[1] == "candidates":
        candidates(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        measure(sys.argv[2])
