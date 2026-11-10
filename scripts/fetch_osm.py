"""OpenStreetMap for the AOI (+150 m margin) from public Overpass servers, as one Overpass-style JSON.

Adapted from dtla-voxel scripts/fetch_osm.py (https://github.com/sigman78/dtla-voxel, commit 90bc1a6c, MIT, see
LICENSE-dtla-voxel). Writes {RAW}/osm.json, the file scripts/osm.py reads.

The box is split into SPLIT x SPLIT queries of at most ~1.5 km (one query over the full area is too heavy for the
public servers at busy times); elements are merged by (type, id). Geometry is clipped to the whole-AOI box (not the
query tile), so ways crossing tile edges stay whole. Each tile is cached; delete {RAW}/osm_parts to download again.
"""
import concurrent.futures as cf
import json
import math
import sys
import time
from pathlib import Path

import requests

from aoi import RAW, SIZE_X, SIZE_Y, bbox_lonlat

SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
UA = {"User-Agent": "madrid-voxel/0.1"}
MARGIN = 150  # metres around the AOI
OUT = Path(RAW) / "osm.json"
SPLIT = max(1, math.ceil(max(SIZE_X, SIZE_Y) / 1500))


def query(bb, full, rounds=6):
    """Elements in bb (S, W, N, E) with geometry clipped to full, plus the data timestamp."""
    f = ",".join(f"{x:.5f}" for x in full)
    q = f"[out:json][timeout:300][maxsize:536870912];nwr({bb[0]:.5f},{bb[1]:.5f},{bb[2]:.5f},{bb[3]:.5f});out body geom({f});"
    for rnd in range(rounds):
        for url in SERVERS:
            try:
                r = requests.post(url, data={"data": q}, timeout=400, headers=UA)
                if r.ok and r.text.lstrip().startswith("{"):
                    js = r.json()
                    return js["elements"], js.get("osm3s", {}).get("timestamp_osm_base")
                print(f"fail {url}: {r.status_code}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"fail {url}: {e}", file=sys.stderr)
        time.sleep(10 * (rnd + 1))
    raise SystemExit("all Overpass servers failed")


def main():
    if OUT.exists():
        print(f"OSM cached {OUT}")
        return
    s, w, n, e = bbox_lonlat(MARGIN)
    parts = Path(RAW) / "osm_parts"
    parts.mkdir(parents=True, exist_ok=True)

    def tile(ij):
        i, j = ij
        f = parts / f"{i}_{j}.json"
        if not f.exists():
            bb = (s + (n - s) * i / SPLIT, w + (e - w) * j / SPLIT, s + (n - s) * (i + 1) / SPLIT, w + (e - w) * (j + 1) / SPLIT)
            try:
                els, stamp = query(bb, (s, w, n, e), rounds=2)
            except SystemExit:  # a dense corner: four smaller queries
                els, stamp = [], None
                for a in range(2):
                    for b in range(2):
                        sub = (bb[0] + (bb[2] - bb[0]) * a / 2, bb[1] + (bb[3] - bb[1]) * b / 2,
                               bb[0] + (bb[2] - bb[0]) * (a + 1) / 2, bb[1] + (bb[3] - bb[1]) * (b + 1) / 2)
                        sub_els, stamp = query(sub, (s, w, n, e))
                        els += sub_els
            f.write_text(json.dumps({"timestamp": stamp, "elements": els}))
        print(f"tile {i},{j} done", flush=True)
        return json.loads(f.read_text())

    merged, stamps = {}, set()
    with cf.ThreadPoolExecutor(2) as ex:
        for part in ex.map(tile, [(i, j) for i in range(SPLIT) for j in range(SPLIT)]):
            stamps.add(part["timestamp"])
            for el in part["elements"]:
                merged[(el["type"], el["id"])] = el
    stamp = max((t for t in stamps if t), default=None)
    tmp = OUT.with_suffix(".json.part")
    tmp.write_text(json.dumps({"bbox": [s, w, n, e], "timestamp": stamp, "elements": list(merged.values())}))
    tmp.rename(OUT)
    print(f"OSM DONE {OUT} {OUT.stat().st_size / 1e6:.1f} MB, {len(merged)} elements, data as of {stamp}", flush=True)


if __name__ == "__main__":
    main()
