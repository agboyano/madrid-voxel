"""Madrid's municipal tree inventory over the AOI -> {RAW}/trees/trees.json

Source: "Arbolado en parques y zonas verdes de Madrid (detalle)", datos.madrid.es dataset 300761-0-arbolado-especies
(Ayuntamiento de Madrid, CC BY 4.0), updated twice a year (January and July). One point per municipally maintained
tree (street trees, district green areas, historic/singular/forest parks), in ETRS89 / UTM 30N. Palms, nurseries and
the forest masses (e.g. Casa de Campo) are not included. Column spec: estructura_datosarbolado.pdf (July 2025).

The dataset is only published as one file for the whole city, so the CSV (~75 MB) is downloaded once into the cache
and filtered locally to the AOI plus MARGIN. Spanish column names are mapped to English identifiers here, and only
here (COLUMNS); see NOTES.md.

usage: PYTHONPATH=scripts uv run python scripts/fetch_trees.py
"""
import csv
import io
import json
from pathlib import Path

import numpy as np
import requests

from aoi import CRS, D, RAW, VOXEL_SIZE, W, to_grid

DATASET = "300761-0-arbolado-especies"
EDITION = "2026-07"  # Arbolado 2026, published 2026-07-09
CSV_URL = (f"https://datos.madrid.es/dataset/{DATASET}/resource/300761-8-arbolado-especies/download/"
           "300761-6-arbolado-especies.csv")
UA = {"User-Agent": "madrid-voxel/0.1"}
MARGIN = 20  # metres around the AOI
DIR = Path(RAW) / "trees"
SRC = DIR / f"arbolado_{EDITION}.csv"
OUT = DIR / "trees.json"

# Spanish column -> (English key, parser). Columns of the spec missing from a given edition are left out.
_text = lambda v: v.strip() or None  # noqa: E731
_num = lambda v: float(v.replace(",", ".")) if v.strip() else None  # noqa: E731
COLUMNS = {
    "ASSETNUM": ("id", _text),
    "NUM_PARQUE": ("park_id", _text),
    "NUM_DISTRITO": ("district_id", _text),
    "NBRE_DISTRITO": ("district", _text),
    "NUM_BARRIO": ("neighbourhood_id", _text),
    "NBRE_BARRIO": ("neighbourhood", _text),
    "X": ("x", _num),
    "Y": ("y", _num),
    "CODIGO_ESPECIE": ("species_code", _text),
    "ESPECIE": ("species", _text),  # scientific name, upper case
    "PERIMETRO": ("trunk_cm", _num),  # trunk circumference at 1.3 m
    "ALTURA_TOTAL": ("height_m", _num),
    "EDAD_RELATIVA": ("age_class", _text),
    "SINGULARIDAD": ("singular", _text),  # CAT_CM / CAT_PGOUM
    "VITALIDAD": ("vitality", _text),  # Alta / Media / Baja
    "ESTADO_GENERAL": ("condition", _text),  # Sano ... Muerto
}


def download():
    if SRC.exists():
        return
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = SRC.with_suffix(".csv.part")
    with requests.get(CSV_URL, headers=UA, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(SRC)


def main():
    download()
    text = SRC.read_bytes().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    unknown = set(rows[0]) - set(COLUMNS)
    if unknown:
        raise SystemExit(f"fetch_trees: unmapped columns {sorted(unknown)}; add them to COLUMNS")
    trees = [{COLUMNS[k][0]: COLUMNS[k][1](v) for k, v in row.items()} for row in rows]
    trees = [t for t in trees if t["x"] is not None and t["y"] is not None]

    i, j = to_grid(np.array([t["x"] for t in trees]), np.array([t["y"] for t in trees]))
    pad = MARGIN / VOXEL_SIZE
    keep = (i >= -pad) & (i < W + pad) & (j >= -pad) & (j < D + pad)
    sel = [t for t, k in zip(trees, keep) if k]
    OUT.write_text(json.dumps({"source": f"datos.madrid.es {DATASET} ({EDITION}), CC BY 4.0", "crs": CRS,
                               "columns": sorted(set(COLUMNS[k][0] for k in rows[0])), "trees": sel},
                              ensure_ascii=False))
    print(f"{len(sel)} of {len(trees)} trees in the AOI (+{MARGIN} m) -> {OUT}")


if __name__ == "__main__":
    main()
