"""Wikidata facts for the OSM features in the AOI that carry a wikidata=Q... tag -> {AREA}/wikidata.json

Landmarks are linked to Wikidata only through the OSM tag, never by name. Every tagged node, way and relation in the
AOI's OSM extract is collected; their items are fetched in batches of 50 with wbgetentities, then the items their facts
point to (architects, styles, heritage designations) for their names. Entities are cached by id in
{RAW}/wikidata/entities.json, so a new AOI or a rebuild only asks for what is missing. Wikidata is CC0.

OVERRIDES maps a required landmark's id to the OSM element it should label when that element lacks the tag (see
DECISIONS.md); it is empty while every required landmark is tagged in OSM.

Output {AREA}/wikidata.json: {"items": {qid: facts}, "osm": [[qid, type, id, name], ...], "missing": [...]}; facts:
  en, es           labels (English, Spanish)
  en_desc, es_desc descriptions
  year             year built or opened (P571 inception, else P1619 opening, else P580 start)
  architects       names (P84)
  height           metres (P2048)
  styles           architectural styles (P149)
  heritage         heritage designations (P1435), e.g. "Bien de Interes Cultural"
  website          official website (P856)
  enwiki, eswiki   Wikipedia article titles
  wikis            number of Wikipedia language editions (sitelinks), a measure of how well known a place is
  types            instance of (P31)

usage: PYTHONPATH=scripts uv run python scripts/fetch_wikidata.py
"""
import json
import time
from pathlib import Path

import requests

from aoi import AREA, RAW

API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "madrid-voxel/0.1 (build-time fetch of landmark facts)"}
CACHE = Path(RAW) / "wikidata" / "entities.json"
OUT = AREA / "wikidata.json"
LANGS = ("en", "es")
OVERRIDES = {}  # qid -> [osm type, osm id] for a required landmark whose OSM element lacks the wikidata tag
# the required landmarks (PLAN.md Phase 4), by Wikidata id; checked against the AOI's tags in the report
REQUIRED = {}


def _get(params):
    for wait in (5, 20, 60, 120):
        r = requests.get(API, params={**params, "format": "json"}, headers=UA, timeout=120)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After") or wait))
            continue
        r.raise_for_status()
        return r.json()
    raise SystemExit("Wikidata keeps rate-limiting")


def entities(ids, cache):
    """Fetch the entities not yet cached (labels, descriptions, claims, sitelinks), 50 per request."""
    todo = sorted({i for i in ids if i.startswith("Q") and i not in cache})
    for k in range(0, len(todo), 50):
        got = _get(dict(action="wbgetentities", ids="|".join(todo[k:k + 50]),
                        props="labels|descriptions|claims|sitelinks", languages="|".join(LANGS)))
        for qid, e in got.get("entities", {}).items():
            cache[qid] = dict(labels={l: v["value"] for l, v in e.get("labels", {}).items()},
                              descriptions={l: v["value"] for l, v in e.get("descriptions", {}).items()},
                              claims={p: [c["mainsnak"].get("datavalue", {}).get("value") for c in cs
                                          if c.get("rank") != "deprecated"]
                                      for p, cs in e.get("claims", {}).items()
                                      if p in ("P31", "P84", "P149", "P571", "P1619", "P580", "P2048", "P1435", "P856")},
                              sitelinks={s: v["title"] for s, v in e.get("sitelinks", {}).items()})
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        time.sleep(1)
    return cache


def _ids(values):
    return [v["id"] for v in values if isinstance(v, dict) and "id" in v]


def _year(values):
    for v in values:
        if isinstance(v, dict) and "time" in v and v.get("precision", 0) >= 9:
            return int(v["time"][1:5]) * (-1 if v["time"][0] == "-" else 1)
    return None


def _height(values):
    for v in values:
        if isinstance(v, dict) and "amount" in v and v.get("unit", "").endswith("/Q11573"):  # metre
            return round(float(v["amount"]), 1)
    return None


def facts(qid, cache):
    e = cache[qid]
    c, lab, desc, sl = e["claims"], e["labels"], e["descriptions"], e["sitelinks"]
    name = lambda q: cache.get(q, {}).get("labels", {}).get("en") or cache.get(q, {}).get("labels", {}).get("es")  # noqa: E731
    out = dict(en=lab.get("en"), es=lab.get("es"), en_desc=desc.get("en"), es_desc=desc.get("es"),
               year=_year(c.get("P571", [])) or _year(c.get("P1619", [])) or _year(c.get("P580", [])),
               architects=[n for n in map(name, _ids(c.get("P84", []))) if n],
               height=_height(c.get("P2048", [])),
               styles=[n for n in map(name, _ids(c.get("P149", []))) if n],
               heritage=[n for n in map(name, _ids(c.get("P1435", []))) if n],
               website=next((v for v in c.get("P856", []) if isinstance(v, str)), None),
               enwiki=sl.get("enwiki"), eswiki=sl.get("eswiki"),
               wikis=sum(s.endswith("wiki") and s not in ("commonswiki", "specieswiki", "wikidatawiki") for s in sl),
               types=[n for n in map(name, _ids(c.get("P31", []))) if n])
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def main():
    osm = json.load(open(AREA / "osm.json"))
    tagged = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        for q in str(t.get("wikidata", "")).split(";"):
            q = q.strip()
            if q.startswith("Q"):
                tagged.append([q, e["type"], e["id"], t.get("name")])
    for q, (typ, oid) in OVERRIDES.items():
        tagged.append([q, typ, oid, None])
    qids = sorted({q for q, *_ in tagged})
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    entities(qids, cache)
    refs = {i for q in qids if q in cache for p in ("P31", "P84", "P149", "P1435") for i in _ids(cache[q]["claims"].get(p, []))}
    entities(refs, cache)
    items = {q: facts(q, cache) for q in qids if q in cache}
    missing = sorted(set(REQUIRED) - {q for q, *_ in tagged})
    OUT.write_text(json.dumps(dict(source="Wikidata (CC0) via OSM wikidata tags", items=items, osm=tagged,
                                   missing=missing), ensure_ascii=False))
    print(f"{len(tagged)} OSM elements with a wikidata tag, {len(qids)} items -> {OUT}")
    for q in missing:
        print("required landmark not tagged in the AOI's OSM:", q, REQUIRED[q])


if __name__ == "__main__":
    main()
