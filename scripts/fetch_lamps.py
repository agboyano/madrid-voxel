"""Madrid's municipal street-lighting inventory over the AOI -> {AREA}/lamps.json

Sources (Ayuntamiento de Madrid, CC BY 4.0), editions of 2022:
  - "Unidades luminosas (farolas)", datos.madrid.es dataset 300573: every lighting unit on the city's streets
    (233 309; parks, gardens and the M-30 left out), maintained by the Dirección General de Conservación de Vías
    Públicas. A unit is one support, whatever it carries: a column with a sodium lantern over the road and a LED globe
    for the pavement counts once.
  - "Unidades luminosas (farolas) en parques históricos y singulares", dataset 300582: the historic parks (the Retiro,
    the Jardines de Sabatini, 300582-2) and the forest parks and nurseries (the Vivero de Estufas del Retiro, 300582-0).
    Its third file, 300582-6, only counts the lamps of other parks, with no positions, and is not used.
Positions in ETRS89 / UTM 30N. Each unit has its luminaire model (`tipo_bloqu`, e.g. FVLED005) and type (LED, DESCARGA
-- sodium, metal halide and older -- or LED-DESCARGA for a support with both), and the street address it hangs on.
No height or support type: lamps.py infers the support from the model (NOTES.md "Street lamps from the inventory").

The files are only published for the whole city, so they are downloaded once into the cache and filtered locally to
the AOI plus MARGIN. Spanish column names are mapped to English identifiers here, and only here (COLUMNS); see NOTES.md.

usage: PYTHONPATH=scripts uv run python scripts/fetch_lamps.py
"""
import json
from pathlib import Path

import numpy as np
import requests

from aoi import AREA, CRS, D, RAW, VOXEL_SIZE, W, to_grid

EDITION = "2022"  # the files as served on 2026-02-16
BASE = "https://datos.madrid.es/dataset"
FILES = {  # dataset, resource -> where the unit stands
    "street": ("300573-0-unidades-luminosas-farolas", "300573-0-unidades-luminosas-farolas-csv"),
    "historic_park": ("300582-0-unidades-luminosas-farolas-", "300582-2-unidades-luminosas-farolas--csv"),
    "forest_park": ("300582-0-unidades-luminosas-farolas-", "300582-0-unidades-luminosas-farolas--csv"),
}
UA = {"User-Agent": "madrid-voxel/0.1"}
MARGIN = 20  # metres around the AOI
DIR = Path(RAW) / "lamps"
OUT = AREA / "lamps.json"

# Spanish column -> English key. The street file's header carries dBase field types ("X_UTM,N,19,11"), dropped on
# reading; the park files name the address class CLA_APP and add the park's name (one with an accent, one without).
_text = lambda v: v.strip() or None  # noqa: E731
_num = lambda v: float(v.replace(",", ".")) if v.strip() else None  # noqa: E731
COLUMNS = {
    "tipo_bloqu": ("model", _text),  # luminaire model code
    "TIPOL": ("light", _text),  # LED / DESCARGA / LED-DESCARGA
    "VIA_CLASE": ("street_class", _text),
    "VIA_PAR": ("street_particle", _text),
    "VIA_NOMBRE": ("street", _text),
    "CLASE_APP": ("address_class", _text),
    "CLA_APP": ("address_class", _text),
    "NUMERO": ("number", _text),
    "COD_NDP": ("address_id", _text),
    "DISTRITO": ("district_id", _text),
    "BARRIO": ("neighbourhood_id", _text),
    "X_UTM": ("x", _num),
    "Y_UTM": ("y", _num),
    "DENOMINACION": ("park", _text),
    "DENOMINACIÓN": ("park", _text),
    "": ("unit_id", _text),  # forest parks: LU_000001 ...
}
KEEP = ("model", "light", "street", "park", "x", "y")


def path(kind):
    return DIR / f"{FILES[kind][1]}_{EDITION}.csv"


def download(kind):
    out = path(kind)
    if out.exists():
        return out
    DIR.mkdir(parents=True, exist_ok=True)
    ds, res = FILES[kind]
    tmp = out.with_suffix(".csv.part")
    with requests.get(f"{BASE}/{ds}/resource/{res}/download/{res}.csv", headers=UA, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(out)
    return out


def read(kind):
    lines = download(kind).read_bytes().decode("utf-8-sig").splitlines()
    header = [h.split(",")[0].strip() for h in lines[0].split(";")]
    unknown = set(header) - set(COLUMNS)
    if unknown:
        raise SystemExit(f"fetch_lamps: unmapped columns {sorted(unknown)} in {kind}; add them to COLUMNS")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = {COLUMNS[h][0]: COLUMNS[h][1](v) for h, v in zip(header, line.split(";"))}
        if row.get("x") is not None and row.get("y") is not None:
            rows.append({k: row.get(k) for k in KEEP} | {"where": kind})
    return rows


def main():
    units = [u for kind in FILES for u in read(kind)]
    i, j = to_grid(np.array([u["x"] for u in units]), np.array([u["y"] for u in units]))
    pad = MARGIN / VOXEL_SIZE
    keep = (i >= -pad) & (i < W + pad) & (j >= -pad) & (j < D + pad)
    sel = [u for u, k in zip(units, keep) if k]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": f"datos.madrid.es 300573 and 300582 ({EDITION}), CC BY 4.0", "crs": CRS,
                               "lamps": sel}, ensure_ascii=False))
    by = {k: sum(u["where"] == k for u in sel) for k in FILES}
    print(f"{len(sel)} of {len(units)} lighting units in the AOI (+{MARGIN} m) {by} -> {OUT}")


if __name__ == "__main__":
    main()
