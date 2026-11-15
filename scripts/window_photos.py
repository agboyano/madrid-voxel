"""Night photos of Madrid on Wikimedia Commons for counting lit windows by eye -> scripts/window_photos.json, and the
photos themselves in $MADRID_CACHE/raw/window_photos/ (scripts/window_stats.py reads the counts made on them).

Candidates: files within 3 km of the map's centre whose text says night (night, noche, nocturna), and the files of the
Commons categories of Madrid's streets, squares and cityscapes at night (two levels of subcategories). Kept: a photo
with its camera time in the EXIF, taken with the sun at least 4 degrees under the horizon (the camera time read as
Madrid's local time), and, where it has coordinates, taken inside the map. Each record has the weekday and the sun's
elevation, so that window_stats.py can bin them.

usage: PYTHONPATH=scripts uv run python scripts/window_photos.py
"""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from aoi import CACHE, D, W, grid_to_lonlat, to_grid
from osm import _T as LONLAT_TO_UTM

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "madrid-voxel/0.1 (https://github.com/agboyano/madrid-voxel)"}
WORDS = ("night", "noche", "nocturna")
CATEGORIES = ["Streets in Madrid at night", "Night cityscapes of Madrid", "Urban squares in Madrid at night",
              "Blue hour in Madrid", "Illuminated buildings in Madrid"]
SUN_MAX = -4.0  # degrees: darker than this, the windows' light shows
DIR = CACHE / "raw" / "window_photos"
OUT = Path(__file__).with_name("window_photos.json")


def get(**params):
    return requests.get(API, params=dict(format="json", **params), headers=UA, timeout=60).json()


def search(q):
    titles, cont = [], {}
    while True:
        r = get(action="query", list="search", srnamespace=6, srlimit=500, srsearch=q, **cont)
        titles += [s["title"] for s in r["query"]["search"]]
        if "continue" not in r:
            return titles
        cont = r["continue"]


def category(cat, depth=2):
    titles, subs, cont = [], [], {}
    while True:
        r = get(action="query", list="categorymembers", cmtitle="Category:" + cat, cmlimit=500, cmtype="file|subcat", **cont)
        for m in r["query"]["categorymembers"]:
            (subs if m["ns"] == 14 else titles).append(m["title"])
        if "continue" not in r:
            break
        cont = r["continue"]
    if depth > 0:
        for s in subs:
            titles += category(s[9:], depth - 1)
    return titles


def sun_elevation(t_utc, lon, lat):
    """The sun's elevation in degrees (NOAA's approximation, good to a fraction of a degree)."""
    d = (t_utc - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = (280.459 + 0.98564736 * d) % 360
    L = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    e = math.radians(23.439 - 0.00000036 * d)
    ra, dec = math.atan2(math.cos(e) * math.sin(L), math.cos(L)), math.asin(math.sin(e) * math.sin(L))
    gmst = (18.697374558 + 24.06570982441908 * d) % 24
    ha = math.radians(gmst * 15 + lon) - ra
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def madrid_utc(local):
    """Madrid's clock to UTC: CET, CEST from the last Sunday of March to the last Sunday of October (01:00 UTC)."""
    def last_sunday(y, m):
        d = datetime(y, m + 1, 1) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    y = local.year
    start, end = last_sunday(y, 3).replace(hour=2), last_sunday(y, 10).replace(hour=3)
    return (local - timedelta(hours=2 if start <= local < end else 1)).replace(tzinfo=timezone.utc)


def main():
    lon0, lat0 = grid_to_lonlat(W / 2, D / 2)
    titles = set()
    for w in WORDS:
        titles |= set(search(f"nearcoord:3km,{lat0:.4f},{lon0:.4f} {w}"))
    for c in CATEGORIES:
        titles |= set(category(c))
    titles = sorted(titles)
    print("candidates:", len(titles))
    keep = []
    for k in range(0, len(titles), 50):
        r = get(action="query", titles="|".join(titles[k:k + 50]), prop="imageinfo|coordinates",
                iiprop="url|extmetadata|size", iiurlwidth=1600, iiextmetadatafilter="DateTimeOriginal|ImageDescription")
        for p in r["query"]["pages"].values():
            ii = (p.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata") or {}
            em = em if isinstance(em, dict) else {}  # an empty list where a file has none
            raw = re.sub(r"<[^>]+>", "", str((em.get("DateTimeOriginal") or {}).get("value", "")))
            m = re.match(r"(\d{4})[:-](\d\d)[:-](\d\d)[ T](\d\d):(\d\d)", raw)
            if not m or not ii.get("thumburl"):
                continue
            yy, mo, dd, hh, mi = (int(v) for v in m.groups())
            local = datetime(yy, mo, dd, hh, mi)
            co = (p.get("coordinates") or [None])[0]
            if co:
                i, j = to_grid(*LONLAT_TO_UTM.transform(co["lon"], co["lat"]))
                if not (0 <= i < W and 0 <= j < D):
                    continue
            sun = sun_elevation(madrid_utc(local), lon0, lat0)
            if sun > SUN_MAX:
                continue
            keep.append(dict(title=p["title"], taken=local.isoformat(timespec="minutes"), weekday=local.strftime("%a"),
                             sun=round(sun, 1), thumb=ii["thumburl"], page=ii.get("descriptionurl"),
                             at=[round(co["lon"], 5), round(co["lat"], 5)] if co else None))
    keep.sort(key=lambda x: x["title"])
    DIR.mkdir(parents=True, exist_ok=True)
    for x in keep:
        x["file"] = hashlib.sha1(x["title"].encode()).hexdigest()[:12] + ".jpg"  # stable when the list changes
        path = DIR / x["file"]
        if not path.exists():
            path.write_bytes(requests.get(x["thumb"], headers=UA, timeout=120).content)
    OUT.write_text(json.dumps(keep, ensure_ascii=False, indent=0))
    print("night photos kept:", len(keep), "with coordinates:", sum(1 for x in keep if x["at"]))


if __name__ == "__main__":
    main()
