"""Madrid's own daily rhythm for the street life: how busy the streets are at each hour, from the Ayuntamiento's
counters, for weekdays and for weekends and holidays -> web/public/data/life.json (read by web/src/sim/life.ts).

cars  the traffic measurement points (Tráfico. Histórico de datos del tráfico desde 2013, datos.madrid.es): every
      urban point inside the AOI, its vehicles per hour every 15 minutes over one month. Each point's hourly means are
      divided by that point's own busiest hour of the weekday, so busy avenues and quiet streets weigh alike, and the
      median over the points is the profile, scaled so that the busiest weekday hour is 1. Points with errors flagged,
      or with fewer than 20 valid days, are left out.
peds  the permanent pedestrian counters (Aforos de peatones y bicicletas, datos.madrid.es), one count per hour, over a
      whole year: the same per-counter shape and median.
bikes the permanent bike counters of the same dataset, likewise, plus `month`: each month's mean daily count over the
      busiest month's, per counter, median over the counters (the counters' year, not Warsaw's).
The counters' `hora` is taken as the start of the hour it counts (their files have 0:00 to 23:00).

The month's file covers the whole city (about 95 MB zipped, 800 MB of CSV) and cannot be asked for by area; it is
downloaded once into $MADRID_CACHE/raw/traffic/ and read as a stream.

usage: PYTHONPATH=scripts uv run python scripts/life_profiles.py
"""
import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import requests

from aoi import CACHE, D, W, to_grid
from osm import _T as _LONLAT_TO_UTM

MONTH = "10-2026"  # October: a working month, no summer or Christmas holidays
COUNTERS_YEAR = 2023  # the last whole year of the pedestrian and bike counters
COUNTERS = {"peds": "300321-2-aforos-peatones-bicicletas-csv.csv", "bikes": "300321-11-aforos-peatones-bicicletas-csv.csv"}
COUNTERS_PKG = "300321-0-aforos-peatones-bicicletas"
# public holidays in Madrid (national, Comunidad de Madrid and the city's): counted as weekends
HOLIDAYS = {date(2026, 10, 12)} | {date(2023, m, d) for m, d in ((1, 1), (1, 6), (4, 6), (4, 7), (5, 1), (5, 2), (5, 15),
                                                                  (8, 15), (10, 12), (11, 1), (11, 9), (12, 6), (12, 8),
                                                                  (12, 25))}
API = "https://datos.madrid.es/api/3/action/package_show?id="
COUNTS_PKG, POINTS_PKG = "208627-0-transporte-ptomedida-historico", "202468-0-intensidad-trafico"
DIR = CACHE / "raw" / "traffic"
OUT = Path(__file__).resolve().parent.parent / "web/public/data/life.json"


def fetch(pkg, suffix):
    """A resource of a datos.madrid.es dataset by the end of its URL, downloaded once."""
    path = DIR / suffix
    if not path.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        url = next(r["url"] for r in requests.get(API + pkg, timeout=60).json()["result"]["resources"] if r["url"].endswith(suffix))
        with requests.get(url, stream=True, timeout=900) as r:
            r.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
    return path


def aoi_points():
    """Urban measurement points inside the grid: id -> name."""
    pts = {}
    with open(fetch(POINTS_PKG, f"pmed_ubicacion_{MONTH}.csv"), encoding="latin-1") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            if row["tipo_elem"] != "URB":
                continue
            i, j = to_grid(float(row["utm_x"]), float(row["utm_y"]))
            if 0 <= i < W and 0 <= j < D:
                pts[int(row["id"])] = row["nombre"]
    return pts


def daytype(d):
    return "weekend" if d.weekday() >= 5 or d in HOLIDAYS else "weekday"


def car_profiles(pts):
    """Per point and day: the hour's mean of the valid 15-minute readings; then the median shape over the points."""
    acc = defaultdict(lambda: np.zeros((2, 24)))  # (point, day) -> sums, counts per hour
    with zipfile.ZipFile(fetch(COUNTS_PKG, f"{MONTH}.zip")) as z, z.open(f"{MONTH}.csv") as raw:
        rows = csv.reader(io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";")
        next(rows)
        for pid, when, _typ, flow, _occ, _load, _speed, err, _per in rows:
            pid = int(pid)
            if pid not in pts or err != "N":
                continue
            day, hh = date.fromisoformat(when[:10]), int(when[11:13])
            a = acc[pid, day]
            a[0, hh] += float(flow)
            a[1, hh] += 1
    per = defaultdict(lambda: {"weekday": [], "weekend": []})
    for (pid, day), a in acc.items():
        if (a[1] >= 3).all():  # every hour of the day measured
            per[pid][daytype(day)].append(a[0] / a[1])
    shapes = {"weekday": [], "weekend": []}
    for pid, days in per.items():
        if len(days["weekday"]) + len(days["weekend"]) < 20:
            continue
        wk = np.mean(days["weekday"], axis=0)
        peak = wk.max()
        if peak <= 0:
            continue
        shapes["weekday"].append(wk / peak)
        if days["weekend"]:
            shapes["weekend"].append(np.mean(days["weekend"], axis=0) / peak)
    med = {k: np.median(s, axis=0) for k, s in shapes.items()}
    top = med["weekday"].max()  # the busiest weekday hour is 1: the viewer's full density
    return {k: [round(float(v / top), 3) for v in m] for k, m in med.items()}, len(shapes["weekday"])


def _coord(s, whole):
    """The counters' coordinates carry dots as thousands separators ("40.417.386"): `whole` digits before the point."""
    neg, digits = s.startswith("-"), re.sub(r"[^0-9]", "", s)
    v = float(digits[:whole] + "." + digits[whole:])
    return -v if neg else v


def counter_profiles(name):
    """The hourly counters of one kind inside the AOI: the median shape per day type, and the month factors."""
    hours = defaultdict(lambda: np.zeros((2, 24)))  # (station, day) -> sums, counts per hour
    inside = {}
    with open(fetch(COUNTERS_PKG, COUNTERS[name]), encoding="utf-8-sig") as fh:
        rows = csv.reader(fh, delimiter=";")
        next(rows)
        for row in rows:
            sid = row[2]
            if sid not in inside:
                i, j = to_grid(*_LONLAT_TO_UTM.transform(_coord(row[10], 1), _coord(row[9], 2)))
                inside[sid] = 0 <= i < W and 0 <= j < D
            if not inside[sid] or not row[3].strip():
                continue
            dd, mm, yy = (int(v) for v in row[0].split(" ")[0].split("/"))
            day, hh = date(yy, mm, dd), int(row[1].split(":")[0])
            if yy != COUNTERS_YEAR:
                continue
            a = hours[sid, day]
            a[0, hh] += float(row[3])
            a[1, hh] += 1
    per = defaultdict(lambda: {"weekday": [], "weekend": [], "months": defaultdict(list)})
    for (sid, day), a in hours.items():
        if (a[1] >= 1).all():
            h = a[0] / a[1]
            per[sid][daytype(day)].append(h)
            per[sid]["months"][day.month].append(h.sum())
    shapes, months = {"weekday": [], "weekend": []}, []
    for sid, d in per.items():
        if len(d["weekday"]) < 60:
            continue
        wk = np.mean(d["weekday"], axis=0)
        if wk.max() <= 0:
            continue
        shapes["weekday"].append(wk / wk.max())
        shapes["weekend"].append(np.mean(d["weekend"], axis=0) / wk.max())
        mon = np.array([np.mean(d["months"][m]) if len(d["months"][m]) >= 10 else np.nan for m in range(1, 13)])
        months.append(mon / np.nanmax(mon))
    med = {k: np.median(v, axis=0) for k, v in shapes.items()}
    top = med["weekday"].max()
    out = {k: [round(float(x / top), 3) for x in m] for k, m in med.items()}
    mon = np.nanmedian(months, axis=0)
    out["month"] = [round(float(x / np.nanmax(mon)), 3) for x in mon]
    return out, len(shapes["weekday"]), sum(inside.values())


def main():
    pts = aoi_points()
    cars, n = car_profiles(pts)
    print(f"cars: {n} of {len(pts)} urban points in the AOI")
    for k, v in cars.items():
        print(f"  {k}: " + " ".join(f"{x:.2f}" for x in v))
    out = json.load(open(OUT)) if OUT.exists() else {}
    out["cars"] = dict(cars, points=n, month=MONTH,
                       source="Ayuntamiento de Madrid, Tráfico. Histórico de datos del tráfico desde 2013 (datos.madrid.es)")
    for name in COUNTERS:
        prof, n, n_in = counter_profiles(name)
        print(f"{name}: {n} of {n_in} counters in the AOI")
        for k, v in prof.items():
            print(f"  {k}: " + " ".join(f"{x:.2f}" for x in v))
        if name == "peds":
            del prof["month"]  # the viewer keeps the pedestrians' numbers the same all year
        out[name] = dict(prof, counters=n, year=COUNTERS_YEAR,
                         source="Ayuntamiento de Madrid, Aforos de peatones y bicicletas (datos.madrid.es)")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
