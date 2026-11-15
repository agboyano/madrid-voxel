"""Lit windows at night, from counts on dated Commons photos of Madrid (scripts/window_photos.py; each facade counted by
eye: windows visible, windows lit, type, pattern, colour of the light) and, for homes, the hour-by-hour rhythm of
Madrid's households from INE's Time Use Survey, into what the viewer draws.

Per building type:
  med[daytype][hour]: the share of lit windows at each clock hour (0-23, the value at the middle of the hour), weekdays
    and weekends.
    homes (residential, mixed): Madrid's rhythm -- the share of households with someone at home and awake, from the
      survey's diaries (Encuesta de Empleo del Tiempo 2009-2010, INE microdata, Comunidad de Madrid, weighted by
      household) -- times one level, the median over the counted facades of their share over the rhythm at their
      hour. The diary day runs from 06:00 to 06:00, so the small hours of a Saturday come from Friday's diaries.
    others: the median share in five clock-time bins (15-17, 18-19, 20-21, 22-23, 0-6), pulled toward the type's
      overall median where a bin has few facades (n / (n + 5) weight on the bin), and drawn between the bins' middles.
  shape: quantiles (0, 1/8, ... 1) of a facade's share divided by what its group predicts; a building's own habit
    picks a point on it, so some buildings stay dark and some fully lit, as in the photos.
  floors: share of facades lit in whole floors; colour: mean share of warm, neutral, cool light.

Input scripts/window_counts.json and the survey's microdata (downloaded once into $MADRID_CACHE/raw/eet/), output
web/public/data/windows.json.
"""
import io
import json
import statistics as st
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests

from aoi import CACHE

COUNTS = Path(__file__).with_name("window_counts.json")
OUT = Path(__file__).resolve().parent.parent / "web/public/data/windows.json"
EET = CACHE / "raw" / "eet" / "datos_emptiem0910.zip"
EET_URL = "https://www.ine.es/ftp/microdatos/emptiem/datos_emptiem0910.zip"
MADRID, SLEEP, HOME = "13", "011", "11"  # the survey's codes: Comunidad de Madrid, sleeping, at one's own home
TYPES = {"residential": ["residential", "mixed"], "office": ["office"], "hotel": ["hotel"], "public": ["public"],
         "religious": ["religious", "public"]}
HOMES = ("residential",)
BINS = [(15, 17), (18, 19), (20, 21), (22, 23), (0, 6)]
CENTRES = [16.5, 18.5, 20.5, 22.5, 27]  # the bins' middles, after-midnight hours counted from the evening before
PRIOR = 5


def bin_of(h):
    return next(i for i, (a, b) in enumerate(BINS) if a <= h <= b)


def quantiles(v, n=8):
    v = sorted(v)
    return [round(v[min(int(k / n * (len(v) - 1) + 0.5), len(v) - 1)], 3) for k in range(n + 1)]


def home_rhythm():
    """Madrid's households with someone at home and awake, share by clock hour, for the viewer's weekdays (Monday to
    Friday) and weekends (Saturday and Sunday)."""
    if not EET.exists():
        EET.parent.mkdir(parents=True, exist_ok=True)
        EET.write_bytes(requests.get(EET_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=600).content)
    with zipfile.ZipFile(EET) as z:
        hh = {}  # household -> its weight, for the Comunidad de Madrid's households
        for line in io.TextIOWrapper(z.open("DHOGAR.TXT"), encoding="latin-1"):
            if line[5:7] == MADRID:
                hh[line[0:5]] = float(line[21:37]) / 1e10
        awake, dow = defaultdict(lambda: np.zeros(144, bool)), {}
        for line in io.TextIOWrapper(z.open("DIARIO2.TXT"), encoding="latin-1"):
            h = line[0:5]
            if h not in hh:
                continue
            dow[h] = int(line[8])
            if line[20:22] == HOME and line[12:15] != SLEEP:
                awake[h][int(line[9:12]) - 1] = True  # 10-minute intervals from 06:00
            else:
                awake.setdefault(h, np.zeros(144, bool))  # counted even if nobody is ever at home and awake
    S, Wt = np.zeros((8, 144)), np.zeros(8)  # by diary weekday, 1 = Monday
    for h, a in awake.items():
        S[dow[h]] += hh[h] * a
        Wt[dow[h]] += hh[h]
    P = S / np.maximum(Wt[:, None], 1e-9)

    def clock(after6, before6):  # the small hours belong to the diary of the day before
        out = []
        for H in range(24):
            days, i = (after6, (H - 6) * 6) if H >= 6 else (before6, (H + 18) * 6)
            w = Wt[days]
            out.append(float((P[days][:, i:i + 6].mean(1) * w).sum() / w.sum()))
        return out
    return {"weekday": clock([1, 2, 3, 4, 5], [7, 1, 2, 3, 4]), "weekend": clock([6, 7], [5, 6])}, len(hh)


def hourly(bins_med):
    """Five bin medians to 24 hourly values: straight lines between the bins' middles, flat beyond the ends."""
    return [round(float(np.interp(h + 0.5 if h >= 12 else h + 24.5, CENTRES, bins_med)), 3) for h in range(24)]


def main():
    # not the facades flagged while counting: festivals and decorations, shop displays, empty buildings, a camera clock
    # the sky contradicts, or a place outside the centre
    rows = [r for r in json.loads(COUNTS.read_text())
            if (r["hour"] <= 6 or r["hour"] >= 15) and r["windows"] > 0 and not r.get("exclude")]
    rhythm, n_hh = home_rhythm()
    out = {"types": {}, "n": len(rows), "rhythm": {k: [round(v, 3) for v in r] for k, r in rhythm.items()},
           "rhythm_households": n_hh}
    for name, src in TYPES.items():
        rs = [r for r in rows if r["type"] in src]
        share = lambda r: r["lit"] / r["windows"]  # noqa: E731
        day_of = lambda r: "weekend" if r["weekend"] else "weekday"  # noqa: E731
        if name in HOMES:
            # one level for the whole day: the facades' shares over the rhythm at their hour (not where the survey
            # has nearly everyone asleep, which would divide by almost nothing)
            fit = [share(r) / rhythm[day_of(r)][r["hour"]] for r in rs if rhythm[day_of(r)][r["hour"]] >= 0.1]
            level = st.median(fit)
            med = {d: [round(level * v, 3) for v in rhythm[d]] for d in rhythm}
            ratios = [share(r) / max(med[day_of(r)][r["hour"]], 0.02) for r in rs]
            print(f"{name}: level {level:.3f} from {len(fit)} facades")
        else:
            overall = st.median(share(r) for r in rs)
            med, ratios = {}, []
            for day in ("weekday", "weekend"):
                bm = []
                for i in range(len(BINS)):
                    g = [share(r) for r in rs if bin_of(r["hour"]) == i and day_of(r) == day]
                    m = st.median(g) if g else overall
                    bm.append((len(g) * m + PRIOR * overall) / (len(g) + PRIOR))
                    ratios += [x / max(m, 0.02) for x in g]
                med[day] = hourly(bm)
        cols = [r["colour"] for r in rs if r.get("colour")]
        colour = [round(st.mean(c.get(k, 0) for c in cols), 2) for k in ("warm", "neutral", "cool")]
        s = sum(colour) or 1
        out["types"][name] = dict(n=len(rs), med=med, shape=quantiles(ratios),
                                  floors=round(sum(r["pattern"] == "whole_floors" for r in rs) / len(rs), 2),
                                  colour=[round(c / s, 2) for c in colour])
        print(name, len(rs), {d: v[18:24] + v[0:2] for d, v in med.items()}, out["types"][name]["floors"], out["types"][name]["colour"])
    OUT.write_text(json.dumps(out))


if __name__ == "__main__":
    main()
