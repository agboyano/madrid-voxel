# Technical notes

Notes written while learning how the pipeline works. The Phase 0 analysis below is inferred from reading the code; the Warsaw data pipeline has not been run.

## Setup

### Reference projects

Cloned outside the repository as read-only references:

| Project | Path | Commit |
| --- | --- | --- |
| warsaw-vibe-voxel (base, imported as the first commit) | `../warsaw-vibe-voxel` | `9104d330fd6c8724eb89ccf6ee6d32fa127b7433` (2026-11-10) |
| dtla-voxel | `../dtla-voxel` | `90bc1a6ce6e87fa0eb93076557838ae1950bb778` (2026-11-06) |

The import copied the files tracked at that Warsaw commit (`git archive`), without its history. `LICENSE` became `LICENSE-warsaw-vibe-voxel`.

### Git identity

`user.name = Agboyano`, `user.email = agboyano@protonmail.com` (global config, set by the user). A local, unversioned `commit-msg` hook in `.git/hooks/` rejects AI attribution; it was tested with a real commit in both directions.

### Environment and installation

- Arch Linux, Python 3.14.8 (the project venv resolves to 3.13 through `uv`), uv 0.13.5, Node 26.12.0, npm 12.2.1.
- **Viewer:** `web/` pins `pnpm@12.11.2` with a `pnpm-lock.yaml`. Installed with `npx -y pnpm@12.11.2 install --frozen-lockfile` (no global pnpm needed). `npm install` would ignore the lockfile and create a `package-lock.json`.
- **Python:** `uv sync` installs the Warsaw dependencies without problems: numpy 2.5.4, scipy 1.18.1, rasterio 1.5.2 (bundled GDAL 3.12.2), pyproj 3.8.0 (PROJ 9.8.1), shapely 2.2.0 (GEOS 3.14.1), pillow, requests, webcolors. rasterio wheels ship their own GDAL, so no system GDAL is needed (`gdalinfo` is not installed).
- **Point cloud libraries** (probed in a throwaway venv, not added yet):
  - `laspy[lazrs]` 2.7.0 installs and detects the `LazrsParallel` backend. This is what dtla-voxel uses; it is enough to read PNOA LAZ 1.4.
  - `pdal` (Python bindings) fails to build: CMake cannot find a system PDAL. Not needed unless we choose PDAL; installing it would need `pacman -S pdal` first. `pdal info` for the Phase 1 source report can be replaced by laspy.
- **Playwright:** `playwright` 1.65.0 added as a dev dependency for `scripts/screenshot.py`. It drives the system Chromium (`/usr/bin/chromium`) instead of downloading Playwright's bundled build.

### Data size reference (Warsaw tiles)

`web/public/data`: 55 MB on disk (50 MB apparent), 2205 files.

| Part | Size |
| --- | --- |
| `tiles/1` (1 m, 1085 tiles) | 7.6 MB |
| `tiles/1f` (foliage) | 13 MB |
| `tiles/8` (8 m clay) | 0.56 MB |
| `trees.json` | 18 MB |
| `traffic.json` | 10 MB |
| other `.bin`/`.json` (foliage, meta, terrain, flood, zones, ...) | ~6 MB |

Grid: W 3950 × D 4430 cells, H 351 levels.

### Viewer and screenshots

- `npm run dev` equivalent: `npx -y pnpm@12.11.2 exec vite` serves the viewer at `http://localhost:5173/` with the Warsaw tiles, unchanged.
- Analytics (PostHog in `web/index.html` and `web/src/stats.ts`) stay off locally: they need a `phc_` key and the `p.migdal.pl` host.
- Headless Chromium falls back to SwiftShader (software WebGL), which is far too slow to stream the city. `--use-angle=gl --ignore-gpu-blocklist --enable-gpu` gets the real GPU (Intel UHD 620 through Mesa).
- The viewer adapts its "Render size" level to the frame rate and draws what the budget leaves out as grey 8 m clay. On this GPU (8-17 fps) that leaves most of the map grey, so `scripts/screenshot.py` sets the slider to 1 by default (`--level`).
- Reference screenshots in `docs/img/`: `warsaw-overview.png` (view `overview`, 15 Jun 17:00), `warsaw-street.png` (view `zlota`, 15 Jun 17:00), `warsaw-skyline.png` (view `skyline`, 10 Oct 09:00). Each takes 70-80 s at full render size.

### Corrections to `PLAN.md` assumptions

- The tiles have only two levels, 1 m and 8 m (plus the `1f` foliage set), not 1/2/4/8 m (`scripts/tiles.py:24`). dtla-voxel adds 2 and 4.
- `scripts/build_data.sh` is not the whole pipeline: nine scripts were run by hand and their outputs committed (see the pipeline map).
- `voxelize.py` does not use the LiDAR point cloud or classes: it takes a DSM at 0.5 m, a DTM at 1 m and an orthophoto at 0.2 m from `data/prep.npz`.

## Pipeline map

This section and the next come from reading the code, not from running it. Line references are `file:line` and point at the snapshot in this repository (`scripts/`, `web/src/`).

### Execution order

`scripts/build_data.sh` runs only six steps (`build_data.sh:5-10`):

```
fetch_osm.sh -> fetch_gugik.sh -> prep.py -> voxelize.py -> places.py -> flood.py
```

Several other scripts write files that the viewer loads, but `build_data.sh` never calls them. They were run by hand, and their outputs are committed. The full dependency order, worked out from the code:

```
                 (manual, cached in data/raw)
 fetch_trees.py ─────────────► data/raw/trees/bos_trees.json, bos_crowns.json  (+ um_drzewa.json: no script)
 wikidata.py ────────────────► data/raw/wikidata.json        (places.py, optional)
 notable.py ─────────────────► data/raw/notable.json         (labels.py, REQUIRED by voxelize)
 climate.py ─────────────────► web/public/data/climate.json  (independent)
 window_photos.py ───────────► scripts/window_photos.json + data/raw/window_photos/*.jpg
   (counted by eye) ─────────► scripts/window_counts.json ──► window_stats.py ──► windows.json

 fetch_osm.sh ──► data/raw/osm.json ─┬─────────────────────────────────────────────┐
 fetch_gugik.sh ─► data/raw/{dsm,dtm}_*.asc, orto_*.tif ──► prep.py ──► data/prep.npz
                                     │                                   │
                                     ▼                                   ▼
            (phenology.json must already exist: roofgardens.py:22)  voxelize.py
                                     │   imports landmarks, monuments, roofgardens, trees,
                                     │   underpass, labels, debris, tiles, traffic
                                     ▼
   web/public/data/{tiles/1,1f,8, meta.json, trees.json, traffic.json, qa_roadmask.bin.gz}
   data/ground.npz, data/debug/*, data/cache/* (LMCACHE=1 / FINALDUMP=1)
                                     │
   ┌──────────────┬──────────────┬───┴──────────┬───────────────┬──────────────┐
 terrain.py    zones.py       windows.py      places.py      flood.py      phenology.py
 terrain.bin   zones.bin/json windows.bin     places.json    flood.bin/json phenology.json, foliage.bin
 (ground.npz)  (osm.json)     (osm.json)      (osm, wikidata) (ground, prep,  (trees.json, DWD, iNat,
                                                              meta.json)     *_photos.json)
```

Gaps and traps in this order:

- `build_data.sh` leaves out `terrain.py`, `zones.py`, `windows.py`, `window_stats.py`, `phenology.py`, `climate.py`, `fetch_trees.py`, `wikidata.py` and `notable.py`.
- `phenology.json` and `voxelize.py` depend on each other. `roofgardens.py:22` reads `web/public/data/phenology.json` at import time, and `voxelize` imports it through `landmarks.py:11`. But `phenology.py:258` needs `trees.json`, which `voxelize` writes (`voxelize.py:1413`). This works today only because `phenology.json` is committed.
- `labels.py:640,759` reads `data/raw/notable.json` with no existence check, so `voxelize` fails at `voxelize.py:1959` if `notable.py` has not been run.
- `zones.py:103` optionally reads `data/cost1m.json`, written by `web/tools/cost1m.mjs`. That tool's default output path is a macOS temp path (`cost1m.mjs:5`).
- `voxelize.py` holds the whole volume in memory: `vol = np.zeros((H, D, W), uint16)` (`voxelize.py:1043`). For Warsaw that is 351 × 4430 × 3950 × 2 B ≈ 12 GB, and the starting H is larger than the final 351 (`voxelize.py:1041`). The dtla-voxel 128-row band approach avoids this.
- `fetch_gugik.sh:24` downloads `lod1_2024.zip`, but nothing reads it.

### Grid / AOI (`scripts/aoi.py`)

| Item | Value | Ref |
| --- | --- | --- |
| World CRS | EPSG:2180 (PL-1992), x easting, y northing | `aoi.py:7` |
| Anchor | PKiN spire at (636965.62, 486975.12), sitting at grid (I0, J0) = (750, 2510) | `aoi.py:15,22` |
| Rotation | THETA = 21.5°, measured from 443 PKiN wall edges | `aoi.py:16`, doc `:3-5` |
| Size | W = 3950 columns (i), D = 4430 rows (j), 1 m cells | `aoi.py:21` |
| Axes | +i = (cos θ, sin θ), roughly ENE; +j = (sin θ, −cos θ), roughly SSE. Seen as an image (column right, row down), this is a north-up raster turned counter-clockwise by θ. Cell (c, r) covers [c, c+1) × [r, r+1). | `aoi.py:25-26,8-9` |
| Transforms | `to_grid(x, y)`, `to_world(i, j)` (continuous); `world_bounds(margin)` is the axis-aligned bbox of the rotated frame | `aoi.py:29-41` |
| Grid origin | `to_world(0, 0)` ≈ (635348, 489036), the NW corner | computed from `aoi.py:34-36` |
| Raw data dir | `RAW = "data/raw"` (relative to the repo root; there is no `$MADRID_CACHE` yet) | `aoi.py:23` |

Grid coordinates are used everywhere downstream: OSM geometries (`osm.py:16-19`), tiles, `meta.json`, `traffic.json`, labels and the viewer. The viewer maps data (x = column, y = row, z = up) onto three.js (x, z, y) (`world.ts:14-15`, `mesher.worker.ts:2`). `meta.theta_deg` is used only to turn the sun's azimuth (`daylight.ts:93-97`).

### Raster contract: what `voxelize.py` expects in `data/prep.npz`

`voxelize.py:138-139` loads `dsm`, `dtm` and `orto` from `data/prep.npz`, as written by `prep.py:80`. `landmarks.py:2173,2586,2884`, `flood.py:32` and `web/tools/audit.py:34` read the same file. The Madrid LiDAR rasters have to match this contract exactly, or the code that hard-codes the ratios has to change.

| Array | dtype | Shape | Cell | Resampling in prep | Values | Hard-coded ratio |
| --- | --- | --- | --- | --- | --- | --- |
| `dsm` | float32 | (2·D, 2·W) = (8860, 7900) | 0.5 m | nearest (`prep.py:72`, "keeps spires") | absolute surface height, m a.s.l. (GUGiK: PL-KRON86-NH) | `reshape(D,2,W,2)` at `voxelize.py:140,197,204,726`; `dsm[Y*2, X*2]` at `voxelize.py:1609` |
| `dtm` | float32 | (D, W) = (4430, 3950) | 1 m | bilinear (`prep.py:74`) | absolute ground height, m a.s.l. | used 1:1 with the grid (`voxelize.py:143-163`, `1611`, `1654`; `flood.py:32-36`) |
| `orto` | uint8 | (5·D, 5·W, 3) | 0.2 m | bilinear, after a per-sheet area average (`prep.py:45,78`) | sRGB; 0,0,0 = no data | `reshape(D,5,W,5,3)` median at `voxelize.py:205`; "5 px per grid metre" at `landmarks.py:2173` |

- **Orientation.** Array row k / column l is grid row j / column i, sampled at the cell centre `to_world((i+0.5)·res, (j+0.5)·res)` (`prep.py:52-68`). Row 0 is the grid's north-west edge (j = 0), not north-up. Sources are assumed axis-aligned and north-up, with origin at the top-left corner and pixel-centre convention (`prep.py:61-62`). `prep.resample()` does not depend on GUGiK and can be reused as-is for any north-up raster in the AOI CRS.
- **Nodata.** `prep.mosaic` fills with −9999 (`prep.py:21`), but `voxelize` never masks it. `BASE = floor(dtm.min()) − 3` (`voxelize.py:145`), so a single nodata cell in `dtm` makes BASE −10002 and wrecks the volume height. **The DTM must have no gaps.** Holes in the DSM come out as negative nDSM, which silently means "no building or tree". `flood.py:35` and `voxelize.py:1612` use `np.isfinite`, so NaN is the safer nodata value for `dsm`.
- **Derived quantities.** `dsm_max` and `dsm_mean` are taken per 1 m cell from 2×2 DSM samples (`:140-142`). `nd_max` and `nd_mean` are those minus `dtm` (`:169-170`). `nd_max_b` is `wall_clean(dsm)` minus `dtm`, used for building tops (`:173-204`). `cellcol` is the per-cell ortho median (`:205`), from which `exg` (excess green), `lum` and `rgbsum` follow (`:206-208`). `rough` is the DSM standard deviation over 3 m (`:725-726`). Ground voxels: `g = round(ground_walls(dtm) − BASE)` (`:163`), and the ground fills z ∈ [0, g).
- **No classification used.** Vegetation comes from ExG plus nDSM plus the tree databases (`:1229-1254`). Buildings come from OSM footprints, with heights from the DSM (`:612-743`). PNOA class 2/6/5/17 masks could replace the ExG heuristics, but nothing consumes them yet.
- **For Madrid.** NPC02 at about 5 pts/m² gives about 1.25 returns per 0.5 m cell. Either grid the DSM at 1 m and up-sample it ×2 by nearest neighbour (keeping the contract), or change the six places that hard-code the ×2. The 0.2 m ortho (×5) has the same problem if the PNOA ortho comes at 0.25 m. Heights must be orthometric and consistent between DSM and DTM; PNOA is ETRS89/UTM30N with REDNAP orthometric heights, but check per tile. `flood.py:87` and `meta.base` assume absolute metres.

### Scripts

| Script | Purpose | Inputs | Outputs (format) | Consumed by |
| --- | --- | --- | --- | --- |
| `build_data.sh` | Driver (partial, see above) | — | — | — |
| `aoi.py` | Grid definition (library) | — | — | every script |
| `fetch_osm.sh` | OSM for the AOI bbox + 100 m. By default it cuts the daily Geofabrik `mazowieckie-latest.osm.pbf` (re-downloaded if older than 1 day); `OVERPASS=1` uses 3 Overpass mirrors | `aoi.world_bounds`, EPSG:2180→4326 (`:8-14`); `download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf` (`:20`) | `data/raw/osm.json`: Overpass JSON `{version, osm3s.timestamp_osm_base, elements[]}` with `out body geom(bbox)` geometry | `osm.py`, `traffic.py:251`, `underpass.py:38` |
| `osm_pbf.py` | PBF → Overpass-style JSON (osmium), tagged nodes, ways with clipped `geometry`, relations | pbf, bbox S,W,N,E | `osm.json` (as above) | — |
| `osm.py` | Parses `osm.json` into shapely objects in grid coords: `nodes` (id, tags, Point), `lines` (id, tags, LineString), `areas` (id, type, tags, Polygon or MultiPolygon). Ways count as areas through `AREA_KEYS` (`:26-27`); multipolygon and building relations are assembled (`:60-79`) | `data/raw/osm.json` | in-memory `OSM` | voxelize, places, zones, windows, labels, wikidata, roofgardens |
| `fetch_gugik.sh` | 9 GUGiK sheets: 2025 DSM (0.5 m, `.asc`), DTM (1 m, `.asc`), ortho (5 cm `.tif`), plus LOD1 zip; cached (`-s` test), resumable | `opendata.geoportal.gov.pl/NumDaneWys/NMPT/83232`, `/NMT/83233`, `/ortofotomapa/83235` (`:7,20-24`) | `data/raw/dsm_<sheet>.asc`, `dtm_*.asc`, `orto_*.tif`, `lod1_2024.zip` | `prep.py` |
| `prep.py` | Mosaic on the sheets' own pixel grid (`:21-30`), paste the RGB windows (`:33-49`), resample onto the rotated grid in 1024-row bands (`:52-68`) | `data/raw/{dsm,dtm,orto}_*` (EPSG:2180) | `data/prep.npz` (`savez_compressed`: dsm, dtm, orto, see the contract above); `data/orto_preview.jpg` (ortho at 0.8 m) | voxelize, flood, landmarks, tools/audit |
| `voxelize.py` | Fuses the rasters with OSM into `vol[z,row,col]` uint16 palette ids. In order: ground and terrain fixes (`:148-286`); ground classes from OSM and ortho (`:288-486`); rails and water (`:488-541`); markings (`:543-610`); buildings (`:612-1216`); vegetation and trunks (`:1218-1420`); fountains and beds (`:1422-1510`); lamps and furniture (`:1512-1575`); bridge decks (`:1577-1873`); parked vehicles (`:1875-1909`); church windows (`:1911-1926`); curated landmarks (`:1928-1956`); labels (`:1958-1961`); debris and floating checks (`:1964-1982`); export (`:1967-2040`) | `prep.npz`, `osm.json`, `part_parents.json`, `overrides.json` (via landmarks), `phenology.json` (via roofgardens), tree DBs (via trees.py), `notable.json` (via labels) | see the files table below | viewer, terrain, flood, phenology, patch, surface_check, floating |
| `tiles.py` | Tile writer: `export` (`:82-128`), `export_region` (`:131-168`), `downsample` (`:27-59`), `column_runs` (`:62-79`) | `vol`, `g`, ids | `tiles/{s}/{tx}_{ty}.bin` and `tiles/1f/…` (format below) | `stream.ts`, `mesher.worker.ts` |
| `landmarks.py` | Curated Warsaw details: labels, views, height fixes, PKiN, churches, bridges (see part 2) | `overrides.json`, `prep.npz` ortho, the volume | mutates `vol`; returns `labels` and `views` for `meta.json` | voxelize, patch, labels |
| `monuments.py` | Monuments as boxes at lon/lat, facing and heights (`:191-420`); `build` (`:451`) | the volume | mutates `vol`; `MON_TOP` (label heights) | landmarks.details |
| `roofgardens.py` | Gardens on roofs, read from the ortho; `WHOLE` = Kopernik's roof paths | osm, ortho, `phenology.json["leaf"]` | mutates `vol`; `PATHS` for traffic | voxelize, landmarks |
| `underpass.py` | Carves level −1 pedestrian passages and stairwells; `WALK` and `IDS` for traffic | `osm.json` (raw, again) | mutates `vol` | voxelize, traffic |
| `debris.py` | `drop_debris` (small floating clumps, `:9`) and `support_floating` (trunks and posts under hanging pieces) | `vol`, `g` | mutates `vol`; `data/debug/floating*.json`, `supports.json` | voxelize, patch |
| `labels.py` | All map labels: curated + Wikidata-notable (ranked by pl+en pageviews) + parks over 2.5 ha; `far` tiers, radii (`:754-784`). Run standalone, it rewrites `meta.labels` from `data/cache/final_top.npy` and `final_g.npy` (`:785-801`) | landmarks, `notable.json`, osm | `labels` list in `meta.json` | voxelize |
| `trees.py` | Merges the city DB, OSM `natural=tree` and the 2010-13 API inventory; `is_conifer`; `attach_crowns` | `data/raw/trees/{bos_trees,bos_crowns,um_drzewa}.json`, osm nodes | list of dicts (grid x, y, species…) | voxelize |
| `fetch_trees.py` | Warsaw MapViewer GeoJSON per theme, in 1 km tiles of the AOI bbox | `mapa.um.warszawa.pl/mapviewer/dataserver/DANE_WAWA` (`:26`) | `data/raw/trees/bos/*.json`, `bos_trees.json`, `bos_crowns.json` | trees.py |
| `traffic.py` | Road graph (lanes, speeds, signals, restrictions), pedestrian graph, bike weights, tram routes (PTv2 relations), train routes, all fitted onto the voxels (`fit`, `:46`) | `osm.json` (raw), `g`, deck heights, `vol`, `solid`, roof gardens | `traffic.json` (schema below); standalone from `data/cache/traffic_in.pkl` (`:822-828`) | `sim/life.ts`, `sim/trains.ts`, `nav/*`, surface_check |
| `terrain.py` | First-moment terrain: heights every 4 m, colours every 2 m | `data/ground.npz` | `terrain.bin` (format below) | `city.ts:239` |
| `zones.py` | Per-column block and building ids (streets, rails and water separate the blocks; blocks over 120 000 m² are split on a 256 m grid) | `osm.json`, optional `data/cost1m.json` | `zones.bin`, `zones.json`, `data/debug/zones.png` | `city.ts:29`, `stream.ts` (building ids) |
| `windows.py` | Building kind per column, for night windows | `osm.json` | `windows.bin` | `windows.ts:14` |
| `window_photos.py` | Night photos of Warsaw from Commons, kept when the sun is below −4° | Commons API `Category:Night in Warsaw` (`:18`) | `data/raw/window_photos/*.jpg`, `scripts/window_photos.json` | (manual counting) |
| `window_stats.py` | Lit-window statistics per building type, hour and weekday | `scripts/window_counts.json` (hand counts) | `windows.json` | `windows.ts` |
| `phenology.py` | Leaf-out, colour and fall days per tree class (DWD + iNaturalist), autumn and lawn tints from Commons photos, and the per-2 m tree-class map | DWD CDC (`:42-43`), iNat (`:44-45`), `foliage_photos.json`, `grass_photos.json`, `trees.json` | `phenology.json`, `foliage.bin` | `foliage.ts`, roofgardens |
| `climate.py` | Typical weather per day of year (ERA5 1995-2024) | Open-Meteo archive at 52.23, 21.01 (`:24`) → `data/raw/climate/warsaw_daily2.json` | `climate.json` | `main.ts:263`, `weather.ts` |
| `wikidata.py` | pl/en labels, sitelinks, P31, P625, P856 for OSM `wikidata=` tags | Wikidata `wbgetentities` (`:16,41-43`) | `data/raw/wikidata.json` | places.py |
| `notable.py` | Every Wikidata item in the bbox (SPARQL `wikibase:box`) with pl+en pageviews, Oct 2025 to Sep 2026 | query.wikidata.org, wikimedia pageviews (`:59,75`) | `data/raw/notable.json` `{qid:{pl,en,desc,types,at,plwiki,enwiki,wikis,views,site,facebook}}` | labels.py |
| `places.py` | Search index: streets merged by name, named areas and nodes, Jazdów houses | osm, `wikidata.json` | `places.json` | `main.ts:291` |
| `flood.py` | River flood slider: spill level per cell, estimated bed depth, gauge calibration | `ground.npz`, `prep.npz[dtm]`, `meta.json[base]` | `flood.bin`, `flood.json` | `flood.ts:19` |
| `patch.py` | Fast landmark loop: re-runs `landmarks.details_geometry` on the cached pre-landmark volume and rewrites the tiles in `BOXES` | `data/cache/{pre_vol.npy,pre_state.pkl,export_ids.pkl}`, `meta.json` | tiles in the box, `meta.json` (palette appended) | dev only |
| `surface_check.py`, `floating.py` | QA: vehicles sinking or hovering against the volume; unsupported components | `data/cache/final_vol.npy`, `meta.json`, `traffic.json` | `data/debug/surface_check.json`, `floating_all_*.json` | dev only |
| `perf_stats.py` | PostHog HogQL usage report | `data/.env` keys, `eu.posthog.com` | stdout, `data/perf_pages.csv` | dev only |
| Data JSON in `scripts/` | `overrides.json` (64 per-building curations; schema in `_doc`), `part_parents.json` (680 part → outline OSM ids), `window_counts.json` (5093 lines of hand counts), `window_photos.json`, `foliage_photos.json` (autumn and summer canopy colours per class), `grass_photos.json` (lawn Lab colour per month) | — | — | landmarks; voxelize `:640`; window_stats; phenology |

### Files: who writes, who reads

| File | Writer | Format | Reader |
| --- | --- | --- | --- |
| `data/raw/osm.json` | fetch_osm.sh / osm_pbf.py | Overpass JSON | osm.py, traffic.py, underpass.py |
| `data/prep.npz` | prep.py:80 | npz; see the raster contract | voxelize, flood, landmarks |
| `data/ground.npz` | voxelize.py:1975 | `g` int16 (D, W) ground level (first free z, metres above BASE); `rgb` uint8 (D, W, 3) colour of the top ground voxel, grass shown as bare; `b` int16 building height above ground | terrain.py, flood.py, tools/poses.py |
| `data/cache/*` | voxelize (env `LMCACHE`, `FINALDUMP`) | `pre_vol.npy`, `pre_state.pkl`, `export_ids.pkl`, `final_vol.npy`, `final_g.npy`, `traffic_in.pkl` (`final_top.npy` is read by labels.py:786 but never written) | patch, traffic, labels, floating, surface_check |
| `data/debug/*` | voxelize, debris, zones | `report.json`, `topdown.png`, `ground.png`, `thin_parts.json`, `pkin_box.npz`, … | humans |
| `tiles/{1,8}/{tx}_{ty}.bin` | tiles.py | gzip (mtime 0) of `counts` uint16[(N+2)²] (runs per column, row-major with a 1-cell apron) + `ground` uint8[(N+2)²] (ground metres, clipped to 0..255) + `runs` uint16[3·Σ] (z0, len, palette id), bottom to top. N = 128. **Levels are 1 and 8 only** (`tiles.py:24`), not 1/2/4/8. Level 8: a cell is solid when ≥ ¼ of its 8×8×8 block is full; colour = the topmost voxel. Warsaw: 31×35 nodes at s = 1, 4×5 at s = 8 | stream.ts:158, mesher.worker.ts:49 |
| `tiles/1f/{tx}_{ty}.bin` | tiles.py:114 | same format; leaves, trunk and grass only. In `tiles/1` grass becomes `bare` and leaves and trunks are removed | stream.ts:164 |
| `meta.json` (1.1 MB) | voxelize.py:2005-2009 (labels rewritten by labels.py; palette appended by patch.py) | `{W, D, H, base, tiles{N, levels[{s,nx,ny}], bytes}, center[CX,CY], theta_deg, crs, trams[[x,y,z]…] (unused by the viewer), jets[[x,z,y]], palette[[r,g,b,mat]] (3402 entries; viewer limit 4096 = 64×64 texture, voxelMaterial.ts:81, world.ts:22), lamps[[c,r,z]], floods[[x,y,r]], labels[{name,en,kind,height,year,rebuilt,by,building,site,alt,far,x,y,z,g,R}], views{key:{label,pos,target}}, sources{osm,lidar,ortho}}` | main.ts, voxelMaterial (palette, lamps, floods), labels.ts, flood.py, surface_check, floating, tools |
| `terrain.bin` | terrain.py | gzip of uint16[ceil(D/4), ceil(W/4)] dm above base (4 m mean), then uint8[D//2, W//2, 3] sRGB | city.ts:239 |
| `zones.bin` / `zones.json` | zones.py:112-114 | gzip of uint16 block[D, W] + uint16 building[D, W]; JSON `{blocks:[[cx,cy,n,x0,y0,x1,y1,(tris)]], buildings:[…]}` (Warsaw: 869 blocks, 13 135 buildings; uint16 caps both at 65 535) | city.ts:29, stream.ts (building ids per tile) |
| `windows.bin` / `windows.json` | windows.py / window_stats.py | gzip uint8[D, W]: kind in the low 3 bits, per-building habit in the high 5; JSON `{bins, types{residential,office,hotel,public,religious:{n,med{weekday,weekend},shape,floors,colour}}, n}` | windows.ts |
| `foliage.bin` / `phenology.json` | phenology.py:266-276 | gzip of uint8 class[D/2, W/2] + uint8 tree hash[D/2, W/2]; JSON `{city{leaf,colour,fall}, sources, classes{k:{species,genera,leaf,colour,fall:{day,sd,n,source},autumn}}, grass[12][3], leaf[3]}` | foliage.ts, roofgardens.py:22 |
| `flood.bin` / `flood.json` | flood.py:83-95 | gzip of uint8 spill[D, W] (m above base, 255 = never) + uint8 depth[D, W] (dm); JSON `{gauge_row, gauge_zero, lidar_cm, base, surface0, fall, voxel_top}` | flood.ts |
| `places.json` | places.py:113 | `{places:[[name, kind, x, y, size, alt]]}`, grid metres, sorted by rank | main.ts:291 |
| `climate.json` | climate.py:56 | `{source, clear[365], cloudy, rain, snow, cover, snowy[bool]}` | main.ts:263, weather.ts:21 |
| `traffic.json` (10.6 MB) | voxelize.py:2040 → traffic.build | `{roads[{a,b,w,p[[x,y,z]],L,lanes,v,c,two,o0,stop?}], rnodes, ctrls, heads, peds, pnodes, trams[{ref,p,L}], trains[{p,L,svc[{ref,op,stops}]}], restr}` (Warsaw: 3591 roads, 34 084 ped edges, 67 tram pieces, 6 train tracks) | main.ts:296 → sim/life.ts, sim/trains.ts, nav/spots.ts |
| `trees.json` (18 MB) | voxelize.py:1413-1420 | `{sources, fields, trees[{id,x,y,src,drawn,z,h,sp,pl,cm,osm,um,h_inv,crown_d,cond,mgr,date,crown,crown_m2,crown_sp}]}` (81 633 trees) | phenology.py only (the viewer does not fetch it) |
| `qa_roadmask.bin.gz` | voxelize.py:2015 | gzip uint8[D, W] (1 = road, 2 = tram bed) | web/tools/qa.mjs |
| `web/public/preview.jpg` | manual | og:image | index.html:12 |

Total size of `web/public/data`: 55 MB.

### Viewer modules (`web/src/`)

| Module | Role | Data read |
| --- | --- | --- |
| `main.ts` | Boot, render loop, adaptive render level, sliders, search items, camera flights, credits, URL state (`date`, `hour`, `weather`, `view`, `cam`, `tilt`, `ui`) | `meta.json`, `climate.json`, `places.json`, `traffic.json` |
| `city.ts` | Staged loading: terrain, then 8 m clay, landmarks, blocks nearest the focus within a triangle budget, then foliage. Builds the terrain mesh | `zones.bin/json`, `terrain.bin` |
| `stream.ts` | `TileStreamer`: worker pool, LOD selection, building-id masks per tile | `tiles/{1,8,1f}/*.bin` |
| `mesher.worker.ts` | Fetches, gunzips and decodes a tile; greedy meshing with baked AO | tile files |
| `world.ts` | Voxel queries and raycasts over the loaded columns (walking, labels, camera) | (from stream) |
| `voxelMaterial.ts` | Voxel shader: palette texture, `MAT` ids (`:7-8`, must match `voxelize.py:44`, `landmarks.py:13,148`), facade windows, PKiN floodlight, foliage, grass, snow, wet, flood, lamp-pool texture | `meta.palette`, `lamps`, `floods` |
| `daylight.ts`, `sky.ts`, `sun.ts` | Sun position (fixed lat/lon, EU DST), sky colours, shadows, fog; PKiN light colours (`sky.ts:119-127`) | `meta.theta_deg` |
| `weather.ts` | Weather presets, the "typical" day from climate, rain and snow particles | `climate.json` |
| `foliage.ts` | Phenology uniforms and the class map | `phenology.json`, `foliage.bin` |
| `windows.ts` | Lit-window uniforms by hour and weekday | `windows.json`, `windows.bin` |
| `flood.ts` | River sheet and drop (sandbanks) | `flood.json`, `flood.bin` |
| `fountains.ts` | Animated jets | `meta.jets` |
| `labels.ts`, `search.ts`, `bar.ts`, `hud.ts`, `caption.ts`, `perf.ts` | Map pins, type-ahead, bottom bar, mouse HUD, loading caption, FPS and level knob | `meta.labels`, `places.json` |
| `post.ts` | Tilt-shift depth of field, N8AO, bloom | — |
| `stats.ts` | PostHog (cookieless) events | — |
| `util.ts`, `types.ts` | `fetchJson`, `fetchGzip`, `dataTexture`; Meta / Label / FloodInfo / Zones types | — |
| `nav/nav.ts`, `nav/ride.ts`, `nav/spots.ts` | Orbit, walk and ride modes; camera rigs per vehicle; walk spots along footpaths | `traffic.json` (through life) |
| `sim/life.ts`, `sim/trains.ts`, `sim/meshes.ts`, `sim/path.ts`, `sim/crossings.ts`, `sim/dance.ts`, `sim/types.ts` | Cars (IDM), signals, trams, pedestrians, bikes, trains; instanced meshes; zouk dancers | `traffic.json` |

## Warsaw-specific code

Actions: **remove** (delete or stub), **replace** (Madrid equivalent), **parametrise** (move to a config or `city` module), **keep** (generic, works as is).

### 1. AOI, CRS and hard-coded coordinates

| Ref | What | Action |
| --- | --- | --- |
| `aoi.py:1-23` | PKiN anchor in EPSG:2180, θ = 21.5°, 3950 × 4430, I0/J0 | replace (Madrid anchor and θ for its street grid, EPSG:25830); read `RAW` from `$MADRID_CACHE` |
| `osm.py:13`, `traffic.py:28`, `underpass.py:21`, `trees.py:22`, `notable.py:53`, `fetch_osm.sh:11`, `flood.py:90`, `web/tools/poses.py:11` | `Transformer(4326↔2180)` hard-coded | parametrise (one `aoi.CRS = 25830`) |
| `voxelize.py:2005` | `crs="EPSG:2180"` in meta | parametrise |
| `prep.py:34` | comment and workaround for GUGiK WKT variants | replace with prep_lidar |
| `voxelize.py:938` | MDM area as a grid LineString `(1036, 3700)-(1036, 4020)` | remove |
| `voxelize.py:1955-1956`, `patch.py:20-54,122` | PKiN box and per-landmark grid boxes | remove / replace |
| `landmarks.py:150,154-157,1449-1451,1677,1952,2034,2266-2267,2353,2542,2579-2580,2783,2876,2971,3042,3101-3102,3164,3192` | grid or EPSG:2180 constants for Varso, the historic core, PKiN shaft and towers, St Alexander, Staszic, Poniatowski, Teatr Wielki, MSN, Saski, the bridges, aviation masts, PGE spire. Applied blindly to whatever is at those cells | remove (stub `details_geometry`) |
| `landmarks.py:81-88` | `EXTRA_LABELS` at EPSG:2180 x, y | replace |
| `roofgardens.py:28-35` | Kopernik roof junctions (grid x, y) and OSM node ids | remove |
| `monuments.py:191-420` | every monument at Warsaw lon/lat | remove / replace |
| `sim/dance.ts:5-7`, `sim/life.ts:646`, `main.ts:245-246` | zouk floor at grid (2626.2, 741), search action `goPlace(2626, 2021)` | remove |
| `web/tools/*` (audit, bench, cmpshots, gpu1m, lodfade, lodflip, mem, navtest, poses, abdiff, film.json, commons.py) | camera poses and landmark names in Warsaw grid coords | replace later (keep the harnesses) |

### 2. Data sources and downloads

| Ref | What | Action |
| --- | --- | --- |
| `fetch_gugik.sh:1-24` | GUGiK DSM, DTM, ortho, LOD1 sheet ids | replace (PNOA-LiDAR NPC02 LAZ via CNIG, probably manual per CLAUDE.md rule 5; PNOA ortho) |
| `prep.py:1-82` | GUGiK `.asc` mosaics → `prep.npz` | replace (LAZ → DSM/DTM rasters, dtla `prep_lidar.py`); keep `resample()` (`:52-68`) |
| `fetch_osm.sh:17-20` | Geofabrik `poland/mazowieckie-latest.osm.pbf` | replace: `europe/spain/madrid-latest.osm.pbf` |
| `fetch_osm.sh:27` | UA `warsaw-voxel/0.1` | replace |
| `fetch_trees.py:1-108` | Warsaw MapViewer (`BOS_ZIELEN_DRZEWA_*`, `BOS_KORONY_<district>`), UA with `piotr.migdal@quesma.com` (`:33`) | replace (datos.madrid.es tree inventory) |
| `trees.py:62-85` | `um_drzewa.json` (api.um.warszawa.pl; no fetch script) | remove |
| `wikidata.py:43`, `notable.py:20`, `web/tools/commons.py:3`, `phenology.py:134` | user agents naming warsaw-vibe-voxel or Piotr Migdał | replace |
| `climate.py:24-25` | Open-Meteo at 52.23, 21.01, `timezone=Europe/Warsaw`, `warsaw_daily2.json` | parametrise (40.42, −3.70, Europe/Madrid) |
| `phenology.py:3-12,42-48,97-104` | DWD stations east of 12.5° E (closest to Warsaw's climate) | replace (Mediterranean or continental phenology source; DWD is a poor fit for Madrid) |
| `phenology.py:44-45` | iNaturalist place_ids 7800, 7207, 8264, 8267, 8266 (PL, DE, CZ, SK, LT) | replace (Spain, Portugal) |
| `window_photos.py:18` | `Category:Night in Warsaw` | replace |
| `voxelize.py:2007-2008` | `sources.lidar/ortho` = GUGiK strings | replace |

### 3. Palace of Culture (PKiN)

| Ref | What | Action |
| --- | --- | --- |
| `voxelize.py:44`, `voxelMaterial.ts:7`, `landmarks.py:13,148`, `debris.py:119` | material `M_PKIN` = 7 | keep the id (format), stop emitting it, or repurpose as "floodlit stone" |
| `voxelize.py:667` | `pkin = next(...)`: **raises StopIteration if absent**, so this is the first crash in Madrid | remove |
| `voxelize.py:902-907,949-951` | PKiN stone and roof colours | remove |
| `landmarks.py:837-1730,2671-2716` | PKiN porticos, clock, crown, windows, pinnacles, tower, fronts, balustrades, east wing | remove |
| `tiles.py:55-57` | `face_ids` (M_CLOCK) colour whole 8 m blocks (generic mechanism, used for the PKiN clock) | keep |
| `sky.ts:119-127`, `main.ts:24,322`, `voxelMaterial.ts:36,71,177,276-279` | `pkinLight`: nightly floodlight colours, `uPkinLight` | remove, or generalise to "floodlit landmark" |
| `landmarks.py:745-770,818-834` (`make_views`) | presets relative to PKiN, Złota 44, Centralna, Kopernik, PGE: **KeyError if missing** | replace (Madrid views) |
| `index.html:15,17` | og:image alt and favicon (PKiN in SVG) | replace |

### 4. Landmarks and curated buildings

| Ref | What | Action |
| --- | --- | --- |
| `landmarks.py:19-79` | `LABELS` dict (Polish OSM names → facts) | replace |
| `landmarks.py:91-118`, `labels.py:754-757`, `places.py:90-110,49` | Jazdów Finnish houses and their groups | remove |
| `landmarks.py:126-145` | `SMOOTH_ROOFS` (PGE Narodowy OSM ids) | remove (keep the mechanism) |
| `landmarks.py:150,190-199,496-501` | Varso and Złote Tarasy colour overrides | remove |
| `landmarks.py:152-162`, `voxelize.py:833-869,875,888-893,916-925,1165-1183` | `HISTORIC_CORE` (Old Town polygon), pitched-roof fit, tenement plaster palette, tiled step sides | parametrise (a Madrid "historic core" polygon, e.g. Madrid de los Austrias, with its own palette) |
| `landmarks.py:529-546,549-667,860-1040,1802-2716,2719-3216` | `details_geometry`, `classic_buildings` and all per-landmark rebuilds (Zachęta, PW, Teatr Wielki, Bristol, Holy Cross, churches, POLIN, Sigismund's Column, Castle tower, Złota 44, MSN, Saski, Sejm, bridges, masts, PGE spire) | remove; keep the helpers `classic_rebuild`, `edge_windows`, `ortho_roof`, `_pier`, `_onion` (generic) |
| `landmarks.py:504-527` | `small_tree` (young street tree, tuned on Złota) | keep |
| `landmarks.py:425-478,201-326` | `apply_zones`, `apply_stripes` (driven by overrides.json) | keep the engine; replace the data |
| `overrides.json` (64 entries) | per-building colours, zones, crowns, labels (OSM ids and Polish names) | replace (start empty) |
| `part_parents.json` (680) | part → outline tie-break for Warsaw OSM ids | replace (empty `{}`; regenerate if needed) |
| `monuments.py:1-420` | Warsaw monuments; docstring says the GUGiK DSM has no statues (the PNOA cloud may) | remove the data; keep `B`, `standing`, `rider`, `attach`, `build` |
| `roofgardens.py:1-35,71` | `WHOLE` (Kopernik) | remove the data; keep the engine |
| `voxelize.py:70` | colour alias for Hale Mirowskie | remove |
| `voxelize.py:520-523` | `WOOD_FLOOR = {603145360}` (Kopernik zouk floor) | remove |
| `voxelize.py:539-541,1282,1328-1331,1457-1485,1537-1561` | Złota: tree heights, boulder fountain, inferred lamps | remove (or generalise lamp inference along kerbs, as dtla's every 36 m) |
| `voxelize.py:1422-1455` | splash-pad fountain styled on Marszałkowska | keep (generic `fountain=splash_pad`), restyle |
| `voxelize.py:929-939` | Royal Route and MDM wall palettes | remove |
| `voxelize.py:1758-1844` | Most Świętokrzyski A-pylon and 48 stays | remove |
| `voxelize.py:1743-1757,1845-1873` | LiDAR pylons; inferred bridge lamps every 32 m | keep |
| `voxelize.py:1911-1926` | church windows (generic SACRED) | keep |
| `voxelize.py:1245` | `nd_mean < 32` "no trees taller than ~30 m in central Warsaw" | parametrise |
| `underpass.py:1-5` | generic level −1 passages (Warsaw names only in comments) | keep |
| `traffic.py:9`, `aoi.py:4` | signal axes assume the grid matches the Śródmieście street grid | parametrise (θ choice for Madrid) |

### 5. Labels, names and languages

| Ref | What | Action |
| --- | --- | --- |
| `labels.py:25` | `IN_WARSAW` regex strips "in Warsaw", "w Warszawie" and districts | replace (", Madrid", "de Madrid") |
| `labels.py:29-85` | `FAR_TIERS` (Polish names per distance tier); the assert at `:715-716` requires every label to be listed | replace (or default `far` from pageviews) |
| `labels.py:90-309,311-352,354-364` | `PICKS` (Warsaw QIDs), `SITES`, `NAMES` | replace |
| `labels.py:4,636-684`, `notable.py:1-98` | ranking by **Polish + English** Wikipedia views; `e["pl"]` used as the name | parametrise the local language → `es` |
| `wikidata.py:1-2,42,46` | `languages="pl\|en"`, field `pl` | parametrise → `es` |
| `places.py:20-23,61` | `PL_KIND`: Polish search synonyms per kind | replace (Spanish synonyms) |
| `places.py:53-55` | `english()` uses `name:en`, wikidata `en`, `pl` | parametrise |
| `labels.ts:57`, `types.ts:10-21` | pin shows `<b>name</b>` (local) + `en ?? kind` | keep the structure; decide order (CLAUDE.md: English name, Spanish where it differs) and log it in DECISIONS.md |
| `search.ts:14-15` | fold handles `ł` | keep (NFD already folds á, é, ñ); drop the `ł` rule |
| `bar.ts:81` | placeholder "Search Warsaw…" | replace |
| `main.ts:210` | `deckOK` regex `^(Most\|Kładka\|Wiadukt)` (Polish bridge words) | replace (`Puente\|Viaducto\|Pasarela`) |
| `main.ts:243-247` | search actions with Polish alt words (tramwaj, samochód, pieszy, …), "Zouk at Kopernik" | replace |
| `trees.py:43-46,59,83`, `voxelize.py:1405-1419` | `species_pl` → `pl` field, "brak danych" | replace with `species_es` and the Madrid field mapping (one place, documented in NOTES.md) |

### 6. Trees, species and phenology

| Ref | What | Action |
| --- | --- | --- |
| `fetch_trees.py:1-108` | Warsaw BOS themes, crowns per district (`CROWNS` `:30-31`) | replace (datos.madrid.es inventory) |
| `trees.py:32-86` | field names from Polish sources: `NUMER_INW`, `Nazwa polska/łacińska`, `Obwód pnia w cm`, `Jednostka zarządzająca`, `wysokosc`, `srednica_k`, `stan_zdrowia`, `gatunek(_1)`, `pnie_obwod`, `x_wgs84` | replace (Madrid field mapping) |
| `trees.py:101-136`, `voxelize.py:1398` | `attach_crowns` (Mapa Koron Drzew, `Gatunek ŁC:` label parsing) | remove |
| `trees.py:89-94` | `CONIFER` genera | keep and extend (Cupressus, Cedrus, Pinus pinea, Cupressocyparis) |
| `voxelize.py:1219-1223,1308-1335,1413-1420` | tree DB merge, trunks; `sources` text names Warsaw services | keep the logic; replace the source strings |
| `phenology.py:56-80` | classes keyed on DWD German species files (Spitz-Ahorn, …); `CROWN_SP` Polish crown groups | replace (Madrid street-tree mix: Platanus, Ulmus pumila, Sophora / Styphnolobium, Celtis, Ligustrum (evergreen), Pinus pinea, Cupressus, Melia) |
| `phenology.py:19-22,50-55`, `grass_photos.json`, `foliage_photos.json` | Warsaw lawn colours by month; autumn colours from Commons photos | replace (Madrid lawns: summer brown-out) |
| `phenology.py:54-55`, `roofgardens.py:23`, `voxelize.py:132-133` | `GREENS`, `PLANTS`, `LEAVES`: the same palette in three places | parametrise (one source) |

### 7. River (Vistula) and flood

| Ref | What | Action |
| --- | --- | --- |
| `flood.py:1-96` | Vistula spill and bed model: left walled bank (`:51-57`), thalweg, Warszawa-Bulwary gauge (IMGW 152210170, zero 75.168 m EVRF2007, `:86-95`), hard-coded quantised water RGB `(104, 100, 80)` (`:25`) | remove (the Manzanares is a small, weir-controlled channel) or replace with a simpler model; the RGB must follow `C["water"]` if kept |
| `flood.ts:1-75` | river sheet, sandbanks, gauge in cm "Warszawa-Bulwary" (`:44`) | remove or replace |
| `main.ts:34-35,63,81-82,294-295,306,342-346` | `RIVER` gauge marks (record low, typical, 2010 and 1844 floods), river slider wiring | remove or replace |
| `bar.ts:65-99` | river slider, "Vistula N cm" (`:86`) | remove or replace |
| `types.ts:54-59` | `FloodInfo` | follows the flood decision |
| `landmarks.py:718-732`, `EXTRA_LABELS["Wisła"]` | river label on the largest water body | keep `river_spot`; replace the label |
| `voxelize.py:525-537` | flattens water bodies of 400 cells or more | keep |
| `perf_stats.py:23` | `'river'` analytics action | follows the analytics decision |

### 8. Trams, trains, traffic and street life

| Ref | What | Action |
| --- | --- | --- |
| `traffic.py:106-128` | `BIKE_BRIDGES` (Vistula bridges, ZDM counts), "Bulwar"/"Wybrzeże" weighting | replace (Madrid Río, Calle Mayor, …) or drop to a weight of 1 |
| `traffic.py:622-716` | tram routes from OSM `route=tram` | keep (generic). Madrid's centre has no trams, so the list will be empty; check the viewer copes with empty `trams` |
| `traffic.py:717-762` | trains from `route=train` (Warsaw cross-city tunnel in the comments) | keep (Cercanías are mostly underground in the centre) |
| `voxelize.py:1990-2004` | `meta.trams` paths (unused by the viewer) | remove |
| `sim/meshes.ts:50-51` | tram geometry with Warsaw livery (yellow body, red skirt) | replace or remove |
| `sim/trains.ts:17-24` | liveries by operator regex: SKM, Koleje Mazowieckie, Polregio, PKP Intercity | replace (Renfe Cercanías, AVE/Avlo, Ouigo, Iryo) |
| `sim/life.ts:21-27,94-101,118` | tram constants (3 × 10.5 m sections, 5 min headway), tram hours (none 0:30-5:00) | parametrise or remove with the trams |
| `sim/life.ts:112-121,382` | daily density curves: Warsaw commute peaks 8 and 17; bike curve from ZDM counters | parametrise (Madrid: later peaks, lunch 14-16, late evenings) |
| `hud.ts:23,51`, `nav/ride.ts:10`, `main.ts:233-237,243` | "Following a tram", tram camera rig, "Follow a tram" | follows the tram decision |
| `sim/dance.ts:1-40` | zouk at Kopernik | remove |
| `fountains.ts:3` | Złota fountain comment (the code is generic over `meta.jets`) | keep |

### 9. Climate, sun and time

| Ref | What | Action |
| --- | --- | --- |
| `sun.ts:1` | `LAT = 52.23`, `LON = 21.01` | parametrise (40.4168, −3.7038; better read from `meta`) |
| `sun.ts:7-10` | EU DST rule, UTC+1/+2 | keep (Madrid is also CET/CEST) |
| `climate.py:1-64` | Warsaw ERA5 climatology (snow days, cover) | parametrise the location; keep the method |
| `weather.ts:10-15,21-28` | presets, snow offered by climate | keep |
| `window_photos.py:22,25-38` | `Europe/Warsaw` and Warsaw lat/lon in `sun_elevation` | parametrise |
| `main.ts:37-38` | `DAYS` (midsummer, midwinter) | keep |

### 10. Lit windows at night

| Ref | What | Action |
| --- | --- | --- |
| `window_counts.json`, `window_photos.json` | 268 Warsaw facades counted from Commons night photos | keep as a placeholder or replace with Madrid counts (a separate research task) |
| `window_stats.py`, `windows.py`, `windows.ts` | generic (OSM building kinds, hour bins) | keep |
| `voxelMaterial.ts:255-265` | facade window grid every 3 m bay, 4 m storey (a 1 m assumption) | keep (note in the 1 m assumptions) |

### 11. Palette and colours

| Ref | What | Action |
| --- | --- | --- |
| `voxelize.py:115-135` | `C` ground palette, `LEAVES`, `PERENNIALS`, `WALL_DEFAULTS` (Warsaw beige, grey and green) | parametrise (Madrid palette: warmer ochre and brick, light granite paving, drier greens); log in DECISIONS.md |
| `voxelize.py:70-77` | `COLOUR_ALIASES` | keep (drop the Hale Mirowskie line) |
| `voxelize.py:891-893,934,939` | Old Town, Royal Route and MDM palettes | replace with a Madrid historic-core palette or remove |
| `voxelize.py:944-989` | roof heuristics: ortho-derived colour, red tiles, copper patina, Warsaw-specific thresholds | keep the logic; retune (Madrid: slate on the Austrias towers, terracotta tile, many flat terraces) |
| `voxelize.py:908-909` | glass when taller than 45 m and office-like | keep, check on AZCA |
| `voxelize.py:1381` | `NEEDLES` conifer colours | keep |
| `sim/life.ts:24-25` | car and shirt colours | keep |
| `sky.ts:120-121` | PKiN light colours | remove |
| `index.html:48`, `style.css` | loading gradient, UI colours | keep |

### 12. UI text, page meta, credits, analytics, packaging

| Ref | What | Action |
| --- | --- | --- |
| `index.html:6-16` | title, description ("Walk around the Palace of Culture…"), og:url, og:image, og:image:alt pointing at `p.migdal.pl/warsaw-vibe-voxel` | replace |
| `index.html:17` | PKiN favicon | replace |
| `index.html:18-42` | PostHog bootstrap; enabled only on host `p.migdal.pl` (`:22`); `eu.i.posthog.com` | remove (or keep inert and parametrise the host) |
| `stats.ts:24-48`, `package.json:14` (`posthog-js`), `.github/workflows/pages.yml` (`VITE_POSTHOG_PROJECT_TOKEN`), `perf_stats.py` | analytics | remove (or the user's own project); log the decision |
| `main.ts:84-85` | credits: Piotr Migdał with a second, AI-model credit (quesma blog link), source link to stared/warsaw-vibe-voxel, "based on GUGiK 2025" | replace: the user as author, "based on warsaw-vibe-voxel by Piotr Migdał (MIT)", data credits (IGN/CNIG CC BY 4.0, OSM ODbL, Ayuntamiento, Catastro); no AI credit (project attribution rules). Done in Phase 0 and Phase 3 |
| `web/package.json:2` | `"name": "warsaw-voxel"` | replace |
| `pyproject.toml:2` | `name = "warsaw-voxel-data"` | replace; add the LiDAR dependencies (laspy or PDAL) |
| `stats.ts:21,28` | sessionStorage key `wv-last` | keep |
| `web/public/preview.jpg` | Warsaw og image | replace |
| `README.md`, `IDEAS.md`, `research.md`, `research_astoria.md`, `research_oldtown.md`, `research_vistula.md`, `visual_ref.md` (repo root) | Warsaw documentation and research | move to `docs/warsaw/` or remove; rewrite README for Madrid with the data attributions |
| `.github/workflows/pages.yml` | Pages deploy | keep (minus the PostHog env) |

### 13. Things that will crash on Madrid data first

1. `voxelize.py:667`: `next()` for "Pałac Kultury i Nauki" (StopIteration).
2. `voxelize.py:1762-1766`: the Most Świętokrzyski block is guarded (`is_empty`, `n_pyl`), so it is a no-op rather than a crash.
3. `landmarks.make_views` (`:745,818`): KeyError for PKiN and Warszawa Centralna.
4. `landmarks.details_geometry` (`:529-546`): writes into hard-coded grid boxes. It will not crash, but it corrupts the volume.
5. `labels.py:640,759`: missing `notable.json`; the `FAR_TIERS` assert (`:715-716`).
6. `roofgardens.py:22`: missing `phenology.json`.
7. `flood.py:28`: `np.argmax(np.bincount(...)[1:])` assumes a water body exists; the gauge at `:90` is outside the grid.
8. `voxelize.py:145`: DTM nodata.

## 1 m assumptions

Inventory of every place in the Warsaw snapshot where one voxel = 1 m is fixed, explicitly or implicitly. It is the
starting point for a single shared `VOXEL_SIZE` constant. Line numbers refer to the snapshot as imported.

**The root assumption.** The grid unit *is* the metre. `scripts/aoi.py:21` sets `W, D = 3950, 4430` "m", and
`to_grid`/`to_world` (`aoi.py:29-36`) map metres to cells with no scale factor. So in every later step a cell index,
a distance in metres and a z level are the same number. The viewer inherits this: the mesher emits vertex positions in
metres (`mesher.worker.ts:248`, `p * s + x0`), and the shaders and `World` then treat `floor(position)` as the voxel
index. Moving to another voxel size therefore means separating two quantities everywhere: **metres** (scene units,
camera, physics, object sizes) and **cells** (array indices, run lengths, kernels).

Recommended convention for the port: keep **three.js scene units in metres** and convert at the tile boundary. Then
the many purely metric constants (camera, fog, vehicles, speeds) need no change. They are listed below as
"metric", meaning they need retuning at most.

Note: the Warsaw build has **only two LOD levels, 1 and 8** (`scripts/tiles.py:24`). The 2 m and 4 m levels do not
exist. `s` means both "metres per cell" and "cells per block" at the same time.

### Tile format and level structure

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `scripts/tiles.py:3-10` | format docstring | "Level 1 is the city at 1 m", "node spans 128 * s metres", ground "in metres (z of the first free voxel at level 1)" |
| `scripts/tiles.py:23` | `N = 128` | cells per node side; a level-1 node is 128 m only because the cell is 1 m |
| `scripts/tiles.py:24` | `LEVELS = (1, 8)` | `s` is used both as block factor (cells) and as metres per cell |
| `scripts/tiles.py:31-32` | `need = s**3 // 4`, `band = 256 // s` | block occupancy in cells; memory band in cells |
| `scripts/tiles.py:88`, `:152` | `gs = g[::s, ::s]` | ground in level-1 cells, which equal metres |
| `scripts/tiles.py:102`, `:106`, `:152` | `gw` uint8, `np.clip(gs, 0, 255)` | ground stored as **uint8 metres = level-1 cells**: at most 255 cells of relief above `BASE` |
| `scripts/tiles.py:79` | runs `uint16 (z0, len, palette)` | z in cells of the level: up to 65 535 cells |
| `scripts/tiles.py:131-147` | `export_region`: `span = N * s`, windows `"1 m window"` | box in level-1 cells, called metres |
| `web/src/types.ts:29-33`, `:52-60` | `TileLevel {s}`, `Meta.tiles`, `ColumnData.ground: Uint8Array` | the viewer reads `s` as metres per cell |
| `web/src/stream.ts:43`, `:74-77` | `bounds()`: `L = N * s`, clamp to `meta.W/D` | node extent in metres equals cells × s; `meta.W/D` are cells used as metres |
| `web/src/stream.ts:96-101`, `:162`, `:167` | foliage nodes and building ids only at `s === 1` / `key(1, …)` | level 1 is hard-coded as "the finest level" |
| `web/src/stream.ts:171-175` | `buildingIds(x0, y0)` indexes `bldMap` (1 m raster) with node metres | metres used as raster index |
| `web/src/stream.ts:246-253` | `ensure(x, z, r = 120)` | `L = N * fine` metres, r in metres |
| `web/src/mesher.worker.ts:1-3` | header: "N x N cells of s metres" | |
| `web/src/mesher.worker.ts:34-40` | `decode`: counts u16, ground **u8**, runs u16 | same layout as `tiles.py` |
| `web/src/mesher.worker.ts:74`, `:87-91` | `pos: Int16Array`; `attr` uint8 = `[normal, ao, ground, scale]` | positions are **integer metres**, so 0.5 m vertices cannot be stored; `scale = s` in uint8 cannot hold 0.5 (unused in the shaders); `ground` uint8 metres |
| `web/src/mesher.worker.ts:165-169`, `:237-238` | face key `((ang*4096 + pal)*256 + ao)*256 + gm)*16384 + bid` | ground packed in 8 bits (< 256), so relief above `BASE` must stay below 256 units |
| `web/src/mesher.worker.ts:248` | `out.vertex(p[0]*s + x0, p[2]*s, p[1]*s + y0, …)` | cell to metre conversion with 1 m implicit at level 1 |
| `web/src/mesher.worker.ts:184-210` | `wallAngle`: 5×5 neighbourhood, straight run `k <= 4`, `gl >= 3` | cells (a 2 m / 4 m wall at 1 m) |
| `web/src/mesher.worker.ts:213-221` | `faceAO`: AO from the 8 neighbour cells | AO radius = 1 cell |
| `web/src/world.ts:34-36`, `:45` | node lookup `L = N * s`; column index `floor((x - x0)/s)` | x/r arguments in metres treated as level-1 cells |
| `web/src/world.ts:50`, `:70`, `:78`, `:86` | `ground[i]` returned as metres | uint8 ground = metres |
| `web/src/world.ts:56`, `:70`, `:77`, `:88` | `zc = floor(z / n.s)`, `(z0 + len) * n.s` | z cells to metres via `s` only |
| `web/src/world.ts:108-114` | `gz = ground / n.s`, `2 / n.s`, `2.5 / n.s` | ground metres to cells assume level-1 cell = 1 m |

### Height encoding (checked against `web/public/data`)

- **Tiles** (`tiles/{1,1f,8}/{tx}_{ty}.bin`): gzip of `counts uint16[(N+2)²]` (33 800 B), `ground uint8[(N+2)²]`
  (16 900 B), then `runs uint16[3 × Σcounts]`. All 2 190 files decode with `len(runs) == sum(counts)`.
  Measured: `meta.json` gives `H = 351`, `base = 73` (m a.s.l.), levels `{s:1, 31×35}` and `{s:8, 4×5}`, and 3 402
  palette entries. The highest run top is 351 cells at level 1, 83 in `1f` and 39 at level 8. The highest ground
  byte is 46.
- **Maximum representable height:** `z0` and `len` are uint16, so a column can reach 65 535 cells: 65.5 km at 1 m,
  32.7 km at 0.5 m. **A 250 m building at 0.5 m (500 levels) plus Madrid's relief fits easily in the runs.** The limits
  are elsewhere:
  - `ground` is **uint8** (tiles, `mesher.worker.ts:36`, `:90`, `:169`; `types.ts:58`). It holds 255 metres above
    `BASE` today. Stored in 0.5 m cells, it would hold only 127.5 m. Central Madrid spans roughly 590 m
    (Manzanares) to over 650 m (Sol/Chamberí, higher further north), around 100 m or more, so cells need uint16.
    Keeping metres in uint8 also works, but loses the half-metre ground step the facade shader keys on.
  - `world.ts:140-141` raycast stops at `y < 420` / `y > 420` (metres above `BASE`). Torre Picasso and the Cuatro
    Torres (about 250 m) on ground about 100 m above the lowest DTM point would reach about 350-380 m: close to the
    limit.
  - `city.ts:97` frustum box for tile visibility is `0..330` m high: Madrid's towers would be clipped from the
    "in view" test.
  - `main.ts:274` builds the map box as `(W, H, D)`, using `meta.H` (cells) as metres. It feeds `daylight.fitShadow`
    (`daylight.ts:181`).
- **`terrain.bin`** (`scripts/terrain.py:5-7`, `:15-24`; read in `web/src/city.ts:238-256`): gzip of
  `uint16[ceil(D/4), ceil(W/4)]` heights in **decimetres above `BASE`** (max 6 553.5 m; measured 3.8-45.5 m), then
  `uint8[D//2, W//2, 3]` sRGB. Measured size 15 313 283 B uncompressed, exactly as expected. The height encoding does
  not depend on voxel size, but **`STEP = 4` and `[1::2, 1::2]` are in cells**, while the viewer hard-codes 4 m and
  2 m (`city.ts:240`, `:241`, `:253`, `:254`, `C = T / 4`). Both sides must change together.

### Rasters beside the tiles (one value per 1 m column)

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `scripts/zones.py:8`, `:113` / `web/src/city.ts:42`, `:64-66`, `:87` | `zones.bin` = uint16 block[D,W] + uint16 building[D,W]; R16UI texture W×D; `bldAt` rounds metres to the index | one texel per cell = per metre |
| `scripts/zones.py:62`, `:103-108` | large blocks split on a 256-cell grid; triangle cost per 128 m tile spread over `16384` = 128² columns | 128 cells = 128 m |
| `scripts/windows.py:7`, `:74-75` / `web/src/windows.ts:15` / `voxelMaterial.ts:187` | `windows.bin` uint8[D,W]; `texelFetch(uWinMap, ivec2(cell.xz))` | cell index = metre = texel |
| `scripts/flood.py:5`, `:40`, `:80-85` / `web/src/flood.ts:20-29`, `:63-66` / `voxelMaterial.ts:307` | `flood.bin` two uint8[D,W]; spill level in metres; `texelFetch(uFlood, floor(vW.xz))` | world metres used as texel index |
| `scripts/phenology.py:270-276` / `web/src/foliage.ts:14` / `voxelMaterial.ts:115`, `:132`, `:351` | `foliage.bin` on a 2-cell grid (`W // 2`, `* 2 + 1`); shader `ivec2(cell.xz * 0.5)` | "2 m" texels = 2 cells |
| `web/src/voxelMaterial.ts:88-104` | lamp-pool canvas `W*0.5 × D*0.5` ("2 m texels"), pool radius `20 * s` | metres = cells |
| `scripts/voxelize.py:2004-2009` | `qa_roadmask.bin.gz` uint8[D,W] | per cell |
| `scripts/voxelize.py:1975-1976` | `data/ground.npz`: `g` int16 (cells), `rgb` per cell | g in cells, read as metres by `terrain.py` |

### Pipeline rasters: resolution and metres-to-cells conversions

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `scripts/aoi.py:21`, `:29-36` | `W, D` and `to_grid`/`to_world` | 1 grid unit = 1 m (root assumption) |
| `scripts/prep.py:1-3`, `:52-59`, `:71-78` | DSM resampled at 0.5, DTM at 1.0, ortho at 0.2 "grid units"; `nj = D / out_res` | output resolutions are fractions of a 1 m cell |
| `scripts/voxelize.py:139-141` | `dsm.reshape(D, 2, W, 2)` max/mean | **2 = 1 m / 0.5 m DSM** samples per cell |
| `scripts/voxelize.py:203-208` | `wall_clean`: `n_up` on 2×2 samples; `nd_max_b … reshape(D, 2, W, 2)` | same factor 2 |
| `scripts/voxelize.py:205` | `orto.reshape(D, 5, W, 5, 3)` median | **5 = 1 m / 0.2 m** ortho pixels per cell |
| `scripts/voxelize.py:725-726` | DSM roughness `uniform_filter(dsm, 6)` then `reshape(D, 2, W, 2)` | 6 samples = 3 m; factor 2 |
| `scripts/voxelize.py:144-145` | `SLAB = 3`, `BASE = floor(dtm.min()) - SLAB` | 3 cells of soil = 3 m |
| `scripts/voxelize.py:163` | `g = round(ground - BASE)` | metres to cells with no division |
| `scripts/voxelize.py:166`, `:1055-1057` | rounding pits "1 m under all eight neighbours"; retaining walls "2 m or more" (`g - nb_lo >= 2`) | thresholds in cells |
| `scripts/voxelize.py:1041-1043` | `H = top + g + 12`; `vol = np.zeros((H, D, W), uint16)` | whole volume in RAM, sized in cells |
| `scripts/voxelize.py:215-235` | `cells_of`/`burn`: `Affine.translation(c0, r0)` / `Affine.identity()` | 1 grid unit per raster pixel |
| `scripts/terrain.py:15-20` | `STEP = 4`, `[1::2, 1::2]` | cells = metres |
| `scripts/traffic.py:3-4`, `:46-104` | traffic.json "coordinates in grid metres … z = voxel level"; `fit(step=0.5)`, `dz in (0, 1, -1)` ("the surface steps a metre at a time"), `int(8 / step)` | metres = cells, z level = metres |
| `scripts/traffic.py:296-297`, `:522-524`, `:620` | `z = int(g + round(nd_mean))`, `+ 2.5` headroom, signal heads `z_at` | DSM metres added to cell levels |
| `scripts/debris.py:9` | `max_size=100, B=256, M=24` | voxels and band sizes in cells |

**Morphological kernels and buffers in cells** (each is "N m" in the comments). In `scripts/voxelize.py`: 143,
156-160 (3, 5, `gaussian 1.5`; "3 m"); 180-181 (7: "3.5 m"); 193 (`grey_opening 13`: "6.5 m opening"); 359-360
(median 9); 368, 1149, 1250 (opening 1); 734 (dilate 4 / 3); 758-759 (erode 1, median 3); 790 (median 5); 873-874
(closing 3, pits 1-3 m); 1012 (`edt <= 1.5`: "2 across on a diagonal"); 1028 (dilate 2); 1156 (max 7, `- 6` m);
1207 (`edt <= 2`); 1228 (dilate 3); 1240-1243 (max 7, 3); 1255-1262 (gaussian 2 / 3, dilate 2 "within 2 m");
1283-1293 (dilate 2, edt); 1337-1339 (canopy peaks max 7, `>= 4` m, `_td >= 5` "5 m apart"); 1517-1523 (kerb
`edt <= 4`); 1587-1590 (dilate 3, closing 2); 1618, 1638 (median/uniform along a way, in 1 m samples); 1672 (dilate 15);
1712 (dilate 3); 1745 (opening 2); 2019-2020 (`edt <= 2`). Others: `scripts/roofgardens.py:82` (opening 2), `:158`
(min 5); `scripts/zones.py:48` (`buffer(1.5)`); `scripts/underpass.py:88-143` (buffers 0.5-3.0 used as cells);
`scripts/places.py:93`, `:100`; `scripts/labels.py:556`, `:669`.

### Object scales: trees, street furniture, crossings, fountains

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `scripts/voxelize.py:372-374` | `HW` road widths (m) buffered as cells | metres = cells |
| `scripts/voxelize.py:553`, `:560-563` | zebra crossing `buffer(1.5 / 2.2)`, stripes `int(tpos) % 2` | **1 m stripes = 1 cell** |
| `scripts/voxelize.py:575`, `:591-592`, `:602` | lane width `lanes * 3.1`; dashes every 9 m, 3 m long; junction `+ 4` | metres = cells |
| `scripts/voxelize.py:1523`, `:1531-1535` | lamp post: kerb within 4 cells; height 10/6 (or OSM `height`) cells; head = 1 voxel | **lamp = 1×1 cell column**, z in cells |
| `scripts/voxelize.py:1544-1561` | inferred Złota lamps every 18 m, ±5.5 m, 9 m apart, 6 cells tall | metres = cells |
| `scripts/voxelize.py:1567-1569`, `:1574-1575` | shelter roof at `g + 2`, posts every 3rd cell; flagpole 9 cells | |
| `scripts/voxelize.py:1302-1306`, `:1393-1396` | trunks: 1 cell, "thick" = 2×2 cells | **trunk width = 1 or 2 cells** |
| `scripts/voxelize.py:1309-1316` | tree placement `2 <= c < W-2`, snap `<= 2.5`, `<= 3` | |
| `scripts/voxelize.py:1365-1375` | crown dome `Rt + 0.7`, `0.62 * Ht`, `max(dep, 1)`, `bot >= 2` | cells |
| `scripts/voxelize.py:1450` | fountain jets `[c + 0.5, z0 + 1, r + 0.5]` | cell centres emitted as metres |
| `scripts/voxelize.py:1440-1506` | fountain granite and rings about 2 m apart, oval `/4.5`, `/6.5`, planted beds | cells |
| `scripts/voxelize.py:1592`, `:1605` | bridge deck: DSM sampled "every metre", `arange(-1.5, 1.6, 0.5)` | |
| `scripts/voxelize.py:1998-2001` | tram paths every 2.0 m, `z = int(g[r, c])` | z cells written as metres |
| `scripts/landmarks.py:504-527` | `small_tree`: height 7-9 cells, trunk `>= 3`, crown radius `0.6 + 1.3 sin`, `±2` cells | **procedural tree in cells** |
| `scripts/trees.py:55`, `:78` | OSM and old-inventory join radius 2.0 / 1.5 (grid metres) | metres = cells |
| `web/src/fountains.ts:9`, `:20-22` | jet cylinder r 0.07-0.11, 1 unit tall scaled 0.4-2.2; phase `x*0.35`, `y*0.2` | metric; positions from `meta.jets` (cells) |
| `web/src/foliage.ts:14` | foliage map `W >> 1` | 2-cell texels |
| `web/src/sim/meshes.ts:42-68` | cars 1.8×4.4 m, trams 2.4 m wide, people 0.46 m / 1.7 m, bikes, signal poles 3.3 m | metric (no change while the scene is in metres) |
| `web/src/sim/trains.ts:15`, `:47-50` | `CAR = 20`, `GAP = 1`, `V = 16`, body 2.9×2.75 m | metric |
| `web/src/sim/life.ts:16-23`, `:405-414`, `:750-753` | `LANE_W 3.0`, `TRAM.sec 10.5`, `ACTIVE_R 900`, grids 8 / 32 m, signal lamp offsets | metric |
| `web/src/sim/crossings.ts:21`, `web/src/nav/spots.ts:18` | spatial hash `G = 32`, 64 m | metric |
| `web/src/sim/dance.ts:7` | `DANCE` at grid `(2626.2, 741.0)`, radii 3.6 / 5.0 | grid position (cells) used as metres; Warsaw-specific |
| `web/src/nav/ride.ts:7-10` | camera rigs: eye 1.62 / 1.3 / 2.1 m, back 4.5-26 m | metric |
| traffic.json / meta.json (`trams`, `lamps`, `jets`, `labels`, `views`) | written in cells, read as metres | cells = metres |

### Landmarks and hand-tuned corrections in voxel coordinates

All of this is Warsaw-specific and will be rewritten for Madrid. The point is that **the new code should be authored in
metres and converted**, unlike this code.

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `scripts/landmarks.py:150` | `VARSO = Point(244, 2694)` | grid cell |
| `scripts/landmarks.py:968` | `regularize_walls(L=3, Lo=2, min_area=30)` | cells ("m") |
| `scripts/landmarks.py:1045` | `pkin_regularize(L=7, Lo=3, min_area=150)` | cells |
| `scripts/landmarks.py:1197` | `pkin_clock(z_rel=165, R=3.2)` | cells |
| `scripts/landmarks.py:1321` | `paint_windows(w=2, h=2, depth=1, plane_tol=3)` | window = 2×2 cells |
| `scripts/landmarks.py:1378` | `pkin_low_windows(bay=6.3, lo=26)` | |
| `scripts/landmarks.py:1449-1451`, `:1677`, `:1706` | `PK_SHAFT*`, `PK_TOWERS`, porticos, balustrade box `(2360, 2660, 600, 900)` | row/col boxes |
| `scripts/landmarks.py:1754` | `edge_windows(w=2, margin=2.5, min_len=6, depth=1)` | cells |
| `scripts/landmarks.py:1952`, `:2034`, `:2266-2267`, `:2353`, `:2356`, `:2542`, `:2579-2580`, `:2783`, `:2876`, `:2971`, `:3042`, `:3101-3102`, `:3164`, `:3192` | church centres and radii, bridge piers, wings `depth=17, H=18`, boxes, masts `(row, col, radius)` | grid cells |
| `scripts/landmarks.py:2762` | `_pier(…, step=0.5)` | sub-cell sampling of 1 m cells |
| `scripts/landmarks.py:201-320`, `:416-420`, `:450-475` / `scripts/overrides.json` | stripes `width` (m along the perimeter), bands `to` (m), checker `cell [w, h]` (m), `mast_h`, crown `height`, `min_part_height` | **authored in metres, applied as cells** |
| `scripts/monuments.py:4-8`, `:28`, `:451-470` | monument boxes `a, b, w, d, z0, z1` in metres, rasterised with `cc + 0.5 - c0`, `range(int(z0), ceil(z1))` | metres = cells; needs a `/ VOXEL_SIZE` |
| `scripts/patch.py:21-31` | `BOXES` "rows, cols of the 1 m grid" | cells |
| `web/src/main.ts:246` | Zouk at `goPlace(2626, 2021, …)` | grid position |

### Viewer: shading that keys on cells

| file:line | what | how it depends on 1 m |
| --- | --- | --- |
| `web/src/voxelMaterial.ts:214`, `:398`, `:420` | `cell = floor(vVox - vN * 0.5)` | half-voxel step back along the normal; voxel index = floor(metres) |
| `web/src/voxelMaterial.ts:216` | `lvl = cell.y - vGz` | storey arithmetic in cells over uint8 ground metres |
| `web/src/voxelMaterial.ts:224-265`, `:268-283`, `:325-333` | windows: storeys `mod(lvl, 3/4)`, bays `mod(u, 2/3/4/5)`, rooms `/4`, `/6`, `/12` | **a storey is 3-4 cells, a window 1-2 cells** |
| `web/src/voxelMaterial.ts:277` | PKiN wash `smoothstep(20, 28, lvl)`, `28..190` | cells |
| `web/src/voxelMaterial.ts:179-180`, `:220`, `:190`, `:359`, `:365` | per-cell hash noise; `floor(cell.xz / 24)`; snow patches `/3`; puddles `/2`, `/7` | texture frequency per cell |
| `web/src/voxelMaterial.ts:319` | soil strata `mod(cell.y, 5)` | cells |
| `web/src/voxelMaterial.ts:371` | lamp light falls off over 16 (m above ground) | metric, but `gz` is uint8 metres |
| `web/src/voxelMaterial.ts:159` | hidden buildings folded to `vattr.z - 3.0` | 3 m under ground |
| `web/src/voxelMaterial.ts:169` | `uZBlk` fetched at `ivec2(c.x, c.z)` | 1 texel per cell |
| `web/src/voxelMaterial.ts:442-445` | staircase walls: shadow normal bias `+ 1.2` ("its 1 m steps") | tuned to a 1 m step |

### Viewer: shadows, lighting, camera, navigation, streaming, fog

These are metric. While the scene stays in metres they keep working, but several were tuned for 1 m detail.

| file:line | what | notes |
| --- | --- | --- |
| `web/src/daylight.ts:45-50`, `main.ts:58` | shadow map 4096 (2048 on phones), `bias -0.0004`, `radius 3` | at full extent (`R` up to `0.75 * max(W, D)`, `:162`) a texel is about 1.6 m, too coarse for 0.5 m voxels |
| `web/src/daylight.ts:114` | `normalBias = clamp(0.3 / L.y, 0.5, 3)` | 0.5-3 m: up to 6 half-metre voxels of light leaking |
| `web/src/daylight.ts:160-163`, `:178`, `:185-186` | fit `R >= 300`, refit grid `Rq/16`, sun 2 500 m away, `near = -b.max.z - 700` | metric |
| `web/src/daylight.ts:135`, `web/src/post.ts:46` | N8AO `aoRadius 6-9`, `distanceFalloff 1.5` | metric; relative to voxel detail |
| `web/src/daylight.ts:136`, `:149-155` | fog `2500..7000`, `near = max(2500k², dist·…)`, `far = near + 4500k` | metric |
| `web/src/sky.ts:71` | sky sphere r = 6 000 | metric |
| `web/src/post.ts:32`, `:37`, `:60-62` | tilt-shift focus 500, enabled above 60 m, ramps 250 / 1200 / 1500 | metric |
| `web/src/main.ts:55` | camera `near 0.5`, `far 9000` | metric; `near` is half a 1 m voxel |
| `web/src/main.ts:109` | orbit `minDistance 4`, `maxDistance 7000` | metric |
| `web/src/main.ts:207-214`, `web/src/labels.ts:45`, `:65`, `web/src/nav/spots.ts:55`, `:66-74`, `web/src/nav/nav.ts:350`, `:366` | `x + 0.5`, `y + 0.5`, `z + 1` | **cell centre and one cell up, assumed to be 0.5 m and 1 m** |
| `web/src/main.ts:254`, `:274`, `:317`, `:446` | keepInside margins 60 / 1 500; map box `(W, meta.H, D)` (cells); `+3`, fallback 18; nearest label 400 m | |
| `web/src/nav/nav.ts:32` | `STEP 1.05`, `HEAD 1.9`, `GRAV 16` | step-up of 1.05 m means "climb a single 1 m voxel"; at 0.5 m walkers would climb two-voxel steps |
| `web/src/nav/nav.ts:420-426`, `:478`, `:550` | fly speed `8 + 0.9·h` (≤ 400 m/s), ceiling 3 600; walk 6 / 20 m/s; ride 2.2 / 7 | metric |
| `web/src/nav/nav.ts:196-197`, `:280`, `:306-310`, `:335`, `:443`, `:453-456` | landing offsets, map margin 61, sky view 60 / 380 / 330, `ensure(…, 200)`, clearance `tg + 2`, body probes ±0.3 / ±0.4 | |
| `web/src/nav/spots.ts:6`, `:16`, `:42`, `:50`, `:54`, `:82` | `EYE 1.7`; net every 3 m; search ±30 step 3; grid step 4 / 2; `clearAround(…, 40)`; spiral `rad < 60` in unit steps | grid steps are cells |
| `web/src/world.ts:97-100` | deck: `≤ 35` m over ground, probes ±3 cells, `≤ 1.5` m | |
| `web/src/world.ts:113` | "1-voxel runs are no ceiling" (`len > 1`) | cells |
| `web/src/world.ts:119-127` | `blocked` steps `z` by 1; `clearAround` probes ±1 cell, 3 m high | 1 m step |
| `web/src/world.ts:130-147` | `raycast`: DDA on unit cells (`floor(o)`, `x += sx`), max 20 000 steps, `y < 420` | **steps 1 m cells**; at 0.5 m it would skip half-voxels and the step cap halves the range |
| `web/src/city.ts:8` | `T = 128` | level-1 node size in metres (= N × 1 m) |
| `web/src/city.ts:28`, `:31`, `:34`, `:104`, `:114-118`, `:172-175`, `:218` | `dims[1]`, `dims[8]`, `request(8, …)`, `request(1, …, keep = true)`, `n.s === 8 / 1` | levels hard-coded as 1 and 8 |
| `web/src/city.ts:48-52`, `:67`, `:87`, `:101` | `tilesIn` (zone bboxes in cells ÷ T metres), `bdist`, `bldAt`, `away` | cells = metres |
| `web/src/city.ts:97` | visibility box height 330 m | too low for Madrid's 250 m towers on high ground |
| `web/src/city.ts:9`, `:154-155` | progress rings at 1 km / 2 km | metric |
| `web/src/main.ts:42-48` | budget from 0.2 M to all `cityTris` (default 14 M); phones 0.75 M ("1 m tiles of the whole map need ~2 GB of GPU") | triangle counts scale with 1 / VOXEL_SIZE² |
| `web/src/stream.ts:131` | workers "hold ~35 MB" | per-tile dense volume `(N+2)² × (zmax+2)` uint16 (`mesher.worker.ts:115`) |

**Streaming and LOD criterion.** There is no screen-space error metric. `city.ts:70-85` sorts city blocks by distance
to the focus and fills a **triangle budget** (`main.ts:48`). What does not fit is shown as 8 m clay. Visibility is a
frustum test on 128 m boxes (`city.ts:93-100`), and priorities go by `seen` + distance (`city.ts:101-102`). Because
the budget counts triangles, the same budget covers about a quarter of the area at 0.5 m.

### Estimate: moving to 0.5 m voxels

**Files affected** (beyond any Madrid rewrite of `landmarks.py`, `monuments.py`, `overrides.json` and `patch.py`):
pipeline `aoi.py`, `prep.py`, `voxelize.py` (about 40 kernels, every `reshape(…, 2/5, …)`, all object sizes), `tiles.py`,
`terrain.py`, `zones.py`, `windows.py`, `flood.py`, `phenology.py`, `traffic.py`, `trees.py`, `underpass.py`, `debris.py`,
`roofgardens.py`, `labels.py`, `places.py`. Viewer: `types.ts`, `stream.ts`, `mesher.worker.ts`, `world.ts`, `city.ts`,
`voxelMaterial.ts`, `foliage.ts`, `windows.ts`, `flood.ts`, `fountains.ts`, `labels.ts`, `main.ts`, `daylight.ts`,
`nav/nav.ts`, `nav/spots.ts`, `sim/life.ts`, `sim/dance.ts`. The metric constants (camera, sim meshes, speeds, fog) can
stay as they are if the scene stays in metres.

**Data size.** Measured `du -b web/public/data` = 52.0 MB. Expected at 0.5 m for the same area:

| component | now (bytes, gz) | scaling | at 0.5 m |
| --- | --- | --- | --- |
| `tiles/1` (city without foliage) | 5 397 560 (raw 304.6 MB: 52.5 header + 252.1 runs) | columns ×4, runs per column about the same: surface-like | about 22 MB (raw about 1.2 GB) |
| `tiles/1f` (trees, grass) | 10 516 661 | crowns are speckled volumes: between ×4 and ×8 | about 42-84 MB |
| `tiles/8` (clay) | 529 375 | the same 8 m level (16 cells) | about 0.5 MB (but the build-time downsample works on ×8 voxels) |
| `terrain.bin` | 869 515 | ×4 if `STEP` stays in cells; ×1 if it moves to metres | 0.9-3.5 MB |
| `zones.bin`, `windows.bin`, `flood.bin`, `qa_roadmask.bin.gz` | 753 586 + 387 938 + 777 696 + 359 565 | ×4 per cell (or ×1 if kept at 1 m) | about 9.1 MB (or 2.3) |
| `foliage.bin` | 1 167 142 | ×4 if the 2-cell grid is kept; ×1 at 2 m | 1.2-4.7 MB |
| `meta.json`, `traffic.json`, `trees.json`, `places.json`, `zones.json`, `phenology.json`, `climate.json`, flood/windows JSON | 31.2 MB in total | feature counts, not resolution | about 31 MB |
| **total** | **52.0 MB** | | **about 105-155 MB** (desktop loads all tiles: about 16 MB today, 65-105 MB) |

**Memory and performance risks.**

- **Pipeline RAM.** `voxelize.py:1043` allocates the whole `(H, D, W)` uint16 volume: 351 × 4 430 × 3 950 × 2 B is
  about 12.3 GB today. At 0.5 m that is ×8, about 98 GB, so the volume must be built in bands (the plan's
  `dtla-voxel/voxelize.py` 128-row bands). Every `D × W` float raster in `voxelize.py` also grows ×4.
- **Source density.** NPC02 has about 5 pts/m², which is about 1.25 points per 0.5 m cell. Many cells would be empty
  without hole filling, which is why CLAUDE.md fixes the intermediate rasters at 1 m.
- **Browser heap.** Every level-1 node is requested with `keep = true` (`city.ts:104`) for collisions and raycasts.
  The raw column data, about 300 MB today, would grow to about 1.2 GB of JS typed arrays.
- **GPU.** Quads grow about ×4 (`main.ts:44`, "~2 GB of GPU" for the whole map, so about 8 GB). The triangle budget
  would put most of the city into clay. Mesher workers need about twice the dense slab per tile
  (`mesher.worker.ts:115`, z doubles).
- **Texture limits.** `zones` (R16UI), `windows` and `flood` are already W×D = 3 950 × 4 430 texels. At 0.5 m they
  would be 7 900 × 8 860, beyond `MAX_TEXTURE_SIZE` 8 192 on many GPUs and all phones. Keep these maps at 1 m and
  sample them with `floor(world_m)`.
- **Shadows.** The texel at full extent is about 1.6 m (`daylight.ts:162-164`), and `normalBias` 0.5-3 m. Half-metre
  detail would be lost in the shadows or leak light unless the fit range or the map size changes.
- **Shading semantics.** Facade storeys and window bays are counted in cells (`voxelMaterial.ts:224-283`). At 0.5 m a
  "3-cell storey" becomes 1.5 m, so these must become `lvl_m = lvl * VOXEL_SIZE`.
- **Physics.** `World.raycast` and `blocked` step 1 cell, `STEP 1.05` climbs one voxel, and `clearAround` probes ±1
  cell. All need cell sizes from `VOXEL_SIZE`.

**Tile-format changes needed for 0.5 m** (`tiles.py` + `mesher.worker.ts`/`stream.ts`/`world.ts`, only if the plan
allows it):

1. Add `voxel: VOXEL_SIZE` to `meta.json` and make `s` mean **cells per block** at every level. A node then spans
   `N × s × VOXEL_SIZE` m. Today `s` doubles as metres.
2. `ground`: uint8 metres → **uint16 cells**, or keep uint8 but define it explicitly as metres. Change the mesher's
   8-bit ground in the face key (`mesher.worker.ts:169`, `:238`) and `vattr.z` (uint8) to match.
3. Vertex positions: `Int16Array` in integer metres cannot hold 0.5. Emit positions in **cells** (Int16 holds up to
   32 767 cells, 16 km at 0.5 m) and apply `VOXEL_SIZE` in the vertex shader or the mesh matrix. Update
   `vVox`/`cell` in `voxelMaterial.ts` to match. Drop or redefine the uint8 `scale` attribute.
4. Runs `uint16 (z0, len, pal)` need no change. 250 m at 0.5 m is 500 cells plus about 200-260 cells of relief,
   far below 65 535.
5. Make `terrain.bin` and `foliage.bin` declare their step (or fix them in metres) so the pipeline and the viewer
   cannot disagree (`terrain.py:15`/`city.ts:240-254`; `phenology.py:270`/`foliage.ts:14`).

### Madrid code and `VOXEL_SIZE` (kept up to date)

`VOXEL_SIZE` is defined once in `scripts/aoi.py` and written to `meta.json` as `voxel`; the viewer does not read it yet. New Madrid code converts metres to cells through it:
- `aoi.py`: `W`, `D`, `to_grid`, `to_world`, `corners`, `grid_transform`;
- `prep_lidar.py`: the raster resolution comes from `pipeline.toml`, independent of `VOXEL_SIZE`;
- `prep.py`: Warsaw's fixed raster cell sizes (0.5 / 1 / 0.2 m) in metres;
- `voxelize_elevation.py`: heights to levels, `MIN_HEIGHT`, `DECK_THICK` and the terrain step;
- `fetch_trees.py`: the AOI margin.

Assumptions in Madrid code that still tie to 1 m:
- `voxelize_elevation.py` passes ground levels to `tiles.py`, which stores them as uint8 metres;
- its views' camera offsets (`+2.5`, `+1.5`) are in metres = levels;
- `zones` blocks use `tiles.N` cells.

## dtla-voxel analysis

Reference snapshot: `../dtla-voxel` at commit `90bc1a6ce6e87fa0eb93076557838ae1950bb778` (38 commits, MIT, "Copyright (c) 2026 SiGMan").
Read-only analysis, nothing was run. Paths below are relative to `../dtla-voxel` unless prefixed with `madrid:` (this repository, still the Warsaw snapshot).

Python deps (`pyproject.toml`): numpy, scipy, shapely 2, pyproj, rasterio, `laspy[lazrs]`, pillow, requests, trimesh (trimesh only for the Disney Hall model). Tests are plain `unittest` files `scripts/test_*.py`.

Pipeline order (`scripts/build_data.sh:7-12`): `fetch_lidar` -> `fetch_dem` -> `fetch_naip` -> `fetch_osm` -> `prep_lidar` -> `voxelize` (which calls `layers.build()`). Peak RAM about 4 GB, about 6 min (`build_data.sh:12`).

### Coordinate frame: `scripts/aoi.py` vs Warsaw `madrid:scripts/aoi.py`

| | dtla `aoi.py` | Warsaw `aoi.py` |
| --- | --- | --- |
| CRS | UTM 11N, EPSG:32611 (`aoi.py:369,387`) | PL-1992, EPSG:2180 (`madrid:aoi.py:7`) |
| Centre | `CENTER_LATLON` in WGS84, projected with pyproj (`:382,389`) | `CX, CY` in projected metres (`madrid:aoi.py:15`) |
| Rotation | `GRID_DEG = 52` (`:383`) | `THETA = radians(21.5)` (`:16`) |
| Extent | `U_MIN..U_MAX`, `V_MIN..V_MAX` around the centre (`:384-385`); `W, D` derived downstream (`prep_lidar.py:24`, `layers.py:30`) | `W, D` plus the centre's grid position `I0, J0` (`:21-22`) |
| Transforms | `utm_to_uv`, `uv_to_utm`, `lonlat_to_uv`, `uv_to_lonlat`, `corners_uv(margin)`, `bbox_lonlat(margin)` (`:393-419`) | `to_grid`, `to_world`, `world_bounds(margin)` (`:29-41`) |
| Paths | `CACHE` from `$DTLA_CACHE`, default **`C:\data\dtla-voxel-cache`** (Windows) (`:379`); `WEB_DATA` (`:380`) | relative `RAW = "data/raw"` (`:23`); other scripts use `data/...` paths |

**The axis conventions match.** In both, +column is (cos θ, sin θ) in world coordinates and +row is (sin θ, −cos θ), so row 0 is the north-west edge and rows grow roughly southward. dtla's grid cell is `(u − U_MIN, V_MAX − v)` (`osm.py:3,17`), and Warsaw's is `I0 + u, J0 + v'`. They are the same affine frame with a different origin parameterisation.

**Adaptation: low.** Keep the Warsaw API names (`CX, CY, THETA, W, D, I0, J0, to_grid, to_world, world_bounds`), because about 20 Warsaw modules import them. Add dtla's extras:
- `CACHE` read from `$MADRID_CACHE` (default `~/data/madrid-voxel-cache`);
- `WEB_DATA`;
- `corners_uv` / `bbox_lonlat` for the fetchers;
- lon/lat helpers through pyproj EPSG:4326 <-> **EPSG:25830**.

Put the centre, size and rotation in one config block (PLAN Phase 1 asks for rotation 0° first). Put `VOXEL_SIZE` beside them.

### `scripts/prep_lidar.py`: point cloud to rasters

- **What it does.** It reads every cached LAZ with `laspy` in a `multiprocessing.Pool` (`:56-57`). It drops noise classes 7 and 18 (`:34`) and reprojects with pyproj (`:31,35`, EPSG:3857 -> 32611, because the USGS EPT is in Web Mercator). It maps points into the rotated grid **directly from point coordinates** (`:36-39`), with no UTM raster and no resampling, which is exactly what PLAN Phase 2 asks for. It then accumulates per-cell statistics with `np.maximum.at / add.at / minimum.at` over flat arrays covering the whole AOI (`:48-69`). The output is `CACHE/lidar.npz` (`:77-79`).
- **Grid and statistics.** Column `i` along +u, row `j` along −v (`:3,37-38`).
  - `dsm`: **0.5 m** grid (2D × 2W), highest non-noise point, NaN where empty (`:7,59,72`).
  - `gsum`/`gcnt`: 1 m, sum and count of ground (class 2) z, so mean ground = gsum/gcnt (`:61-63`).
  - `bmax`: 1 m, highest bridge-deck point, class 17 (`:64-65`).
  - `n1`, `nl1`, `low1`: 1 m, for class 1 only. `n1` counts all points, `nl1` counts points that are not the last return, `low1` is the lowest z (`:66-69`).
- **Class inference.** Not in this file. `prep_lidar` only splits 2 / 17 / 1 because "the 2023 LA County survey only classifies ground (2), bridge decks (17) and noise" (`:4`). The inference happens in `layers.py`: buildings = OSM footprints × DSM (`layers.py:337-399`), "unmapped structures" = tall, not green, not near a footprint (`:401-442`), vegetation = NDVI or multiple-return vote (`:403,503-505`), with `vegetation.classify_edges` as rescue (`:416-418`).
- **Memory.** Full-AOI flat arrays: dsm is 4·W·D float32. For 4.5 × 3.2 km that is about 230 MB, plus about 6 bytes × W·D per 1 m stat, so about 1 GB in total. That is fine. `np.*.at` is slow but simple.
- **Depends on.** `aoi` (`CACHE, U_*, V_*, utm_to_uv`), laspy+lazrs, pyproj. Output consumed by `layers.py:147-169`.
- **Madrid adaptation: medium.**
  1. Drop the reprojection. PNOA is already EPSG:25830, so only the rotation `utm_to_uv` is needed (remove `:25,29-31`).
  2. Read files from the PNOA cache folder instead of `CACHE/lidar/ept` (`:47`).
  3. Use the real ASPRS classes:
     - `ground = 2`;
     - `veg = 3/4/5`, with low/medium/high split stats if useful;
     - `building = 6`;
     - `water = 9`;
     - `bridge = 17`;
     - noise 7/18 dropped.
     Replace the `cls == 1` block (`:66-69`) with per-class counts and max/min heights (for example a `bldmax`, `vegmax`, `vegcnt`). Keep the return-number stats (`nl1`) for vegetation porosity.
  4. Add per-point **NDVI from the LiDAR's own NIR**. laspy exposes `red` and `nir` on PDRF 8. Accumulate a per-cell mean, which replaces NAIP NDVI (`layers.py:164-166`).
  5. Check LAS 1.4 flags: overlap / withheld bits, and `synthetic`.
  6. Make the dsm resolution a parameter. The hard-coded factor 2 (`:37-39,48,59-60`) should become `SUB = round(VOXEL_SIZE / DSM_RES)`. At ~5 pts/m² the 0.5 m grid will be ~50% empty. Fill it explicitly (dtla does nearest-neighbour fill in `layers.py:154-157`) or use 1 m only.
  7. **DTM.** dtla takes the DTM from USGS (`fetch_dem.py`), not from `gsum/gcnt`. Madrid must build the DTM from class-2 points: mean ground, then interpolate the holes under buildings. This is new code; nothing in dtla does it.
  8. **Warsaw compatibility.** Warsaw's fusion reads `data/prep.npz` with `dsm` at 0.5 m (2D × 2W, nearest), `dtm` at 1 m and `orto` at 0.2 m (D·5 × W·5 × 3) (`madrid:prep.py:1-3,77-81`, `madrid:voxelize.py:138-145,205`). An adapted `prep_lidar` can write exactly that `prep.npz` (dsm = 0.5 m max, dtm = filled ground) plus extra class layers. Warsaw's `voxelize.py` then runs unchanged for the Phase 2 test. Note that `voxelize.py:205` hard-codes the 5 × 5 ortho block (0.2 m), so PNOA ortho must be resampled to 0.2 m or that line parameterised.

### `fetch_*.py`: area-limited downloads

| Script | What it does | Reusable for Madrid | Adaptation |
| --- | --- | --- | --- |
| `fetch_lidar.py` | Walks the USGS EPT octree on S3 and downloads only nodes whose box intersects the AOI polygon + 40 m (`:123-153`). Caches in `CACHE/lidar/ept`; skips existing files; writes `.part` then renames (`:156-164`). Requests session with retries and backoff (`:106-120`). Thread pool of 24 (`:180`). | The pattern: AOI polygon from `corners_uv(MARGIN)` (`:125`), skip if cached, atomic `.part` rename, retry helper. | **High (rewrite as `fetch_pnoa_lidar.py`).** PNOA is 1 × 1 km tiles named by km coordinates in EPSG:25830. Compute the tile list from the AOI polygon's bounds, then download from the CNIG Centro de Descargas. If CNIG cannot be automated (forms or session), stop and print the exact tile list and target folder (CLAUDE.md rule 5). |
| `fetch_dem.py` | Reads USGS 1 m DEM COGs over HTTP through `WarpedVRT` straight onto the rotated grid (`:218-232`). **`grid_transform()` (`:210-215`) is the affine from rotated (col, row) to UTM.** `layers.py` also imports it for NAIP (`layers.py:25,69`). | `grid_transform()` is the generic "warp any raster onto the rotated grid" helper. Use it for the ortho and for the optional Ayuntamiento DSM 2023 test (Phase 2). | **Low for `grid_transform`** (move it into `aoi.py`, change the CRS to 25830). **Not needed as a DEM source**: CLAUDE.md requires a single elevation source (NPC02), so the DTM comes from class 2. |
| `fetch_naip.py` | Searches the Planetary Computer STAC (`:258-266`) and reads only the AOI windows of RGB+NIR COGs into a UTM mosaic at 0.6 m (`:269-286`). | The window-reading + `WarpedVRT` mosaic structure. | **High.** Replace with `fetch_ortho.py` for PNOA ortho from CNIG / Geoportal. There is no STAC; tile/sheet download, or WMS/WCS if allowed. NIR may come from the LiDAR instead (see `prep_lidar` point 4). |
| `fetch_osm.py` | Overpass `nwr(bbox); out body geom(full_bbox)` split into a 3 × 3 grid (`:311,340`), falling back to 2 × 2 sub-queries on failure (`:343-349`). Four mirror servers, retry rounds (`:306-328`). Per-part cache in `CACHE/osm_parts` (`:333-338`). Merged by (type, id) into `CACHE/osm.json` (`:354-359`). | Almost all of it. Output is the same Overpass JSON that Warsaw's `osm.py` parses (Warsaw makes it with `madrid:scripts/fetch_osm.sh` + `osm_pbf.py` from Geofabrik). | **Low.** Change the User-Agent (`:321`, "dtla-voxel/0.1") and possibly `SPLIT`. Keep `bbox_lonlat(150)`. For the full 4.5 × 3.2 km area, the Warsaw Geofabrik route (Madrid extract + `osm_pbf.py`) is a more robust alternative. Note `fetch_osm.py` has no cache-expiry logic. |

### `scripts/voxelize.py`: band fill, compared with Warsaw `madrid:scripts/voxelize.py`

**dtla structure (491 lines, functions + `main()`):**
- `layers.build()` returns a dict of **2D (D, W) layers** plus small lists, for example trunks, palms, bridge lines and lamp lines (`voxelize.py:224`, `layers.py:611-623`).
- Late 2D passes come next: landmark volumes, crosswalk paint, roof pilot (`:225-235`).
- "Sprites" are things that are not simple columns: trunks, palms, bridge piers, lamps. They go into one `(n, 4)` int64 array of `(row, col, z, palette)` (`:240-251`). Functions: `palm_voxels` (`:28-45`), `pier_voxels` (every 28 m along bridge ways, `:48-68`), `lamp_voxels` (`:71-96`).
- `H` is the maximum over all layers + 4, capped at 450 (`:253-256`).
- **Band loop** (`:274-309`). For each tile row `ty`, `fill_band(Lr, r0 = ty·128 − 1, r0 + 130, H, sprites)` (`:100-179`) allocates only an `(H, 130, W)` uint16 volume: 128 rows plus a 1-row apron on each side, which is exactly what the tile format's apron needs. It fills the band z-slice by z-slice from the 2D layers:
  - soil and ground colour;
  - building walls from `boti..topi`, roof equipment, roof colour;
  - `building=roof` canopies;
  - deck sides, top and barrier;
  - viaduct ribs;
  - crowns from `crown_bot..crown_top`;
  - sparse attachments (`:161-169`);
  - sprites inside the rows (`:171-176`);
  - landmark model stamping (`:177-178`).
- Per band, it then:
  1. collects thin voxels (`tiles.thin_voxels`, `:285-288`);
  2. downsamples the band core into **pre-allocated full-area coarse volumes for s = 2, 4, 8** (`:270,289-293`), using a crosswalk-aware `downsample_road_surface` (`:189-206`);
  3. writes the level-1 tiles `tiles/1/{tx}_{ty}.bin` and foliage `tiles/1f/...` for the whole row of tiles (`:298-307`, `write_tile` at `:182-186`, `tile_window` at `:209-219`);
  4. frees the band (`:309`).
- After the loop: coarse tiles with thin-voxel `detail` for s = 2 and 4 (`:316-340`), `terrain.bin` (`:343-354`), `meta.json` (`:359-374`), debug top-down image (`:377-378`). `refresh_labels()` rebuilds labels and views alone (`:479-486`).
- **Memory model.** Peak = 2D layers (dozens of D × W arrays, int32/float32/uint16) + one band (H × 130 × W × 2 B; with H = 300 and W = 4500 that is about 350 MB) + coarse volumes (1/8 + 1/64 + 1/512 of the full volume, about 14% of it) + thin-voxel lists. The docstring says "peak around 3-4 GB" vs Warsaw "~26 GB" (`:3-5`).

**Warsaw structure (2051 lines, one top-level script with no functions for the main flow):**
- Inputs: `data/prep.npz` (`dsm` 0.5 m, `dtm` 1 m, `orto` 0.2 m) (`madrid:voxelize.py:138-145`). OSM through `osm.OSM`. Many side modules: `landmarks`, `roofgardens`, `debris`, `traffic`, `underpass`, `labels`, `monuments`, `zones`, trees and phenology.
- It builds its 2D layers inline (ground colour, buildings, roofs, trees). Then it allocates **the whole volume at once, `vol = np.zeros((H, D, W), np.uint16)`** (`madrid:voxelize.py:1043`) and fills it by many passes that write arbitrary 3D voxels:
  - ground (`:1046-1061`), walls and roofs (`:1127-1181`);
  - tree crowns and trunks (`:1302-1396`), furniture (`:1454-1508`);
  - lamps from OSM nodes snapped to the kerb (`:1520-1537`) plus inferred lamps on Złota (`:1538-1560`);
  - underpass carving (`:1694-1718`), bridge decks (`:1740-1755`), pylons (`:1792-1841`), cars (`:1897-1907`).
- Then **whole-volume post-passes**: `debris.drop_debris` and `debris.support_floating` (`:1965,1982`); `ground.npz` (`:1972-1976`); `tiles.export(vol, g, ...)` (`:1986`); `traffic.build(vol=vol, ...)` (`:2040`); a deck-height scan over vol (`:2026-2031`); and the top-down debug image (`:2044-2051`).
- **Memory.** About 2·H·D·W bytes. Warsaw's 3950 × 4430 at H ≈ 260 is about 9 GB for `vol` alone, plus large temporaries. A Madrid 4.5 × 3.2 km area at H ≈ 220-260 would be about 6-7.5 GB plus temporaries. That is borderline but may fit on a 32 GB machine; measure it in Phase 5.

**Key differences:**

| | dtla | Warsaw |
| --- | --- | --- |
| Volume | one 130-row band at a time | full (H, D, W) in RAM |
| 3D logic | only from 2D layers + a sprite list; per-band stamping | arbitrary in-place 3D edits, plus post-passes needing the whole volume (floating-debris support via 3D connectivity, traffic, deck scans) |
| Tile writing | inline in `voxelize.py` (same byte format), levels 1/1f/2/4/8 | `tiles.export()`, levels 1/1f/8 |
| Inputs | `lidar.npz` + `dtm.npy` + `naip.tif` + `osm.json` via `layers.py` | `prep.npz` + `osm.json` + many JSON side files |

**Adaptation for Madrid: high, if done.**
- The band loop itself (`:274-341`) is generic and could be copied almost verbatim.
- The cost is restructuring Warsaw's fill into "2D layers + sprites + per-band functions". Every Warsaw pass that writes `vol[...]` has to become either a 2D layer or a sprite list.
- Whole-volume passes need band-local or halo-aware versions: `debris.support_floating`, `traffic.build(vol=...)`, the deck-near scan, the underpass carving, and the `FINALDUMP`/`pkin_box` debug dumps (`madrid:voxelize.py:1955,1983`).
- Recommendation: keep Warsaw's monolithic fill for the 500 m test area (Phases 2-4). Only switch to the band model in Phase 5, if the full area does not fit (as PLAN says). When writing new Madrid fusion code in Phase 3, prefer the dtla shape (2D layers dict + sprites) so that the later port is mechanical.

### `scripts/layers.py`: 2D fusion

Single function `build()` (`:146-623`) returning a dict of (D, W) layers.

- **Ground.** `dtm` from `dtm.npy`; `base = floor(min) − SLAB(3)`; `g = round(uniform_filter(dtm, 3) − base)` (`:147-151`).
- **Surface.** `dsm` 0.5 m with NaN filled by nearest (`:153-157`). `dsm_max` / `dsm_mean` over 2 × 2 blocks; `nd_b = wall_clean(dsm)` max − dtm (`:158-162`). `wall_clean` is Warsaw's own code (`:74-90`).
- **Spectral.** NAIP warped to the grid (`:67-71`); NDVI, luminance; `passthru = nl1/n1` (`:164-170`).
- **Bridge decks** (`:175-188`). Class-17 `bmax` > dtm + 3, cleaned with closing/opening, components ≥ 40 cells; `deck_top` = median-filtered bmax. **Directly reusable with PNOA class 17.** Adaptation is low; just retune thresholds.
- **Ground colours** (`:190-235`). OSM landuse / leisure / surface tables burned in area order, then NDVI reclassification "LA look: golden verges" (`:221-235`, LA thresholds). Adaptation medium: re-tune NDVI thresholds for PNOA NIR, and drop the "dry gold" logic or adapt it to Madrid summer grass.
- **Roads** (`:237-299`). Widths from `width` / `lanes` / defaults table `HW`; bridge ways set aside as `bridge_lines`; `lamp_lines` collected (`:268-269`); **centre lines = LA double yellow** (`:283-296`, `C["mark_y"]`). Spain uses white centre lines, so change the colour and the rule.
- **Rail** (`:301-308`). Generic; low adaptation.
- **LA River channel** (`:310-335`). LA-specific; **do not use**. Madrid's Manzanares (Madrid Río) is outside the planned AOI. Generic `water_pools` from OSM water is fine.
- **Buildings** (`:337-399`):
  - OSM footprints burned largest first;
  - per-building median and p90 of `nd_b` (`:350-366`);
  - flat-roof snap to the median and median filter (`:369-374`);
  - OSM `height` / `building:levels × 3.6` wins where the LiDAR sees much lower ("built after the flight", `:376-383`);
  - needle parts (`:384-394`);
  - `bmask` opening (`:396-398`).
  **Adaptation medium.** Footprints from Catastro (with number of floors) or OSM. With PNOA class 6 the building/non-building decision can use classification instead of NDVI votes. The 3.6 m per level is a hard-coded metre value that should go through config / `VOXEL_SIZE`.
- **Unmapped structures / vegetation vote** (`:401-442`). **This is the LA class inference**: `veg_vote = NDVI > 0.05 | passthru > 0.3`, then `struct = tall & ~near_bld & ~veg_vote`. Madrid should replace it with PNOA classes: 6 = unmapped building, 3-5 = vegetation. NDVI / passthru only as a tie-breaker.
- `trim_edge_slivers` (`:93-111`, used `:468`). Generic LiDAR-facade-return cleanup; reusable (low adaptation).
- **Wall styles** (`:114-142`) use the SoCal palette (STUCCO / CLASSIC "Historic Core"): **do not use**. Warsaw's own `wall_style` / `roof_style` (`madrid:voxelize.py:895,944`) plus a Madrid palette (Phase 4) is the base.
- **Roof colours** from imagery: per-building mean RGB of bright pixels, colour lift tuned for NAIP (`:470-500`). The idea is reusable; the constants are NAIP-specific. Warsaw already takes roof colours from the 0.2 m ortho.
- **Vegetation** (`:502-588`):
  - CHM from `nd_max`; local maxima as seeds; `watershed_ift` crown segmentation;
  - per-crown area / height / NDVI / luminance;
  - junk filters for facade noise, light poles and catenary masts (`:529-545`);
  - **palm detection** (`:518-528,549`) and OSM palm genera (`:580-588`): **do not use**;
  - dome-shaped crown top/bottom (`:553-568`);
  - leaf colour bins (`:569-575`); **jacaranda** (`:572-573`, LA, do not use);
  - trunks list (`:576-577`).
  This is the "tree detection from NDVI and multiple returns" piece (see below).
- **Late overrides** (`:590-606`): `landmark_overrides`, `facade_colors`, vegetation audit JSON written into `CACHE/vegetation-review`.
- Depends on `aoi`, `fetch_dem.grid_transform`, `osm`, `palette`, `vegetation`, `road_markings`, `landmark_overrides`, `facade_colors`. Inputs `lidar.npz`, `dtm.npy`, `naip.tif`, `osm.json`.
- **Overall adaptation: medium-high.** Use it as the **skeleton** for Madrid's Phase 3 fusion: the function layout, the returned layer names and the decks code. Replace its inference blocks with PNOA classes, and carry over Warsaw's richer rules: trees from the inventory, roof styles, underpasses.

### `scripts/road_markings.py`: crosswalks and junctions

- `junction_interiors(roads)` (`:93-128`). True at-grade intersections are found with an STRtree over road centrelines, a shared-vertex check and a tangent angle check. Local strips are intersected to give the junction polygons that centre lines must avoid (used in `layers.py:285,293`).
- `build_crosswalk_mask(lines, nodes, roads, road_mask)` (`:131-257`):
  - prefers explicit `footway=crossing` ways (`:224-237`), then `highway=crossing` nodes that carry a positive marking tag (`:238-256`);
  - finds the road under the crossing with tangent checks and refuses ambiguous cases (`:150-170`);
  - paints traffic-oriented bars 1.5 m wide at a 2.8 m pitch, or two border lines for `crossing:markings=lines` (`:172-222`);
  - rasterises them clipped to `road_mask`, keeping components ≥ 3 cells (`:42-47,213-216`).
- `finalize_crosswalk_paint(layers)` (`:57-72`) allocates the paint palette colours late, so the palette order stays stable. `voxelize.downsample_road_surface` (`voxelize.py:189-206`) softens paint at 2 m and drops it at 4/8 m. `terrain.bin` drops it as well (`voxelize.py:347-349`).
- Depends on shapely (STRtree), rasterio, scipy, `palette` (`M_MARK`, `pal`). Tests: `test_road_markings.py`, `test_road_marking_lod.py`.
- **Madrid adaptation: low-medium.**
  - Spanish crossings are continental "zebra" bars, which is the default branch. Check how Madrid's OSM tags `crossing:markings`.
  - Bar size and pitch (1.5 / 2.8 m) and the `3 <= width <= 35` limits are hard-coded metres. Route them through config / `VOXEL_SIZE`.
  - Warsaw's `M_MARK` material id must exist in the Madrid palette.
  - The LOD-aware downsample only matters if levels 2/4 are adopted (see `tiles.py`).

### Street lamps every ~36 m along kerbs

- **Lines** (`layers.py:268-269`): every non-tunnel, non-bridge road of class `ROADS` except `service`/`motorway`/`busway`, longer than 40 m, as `(centreline, half-width)`.
- **Placement** (`voxelize.py:71-96`, `lamp_voxels`):
  - for each line and **both sides**, positions at `arange(12, length − 6, 36.0)` (`:79`);
  - offset along the normal by `hw + 1.0` m, which is the kerb (`:80-85`);
  - skipped where blocked by buildings, decks or crowns (`:75,86`), and de-duplicated on a 12 m grid (`:86-88`);
  - 7-voxel pole (`:90-91`) and an emissive head at `z0 + 7` leaning one cell over the road (`:92-95`);
  - positions go to `meta.json` `lamps` (`:248,360`), which the viewer uses for lights.
- Warsaw instead uses **OSM `highway=street_lamp` nodes snapped to the kerb** with `distance_transform_edt` (`madrid:voxelize.py:1515-1537`), heights 10 m near roads and 6 m otherwise, plus a street-specific inference for Złota every 18 m on alternating kerbs (`:1538-1560`).
- **Madrid adaptation: low.** Count OSM `street_lamp` nodes in the AOI first (PLAN Phase 3). The best combination is OSM lamps first, then dtla-style inferred lamps where none lie within ~9 m (Warsaw's `lamp_xy` distance check, `:1543,1553`).
- The constants 12 / 36 / 6 / hw + 1 / 7 m / 12 m grid are all metres and should go through `VOXEL_SIZE`. The Złota block is Warsaw-specific; remove it.

### Tree detection from NDVI and multiple returns

- **`vegetation.py:12-79` `classify_edges`.** "Conservative object evidence for vegetation beside mapped buildings".
  - Candidate blobs (20-1500 cells, aspect ≤ 4, within 12 m of a building, top < 35 m) are accepted as crowns when all of these hold: rim porosity (`passthru > 0.3` on ≥ 25% of reliable rim cells), dome rise ≥ 0.35 m, plane-fit roughness ≥ 0.3 m, low wall contact, and (green ≥ 15% or core ≥ 3 m from the wall) (`:59-60`).
  - It also returns "attachments": elevated, thin, non-green surfaces near walls with measured top and bottom (`:72-76`).
  - Pure numpy/scipy, no I/O, with diagnostics. Tests in `test_vegetation.py` (unittest).
- **Crown segmentation** (`layers.py:502-577`): CHM -> peaks (5 × 5 max, > 3 m) -> watershed -> per-crown stats -> junk filters -> dome crowns + trunks.
- **Support tools:** `audit_vegetation.py`, `validate_vegetation.py`, `docs/vegetation-classification.html`, fixtures `scripts/fixtures/flower-vegetation.*`.
- **Madrid relevance.** With PNOA classes 3/4/5 the evidence problem is mostly solved by classification, so `classify_edges` is of limited use. The **crown segmentation + junk filters** are the useful part, for the optional "LiDAR crowns with no inventory tree" fill (PLAN Phase 3). Feed it `chm` from class 3-5 max height, NDVI from the point NIR, and `passthru` from the return-number stats.
- Adaptation: medium. Remove palms and jacaranda, and re-tune the NDVI thresholds; the LA values are low because the NAIP scene "reads low", `layers.py:224`. Warsaw's tree code (inventory + species + phenology) stays primary.

### `scripts/tiles.py`: diff against Warsaw, and the on-disk format

`diff madrid:scripts/tiles.py dtla:scripts/tiles.py` (168 vs 215 lines):
1. `LEVELS = (1, 8)` -> `(1, 2, 4, 8)` (`dtla tiles.py:29`).
2. The `downsample` solidity threshold at s = 2 is a third (`max(2, s³·3//8)`) instead of a quarter (`:36`).
3. New `thin_voxels()` (`:87-109`): banded 3 × 3 × 3 neighbour count, plus `keep_ids` for lamp heads. It finds one-voxel-thin structures (spires, poles, stays).
4. `export` / `export_region` take `keep_ids` and `skip_ids`, and for **levels 2 and 4 append a trailing `detail` section** of `uint16[4·n]` `(x, y, z, palette)` 1 m voxels relative to the node corner, where the coarse block is empty (`:10,129-132,154-157,204-211`).
5. Docstrings, `from scipy import ndimage` import.

**On-disk format.** Header, encoding and layout are identical: gzip (level 9, mtime 0) of
- `counts uint16[(N+2)²]`;
- `ground uint8[(N+2)²]`;
- `runs uint16[3·sum]` `(z0, len, palette)`;
- N = 128, 1-cell apron;
- paths `tiles/{s}/{tx}_{ty}.bin` and `tiles/1f/...`.

The only extension is the optional trailing `detail` block, and only at levels 2 and 4, which Warsaw does not produce. Level 1, 1f and 8 tiles are byte-format identical. dtla's `voxelize.py` writes tiles through its own `write_tile` / `tile_window` (`voxelize.py:182-219`) with the same layout, not through `tiles.export`.

**Viewer readers:**
- **Warsaw** (`madrid:web/src/mesher.worker.ts:31-40`): `DecompressionStream('gzip')`, `counts` at offset 0, `ground` at `2·n2`, `runs = buf.slice(3·n2, 3·n2 + 6·nr)`. Trailing bytes are **ignored**, so it would read dtla 2/4 tiles and silently drop `detail`.
- **dtla** (`web/src/tileData.ts:15-24`): same offsets. It validates `(byteLength − end) % 8 == 0` and exposes `detail`, meshed by `meshDetail` (`mesher.worker.ts:152-190,395-430`). Warsaw tiles have 0 trailing bytes, so they are valid.
- So the two readers are **mutually compatible at the byte level**.

Non-format differences:
- Warsaw's viewer assumes the levels are {1, 8}, with level 8 as "clay" (`madrid:web/src/city.ts:118,172,218`).
- `meta.json` differs: dtla `center` is lat/lon with `crs` EPSG:32611 (`voxelize.py:359`), Warsaw `center` is `[CX, CY]` projected (`madrid:voxelize.py:2005`).
- dtla deployment content-hashes tile files (`web/tools/version-data.mjs:19-24`, `web/src/util.ts:17` `dataUrl`). That is a delivery layer, not the tile byte format.
- **Conclusion:** keep Warsaw's `tiles.py` (CLAUDE.md rule 7). Adopting levels 2/4 + `detail` would be a plan-level decision, because it needs viewer changes in `city.ts`.

### Workflows and the profiling harness

- **`.github/workflows/pages.yml` exists at HEAD.** Added in `2888f5c` ("Deploy to GitHub Pages; README", 2026-11-02), last changed in `3e77ad7`. Steps: Node 22 with npm cache, `npm ci` in `web/`, `node tools/test-data-cache.mjs`, `npm run build`, `upload-pages-artifact@v3` (`web/dist`), `deploy-pages@v4` (`pages.yml:17-45`). Permissions `pages: write`, `id-token: write`; concurrency group `pages`.
  - Madrid adaptation is low. Drop the `test-data-cache.mjs` step unless the content-hash cache is copied too.
  - The Vite `base` must match the repository's Pages path.
  - The committed data in `web/public/data` must stay under GitHub's file and repository size limits.
- **`artifacts/profiling/` does not exist at HEAD.** It was added in `7d52d72` ("Profile rendering costs and record baseline measurements", 2026-11-02), grown in `615991b` and `1034c95`, and **removed in `e142849`** ("keep generated profiling artifacts out of version control"). `/artifacts/` is now in `.gitignore`. It only ever held generated JSON/PNG results (baseline, shadow, LOD, mobile).
- **`docs/rendering-profile.html` exists at HEAD.** Added in `7d52d72`, last changed in `9eeb73e`. It is a hand-written HTML report of shadow-map cost, postprocessing and tile/worker memory, with harness instructions.
- **Harness code is in `web/tools/`**: `profile.mjs` (added `7d52d72`), `profile-streaming.mjs`, `profile-gc.mjs`, `profile-horizon.mjs`, `bench-*.mjs`, `check-*.mjs` (shadows, LOD, mobile, idle), `test-*.mjs`. They use `playwright-core` and Chrome DevTools Protocol for worker heaps (`profile.mjs:8-30`).
  - `profile.mjs` looks for Chromium under **`AppData/Local/ms-playwright/.../chrome-win64/chrome.exe`** (`profile.mjs:11-14`), a Windows path. It falls back to `CHROME` env or `channel: 'chrome'`; Linux needs `CHROME` set or the path logic changed.
  - The tools depend on dtla's instrumented viewer: `web/src/performanceProfile.ts` (added `27d1b2a`, central LOD / streaming / shadow budgets) and `stats.ts`. Warsaw's viewer has different internals.
- **Warsaw already has its own tools**: `madrid:web/src/perf.ts`, `madrid:web/tools/bench.mjs`, `mem.mjs`, `memphone.mjs`, `weakgpu.mjs`, `jank.mjs`, `longtasks.mjs`, `scripts/perf_stats.py`.
- **Adaptation: medium-high.** Treat dtla's harness as a design reference: the methodology (fixed views, sample windows, CDP heap reads, JSON output) and the report layout. Extend Warsaw's existing tools rather than transplanting dtla's, which target a refactored viewer.

### Other dtla modules

| Module | What | Reuse for Madrid? |
| --- | --- | --- |
| `palette.py` (113 lines) | `Palette` class (quantised RGB + material id, append-only, `:33-46`), `parse_colour` with alias tables and saturation/lightness clamps (`:49-73`), `stable_hash`, `soften` toward "SoCal cream" (`:24-26`), material id contract matching the viewer (`:9-14`), colour dictionary `C` and lists (`:76-113`). | **Structure yes, colours no.** Moving Warsaw's palette out of `voxelize.py` into a `palette.py` module like this is a good Phase 4 step. Material ids must match Warsaw's `madrid:web/src/voxelMaterial.ts`, not dtla's (dtla appended `M_STUCCO`, LA landmark materials 23-29). The SoCal colours (STUCCO, JACARANDA, PALM_*, dry gold grass) are **not to be used**. |
| `roof_cleanup.py` (158 lines) | `clean_roof(surface, mask)`: finds flat roof decks as connected elevation modes (0.25 m bins), with plane and quadratic fits rejecting slopes > 1.2% and curved roofs. Only snaps within 0.35 m; returns diagnostics (`:1-60`). Pure numpy/scipy; tests in `test_roof_cleanup.py`. | **Yes, low adaptation**, as an optional Phase 2/3 tool against ~5 pts/m² roof noise on flat roofs. Pitched clay-tile roofs dominate central Madrid and are rejected by design (safe). The caller `roof_pilot.py` is a hard-coded roster of 10 LA buildings (`roof_pilot.py:1-25`): do not use it; write a generic per-building loop. |
| `landmark_overrides.py` (177 lines) | Identity-based overrides: OSM (type, id) + anchor + distance and area bounds -> wall/roof colour and material, optional geometry refiner (`:20-37,106`). Registry entries are LA (City Hall, etc.). | **Mechanism yes, entries no.** The "bind by OSM identity, never by name" pattern matches the Wikidata rule in CLAUDE.md. Medium adaptation: empty registry, Madrid entries in Phase 4. |
| `facade_colors.py` (139 lines) + `docs/facade-color-roster.json` | Verified facade colours from a reviewed JSON roster keyed by OSM identity (`:20-40,84`). | Mechanism optional (Phase 4). The roster is LA-only. |
| `landmark_volumes.py`, `disney_model.py`, `scripts/assets/disney-shell.*` | Authored 3D shell for Disney Concert Hall (trimesh). `disney-shell.json:121` contains a Windows path. | **Do not use.** |
| `obstruction_lights.py` | Aviation lights on tall roofs, from tiles and OSM. | Optional, low priority (Madrid's centre has few tall towers; Torre de Madrid / Edificio España). |
| `build_horizon.py` + `web/src/assets/horizon.*` | Distant mountain horizon profile from a DEM. | Optional (Sierra de Guadarrama would be a nice touch); it would need a DEM outside the "single source" rule, so log a decision first. |
| `landmarks.py`, `landmark_catalog.py`, `make_views` (`voxelize.py:448-476`) | LA landmark list and camera views. | **Do not use the content.** `make_views`'s bearing/elevation helper is generic. |
| `osm.py` | Overpass JSON -> shapely in grid coordinates, adapted from Warsaw. | Warsaw's own `madrid:scripts/osm.py` is richer (`nodes_with`, `lines_with`); keep Warsaw's. |
| Tests (`scripts/test_*.py`, unittest) | `test_road_markings`, `test_roof_cleanup`, `test_vegetation`, `test_building_slivers` are generic. The rest are LA-specific: landmark, Disney, roof pilot, facade roster. | Copy the generic ones together with their modules. |

**Do not use:**
- **LA class inference**: `layers.py:401-442`, NDVI / passthru votes as the primary classifier. PNOA is classified.
- **Palms**: `voxelize.py:28-45,244-246`, `layers.py:518-528,549,578-588`, `PALM_*` and the palm-trunk exception in `voxelize.py:285`.
- **Jacaranda**: `layers.py:572-573`.
- **SoCal palette** and stucco / Historic Core wall rules: `palette.py:1,24-26,76-113`; `layers.py:114-142,489-494`.
- **LA River channel**: `layers.py:310-335`. **Double-yellow centre lines**: `layers.py:283-296`.
- **LA landmarks, Disney model, roof pilot roster, facade roster**, `make_views` targets.
- **USGS / NAIP / EPT specifics**: S3 URLs, EPSG:3857/32611, `TILES` names.
- **Windows paths**: `aoi.py:379`, `build_data.sh:2`, `disney-shell.json:121`, `web/tools/profile.mjs:11-14`.
- **Cloudflare deployment scripts** (`web/cloudflare.config.ts`, `build:cf`, `deploy:cf` in `web/package.json`) unless needed.

**Licence note.** Copy `../dtla-voxel/LICENSE` as `LICENSE-dtla-voxel` before copying any code. Each copied file gets an origin comment with the dtla commit `90bc1a6`. `osm.py` and the `wall_clean` / `trim` lineage are already Warsaw-derived.

### Proposal: what to copy and when

| Phase | Piece | Action | Effort |
| --- | --- | --- | --- |
| **1. Data sources** | `aoi.py` | Merge dtla helpers (`CACHE` from `$MADRID_CACHE`, `WEB_DATA`, `corners_uv`, `bbox_lonlat`, lon/lat via EPSG:25830) into Warsaw's `aoi.py`, keeping Warsaw names. Parameters: centre (Sol), size 500 m, rotation 0°, `VOXEL_SIZE`. Move `fetch_dem.grid_transform` (`fetch_dem.py:210-215`) here. | Low |
| 1 | `fetch_osm.py` | Copy almost verbatim (User-Agent, maybe `SPLIT`); output is compatible with Warsaw's `osm.py`. | Low |
| 1 | `fetch_pnoa_lidar.py` | New. Reuse the `get()` retry, the cache-skip and the `.part` pattern from `fetch_lidar.py:106-121,156-164`. Tile list from AOI bounds in 25830. Fall back to manual instructions if CNIG cannot be automated. | High (new logic) |
| 1 | `fetch_ortho.py` | New. Reuse the `WarpedVRT` + `grid_transform` window reading from `fetch_naip.py` / `fetch_dem.py`. | Medium |
| 1 | `fetch_trees.py`, `fetch_catastro.py` | Nothing to take from dtla (Warsaw has `fetch_trees.py`). | n/a |
| **2. Elevation test** | `prep_lidar.py` | Copy and adapt: no reprojection, real PNOA classes (2/3-5/6/9/17), point NIR to NDVI, return stats kept, resolution as a parameter. Build the DTM from class 2 with hole filling. Write a Warsaw-compatible `prep.npz` (`dsm` 0.5 m, `dtm` 1 m, `orto` 0.2 m) plus class layers, so Warsaw's `voxelize.py` runs unchanged. This file is also the "elevation source adapter" boundary. | Medium |
| 2 (optional) | `roof_cleanup.py` | Copy if flat roofs come out noisy; skip `roof_pilot.py`. | Low |
| **3. Fusion** | `layers.py` | Use it as the skeleton for a Madrid `layers.py`: decks from class 17 (`:175-188`), `wall_clean`, `trim_edge_slivers`, the per-building LiDAR stats + "OSM/Catastro height wins after the flight" rule, and the returned-dict layout. Replace the class inference with PNOA classes; keep Warsaw's styles, trees and underpasses. | Medium-high |
| 3 | `road_markings.py` (+ tests) | Copy. White centre lines instead of `mark_y`; metres through `VOXEL_SIZE`; check Madrid crossing tags. | Low-medium |
| 3 | Lamps | Port `lamp_voxels` (`voxelize.py:71-96`) and `lamp_lines` (`layers.py:268-269`) as the fallback after OSM `street_lamp` nodes (Warsaw `voxelize.py:1515-1537`), with a minimum-distance dedupe. Remove the Złota block. | Low |
| 3 (optional) | `vegetation.py` + crown segmentation (`layers.py:502-577`) | Only if many LiDAR crowns lack inventory trees: CHM from classes 3-5, NDVI from point NIR, no palms or jacaranda. Log the decision in `DECISIONS.md`. | Medium |
| 3 | `pier_voxels` (`voxelize.py:48-68`) | Optional: bridge piers under class-17 decks (Madrid has few flyovers in the AOI). | Low |
| 4 | `palette.py` structure, `landmark_overrides.py` mechanism | Restructure Warsaw's palette into a module; identity-based landmark overrides fed from Wikidata/OSM IDs. Colours are new. | Medium |
| **5. Full area & performance** | Band fill (`voxelize.py:100-179,182-219,274-341`) | Only if the monolithic Warsaw fill does not fit in RAM: port the fill to 2D layers + sprites and copy the band loop. Whole-volume passes need band-aware rewrites (debris support, traffic, deck scan, underpasses). Keep `tiles.py` and the format unchanged (levels 1/1f/8; dtla's 2/4 + `detail` only by explicit plan decision). | High |
| 5 | Profiling | Use `web/tools/profile.mjs` and `docs/rendering-profile.html` as the methodology and report template. Extend Warsaw's own `perf.ts` / `bench.mjs` / `mem*.mjs`. Fix the Windows Chromium path (`profile.mjs:11-14`). Keep results out of git (`/artifacts/` in `.gitignore`, as dtla `e142849` did). | Medium-high |
| **6. Publication** | `.github/workflows/pages.yml` | Copy; drop the `test-data-cache.mjs` step; set Vite `base`; check data size limits; no attribution in workflow files. | Low |


## Madrid data sources (Phase 1)

AOI: 500 × 500 m centred on Puerta del Sol, the centre of the OSM square (relation 7424032, wikidata Q427163) at X 440 316.4, Y 4 474 264.1 (EPSG:25830). Rotation 0°, so grid +i is east and +j is south. World bounds X 440 066–440 566, Y 4 474 014–4 474 514. All downloads go to `$MADRID_CACHE/raw` (default `~/data/madrid-voxel-cache/raw`), which `aoi.RAW` points to.

| Source | Script | Output in the cache | Date | CRS | Height reference | Resolution / precision |
| --- | --- | --- | --- | --- | --- | --- |
| OpenStreetMap (Overpass) | `fetch_osm.py` | `osm.json` (7.3 MB, 25 566 elements) | data as of 2026-11-10T22:05Z | WGS84 lon/lat | none | vector |
| Municipal tree inventory (datos.madrid.es 300761-0-arbolado-especies) | `fetch_trees.py` | `trees/trees.json` (541 trees in AOI + 20 m) | 2026-07 edition, published 2026-07-09 | ETRS89 / UTM 30N (EPSG:25830) | tree `height_m` above ground | point per tree; coordinates to the mm |
| Catastro INSPIRE Buildings WFS | `fetch_catastro.py` | `catastro/buildings.geojson` (596), `building_parts.geojson` (4 106) | live service, read 2026-11-10 | EPSG:25830 | no heights: floors above/below ground only | stated horizontal accuracy 0.1 m |
| PNOA orthophoto, most recent (IGN WMS `pnoa-ma`) | `fetch_ortho.py` | `ortho/ortho.tif` (2401 × 2401 px), `ortho.json` | flight 2023-07 over the whole AOI | EPSG:25830 (requested axis-aligned) | n/a | 0.25 m native |
| PNOA-LiDAR 3rd coverage NPC02 (CNIG) | `fetch_pnoa_lidar.py` (check), `lidar_report.py` | `pnoa_lidar/*.LAZ` (16 tiles of 1 km, 1.2 GB) | flown 2024-03-17/18; files created 2026-02-22 | EPSG:25830 (horizontal only in the header) | orthometric (ellipsoidal to orthometric conversion per IGN; geoid model not stated) | 5.9 pts/m² own points, 10.0 with overlap; Z scale 1 mm |

Notes per source:

- **OSM:** in the AOI there are 1 088 elements tagged `building`, 2 294 `highway`, 139 crossings, 262 `highway=street_lamp` nodes (so Phase 3 probably does not need lamps placed along kerbs) and 231 elements with a `wikidata` tag.
- **Trees:** the dataset is published only for the whole city (CSV, 75 MB, 799 110 trees), so it is downloaded once and filtered locally; this is the one exception to area-limited downloads. Palms, municipal nurseries and forest masses are not in it. The 2026 CSV has 12 of the 15 columns in the spec (`estructura_datosarbolado.pdf`, July 2025): `EDAD_RELATIVA`, `SINGULARIDAD`, `VITALIDAD` and `ESTADO_GENERAL` are missing. The most common species in the AOI are *Ligustrum japonicum* (229), *Cercis siliquastrum* (67), *Pyrus calleryana* 'Chanticleer' (52), *Platanus × hispanica* (35) and *Aesculus hippocastanum* (33). Median height 4.5 m, maximum 17 m.
- **Catastro:** the WFS answers bounding-box queries, so it is read in 500 m tiles. `Building` carries year built, current use, condition and dwelling/unit counts; its own `numberOfFloorsAboveGround` is empty in Madrid, so floors come from `BuildingPart` (linked by `building_id`, all parts matched). Uses in the AOI: 403 residential, 120 retail, 47 office, 25 public services, 1 industrial. Median year built 1900. Data error: building `0443102VK4704C` has year 979.
- **Orthophoto:** the July 2023 flight is a year older than the LiDAR (spring 2024). It is not a true orthophoto, so the roofs of tall buildings lean a little away from their Catastro footprints (`docs/img/phase1-sources-overlay-sol.jpg`). The WMS is the IGN's official viewing service; the CNIG download centre has the same orthophotos as files, behind the same reCAPTCHA as the LiDAR. A newer or true orthophoto from the Ayuntamiento Geoportal is an alternative to evaluate.
- **Alignment:** Catastro footprints and municipal trees drawn over the orthophoto fit roof edges and street tree rows (`docs/img/phase1-sources-overlay.jpg`), so all three EPSG:25830 sources agree without any shift.
- **PNOA-LiDAR download:** the CNIG download centre protects downloads with reCAPTCHA v3 (`preAutorizarDescarga`), and its file search refuses scripted requests (HTTP 403). Under `CLAUDE.md` rule 5 the files are downloaded by hand; `fetch_pnoa_lidar.py` lists the 1 km tiles the AOI needs, checks the files by their headers and prints the instructions with the expected file names. See the PNOA-LiDAR section below.

### Tree inventory columns (Spanish -> English)

Defined once, in `COLUMNS` in `scripts/fetch_trees.py`.

| Spanish column | English key | Meaning |
| --- | --- | --- |
| `ASSETNUM` | `id` | unique tree id |
| `NUM_PARQUE` | `park_id` | historic, singular or forest park id (empty elsewhere) |
| `NUM_DISTRITO` / `NBRE_DISTRITO` | `district_id` / `district` | administrative district |
| `NUM_BARRIO` / `NBRE_BARRIO` | `neighbourhood_id` / `neighbourhood` | neighbourhood (barrio) |
| `X`, `Y` | `x`, `y` | EPSG:25830 metres |
| `CODIGO_ESPECIE` | `species_code` | species code |
| `ESPECIE` | `species` | scientific name, upper case |
| `PERIMETRO` | `trunk_cm` | trunk circumference at 1.3 m, cm |
| `ALTURA_TOTAL` | `height_m` | total height, m (decimal comma in the CSV) |
| `EDAD_RELATIVA` | `age_class` | relative age (not in the 2026 CSV) |
| `SINGULARIDAD` | `singular` | `CAT_CM` / `CAT_PGOUM` (not in the 2026 CSV) |
| `VITALIDAD` | `vitality` | Alta / Media / Baja (not in the 2026 CSV) |
| `ESTADO_GENERAL` | `condition` | Sano … Muerto (not in the 2026 CSV) |

### PNOA-LiDAR NPC02 over the AOI

Figures from `scripts/lidar_report.py` (re-run it for NPC03 or the municipal 2026 flight).

- **Files:** 16 tiles downloaded by hand (X 439–443 km, Y 4473–4476 km; tile 443-4474 is not among them, which matters only for the full area). The AOI needs `PNOA_2024_MAD_440-4474_H30_NPC02.LAZ` and `PNOA_2024_MAD_440-4475_H30_NPC02.LAZ`. **File names give the north-west corner in km:** `440-4474` covers X 440 000–441 000, Y 4 473 000–4 474 000. Each tile holds 6.9–11.3 M points (58–97 MB).
- **Format:** LAS 1.4, point format 8 (XYZ, intensity, returns, classification, GPS time, RGB and NIR, all 16-bit), scale 1 mm, written by TerraScan. GPS time is adjusted standard GPS time.
- **CRS and heights:** the header declares only EPSG:25830, with no vertical CRS. Heights are orthometric: the IGN processing converts ellipsoidal to orthometric heights, and the ground at Sol is at 643–667 m (median 652 m), as expected for the square (ellipsoidal heights would be about 50 m higher). The geoid model is not stated on the IGN page.
- **Capture date:** 17 and 18 March 2024 (43 % and 57 % of the points). Deciduous trees, the plane trees included, were still bare.
- **Density over the AOI (0.25 km²):** 2.51 M points, 10.0 pts/m² in total, but 41.75 % are class 12 (overlap). Without overlap: **5.9 pts/m²**, 5.1 first returns/m², as the specification says (≥ 5). Cells of 1 m with no points: 3.7 % with all points, 5.7 % without overlap (median 7 and 5 points per cell). Most empty cells are light wells, narrow courtyards and the gaps between buildings. No points carry the withheld or overlap flags: overlap is only marked through class 12.
- **Class 12 (overlap) hides the semantic class.** Overlap points (median 18.5 m above the ground, so largely on roofs) lose their ground, building or vegetation class. For heights they are good points; for classification, take the class from the non-overlap points of the same cell or its neighbours. Over all 16 tiles overlap is 21.8 % of the points.
- **Classes in the AOI** (share of all points): 1 unclassified 0.09 %, 2 ground 12.27 %, 3/4/5 vegetation 0.29/0.31/1.02 %, 6 building 43.87 %, 7 noise 0.01 %, 12 overlap 41.75 %, 14 power line (6 points), 64 vehicle 0.37 %, 65 wall 0.02 %, 70 antenna (51 points). Over all 16 tiles there are also 9 water, 15 power tower, 17 bridge (0.17 %, present in every tile), 67 solar panel and 68 wind turbine.
- **PNOA class codes beyond ASPRS** (pnoa.ign.es, "Procesamiento de los datos"): 64 vehicle, 65 wall, 67 solar panel, 68 wind turbine, 69 dam, 70 antenna, and from NPC03: 71 flat roof, 72 pitched roof, 73 green flat roof, 74 facade, 75 interior courtyard. Class 65 (an NPC03 class) already appears in these NPC02 files. Bridges are class 17.
- **Classification quality at Sol** (`docs/img/phase1-lidar-classes.png`, highest non-overlap point per 1 m cell): buildings and streets are clean. Parked cars are class 64 along the kerbs, so they do not pollute ground or buildings. Unclassified points (class 1, 0.6–3.7 m above the ground) gather in the square: kiosks, the Cercanías entrance and street furniture. The antenna (class 70) is one object about 12 m above the ground. No awnings or vehicles were found classified as building or ground at this scale.
- **Colour and NIR:** every point has RGB and NIR (16-bit values 256–65 280, none zero).
- **NDVI test, Paseo del Prado** (X 441 200–441 330, Y 4 474 050–4 474 350; `docs/img/phase1-lidar-ndvi-prado.png`): NDVI = (NIR − R) / (NIR + R) from the points' own values. Lawns around the Fuente de Neptuno are clearly positive (ground p90 +0.35). Trees are weak: high vegetation median +0.16 (p90 +0.40), because the deciduous trees were leafless in March. Buildings −0.01. NIR is usable for grass and evergreens, but not on its own to detect deciduous crowns from this flight; the leaf-off flight also means sparse crowns for plane trees.

## Elevation pipeline (Phase 2)

```
fetch_pnoa_lidar.py (check)  ->  prep_lidar.py  ->  $MADRID_CACHE/work/elevation_<source>.npz  (common format)
                                                       |-> prep.py              -> data/prep.npz  (Warsaw voxelize.py contract)
fetch_ortho.py --------------------------------------->|
                                                       '-> voxelize_elevation.py -> web/public/data  (Phase 2 test)
```

Commands, from the repository root:

```
PYTHONPATH=scripts uv run python scripts/prep_lidar.py          # ~3 s for the test AOI (one LAZ tile)
PYTHONPATH=scripts uv run python scripts/prep.py
PYTHONPATH=scripts uv run python scripts/voxelize_elevation.py
uv run python scripts/screenshot.py phase2-top --view top --date 5-15 --hour 12
```

### Common elevation format (`elevation_<source>.npz`)

The boundary between a point-cloud source and the rest of the pipeline. Every array is on the rotated `aoi.py` grid at the resolution set in `pipeline.toml` (`[elevation] resolution`, 1.0 m for NPC02), row 0 = grid row 0; each point is assigned to the cell it falls in, so there is no north-up raster and no second resampling. Changing the rotation only means re-running `prep_lidar.py`.

| Array | Type | Content |
| --- | --- | --- |
| `dsm` | float32 | highest point that is not noise or a vehicle (overlap points included); NaN where empty |
| `dtm` | float32 | mean of ground points; gaps filled by a multi-scale (push-pull) fill and smoothed (σ 3 m) only where filled; never NaN |
| `ground_n` | uint16 | ground points per cell (0 where the DTM is filled) |
| `cls` | uint8 | canonical class of the highest non-overlap point; cells with only overlap points take the class of the nearest cell with its own points; 0 where empty |
| `cls_filled` | bool | cells whose class came from a neighbour |
| `top_building`, `top_vegetation`, `top_bridge` | float32 | highest point of each class group; NaN where none |
| `n_all`, `n_overlap`, `n_vegetation_nonlast`, `n_vehicle` | uint16 | point counts |
| `info` | JSON | source, description, resolution, CRS, vertical reference, flight dates, files, point count and the AOI parameters |

Canonical classes are the ASPRS codes plus PNOA's own from 64 (vehicle 64, wall 65, solar panel 67, antenna 70, NPC03 roof/facade/courtyard classes 71–75). **Adding a source** (the municipal 2026 flight, NPC03): write its `fetch_` script and add an entry to `SOURCES` in `prep_lidar.py` with its folder, file pattern, CRS, vertical reference, a class equivalence table onto the canonical codes, its noise and overlap codes and its GPS time type; then set `source` (and, for a denser flight, `resolution`) in `pipeline.toml`. `prep.py` checks that the stored AOI parameters match `aoi.py`, so stale rasters are refused.

### What Warsaw's fusion expects, and how Madrid feeds it

`prep.py` writes `data/prep.npz` exactly as Warsaw's `voxelize.py` reads it (see "Raster contract" above): `dsm` float32 (2D, 2W) at 0.5 m, `dtm` float32 (D, W) at 1 m with no gaps, `orto` uint8 (5D, 5W, 3) at 0.2 m, row 0 = grid row 0, values at cell centres, absolute orthometric heights. From the 1 m rasters the DSM is each cell repeated 2 × 2 (nearest neighbour, so no detail is invented and the ×2 that `voxelize.py` hard-codes is kept); the DTM is taken 1:1; the orthophoto (north-up, 0.25 m) is sampled bilinearly at the centres of the rotated 0.2 m cells. NaN marks empty DSM cells (`voxelize.py` handles NaN with `isfinite` in the places that check). Nothing in Warsaw's `voxelize.py` had to change for this; it is not run yet because it needs the Phase 3 inputs (OSM fusion, trees, landmarks).

The pipeline map shows nothing in Warsaw's code that needs a 0.5 m raster from the source: the 0.5 m DSM only feeds 2 × 2 maxima/means per 1 m cell and `wall_clean`. With NPC02 the intermediate resolution therefore stays at 1 m.

### Phase 2 test voxels (`voxelize_elevation.py`)

Ground and surface only, generic palette: each column is soil and paving up to the DTM, then by class: buildings, antennas and walls solid to the surface with a roof-coloured top voxel; unclassified structures (kiosks, the Cercanías entrance) solid grey; vegetation as a crown hanging below the surface (60 % of the height); bridges as a 1.5 m deck. A column holds something above the ground only if the surface is ≥ 1.5 m above it. Vehicles (class 64) are left out of the DSM, so parked cars do not become blocks. Empty DSM cells take the median of their valid 3 × 3 neighbours (twice), then the ground. The output is the minimum the viewer needs: tiles through the unchanged `tiles.py`, `meta.json` (with `voxel`), `terrain.bin` in `terrain.py`'s format, and `zones.bin/json` with one block per 128 m tile and no buildings, so nothing waits to be shown whole. `places.json` and `traffic.json` are absent; the viewer logs two JSON errors and carries on.

Test AOI result: 4 × 4 level-1 nodes, 328 KB in `web/public/data`, height 72 levels over base 640 m. Columns: building 70.4 %, vegetation 2.6 %, unclassified structures 0.2 %, no bridges.

### Quality of the NPC02 elevation (test AOI)

Screenshots: `docs/img/phase2-top.png`, `phase2-sol.png`, `phase2-street.png` (15 May, noon).

- **Roof holes:** of the 157 356 cells inside Catastro footprints (62.9 % of the AOI), **1.22 % have no point** and 0.69 % have only overlap points. Empty cells are filled with the 3 × 3 median; overlap-only cells take their neighbours' class. 98.5 % of footprint cells end up as building. Roofs read as continuous surfaces; holes are not a visible problem.
- **Courtyards and light wells:** they come out open and at the right depth (dark pits in the top view). 2.95 % of footprint cells are below half their building's median height; 91 % of those are inside the footprint rather than on its edge, i.e. real courtyards and light wells, which Catastro footprints include.
- **Roof edges and cornices:** 7.1 % of the AOI is building-class surface higher than 6 m *outside* the Catastro footprints, mostly a 1 m strip along the facades where eaves and cornices overhang the street. Those mixed cells make the walls ragged, with vertical notches that show as dark stripes in the oblique and street views. Phase 3 should cut walls to the footprints (Warsaw's `wall_clean` and footprint rules) and keep the overhang as eaves only above a clearance.
- **Stepped roofs:** pitched roofs become 1 m terraces; with the roof colour only on each column's top voxel, the risers show as wall colour with red speckles. Expected at 1 m; the full palette and orthophoto colours come in Phases 3–4.
- **Trees:** leaf-off (flown 17–18 March), so plane-tree crowns are sparse and come out as thin green pillars and scattered blocks. Phase 3 uses the inventory (species, height) for crowns rather than the LiDAR shape.
- **Street furniture:** kiosks, the Cercanías entrance, the statue and signs come out as unclassified grey blocks in the square; scattered 1-voxel specks remain where class 1 points stand over 1.5 m.
- **Artefacts:** no spikes or pits from noise; the DTM fill under buildings is smooth. Small ground bumps remain where ground points sit on raised features.

**Conclusion:** NPC02 alone gives roofs without significant holes at 1 m. The optional Ayuntamiento DSM 2023 test is not needed on these numbers; the remaining defects (ragged facades, terraced pitched roofs, sparse trees) are matters for the Phase 3 fusion, not for the elevation source.

### Viewer notes learnt in Phase 2

- At street level a view's target must sit just below the camera: OrbitControls' tilt limit (`TILT` in `nav.ts`) lifts a camera that looks up.
- Deleting and recreating `web/public/data/tiles` while the Vite dev server runs makes it serve `index.html` for the new files; the voxeliser therefore overwrites node files in place and only removes stale ones.

## Fusion (Phase 3)

`sh scripts/build_data.sh` runs the whole Madrid pipeline from the cache in about 25 s for the test area.

### Structure

- `palette.py`: material ids (must match `web/src/voxelMaterial.ts`), the shared `Palette`, the ground palette `C`, colour helpers.
- `buildlog.py`: `note()`, the report and the output folders.
- `layers.py`: the 2D fusion, `build()` returning the layers by name (dtla-voxel's structure, Warsaw's rules): ground level and classes, roads, the LiDAR rasters and classes, ortho indices, building features with styles, roof heights and undersides, bridge ways. The docstring lists every layer.
- `voxelize.py`: the 3D fill from those layers, plus what is decided voxel by voxel: vegetation and trunks, fountains, street furniture, bridge decks, underpasses, landmarks, debris; then the export.
- The split was checked to be byte-identical: every tile and viewer file hashed before and after (`data/debug/rebuild.sh`).
- **Not moved yet:** the vegetation masks and the bridge deck heights are computed in `voxelize.py`, between 3D writes (trunks, deck surfaces). Moving them into `layers.py` means separating those reads and writes; worth doing with the band fill in Phase 5.

### Sources and rules

- **Ground:** the PNOA DTM through Warsaw's `ground_walls` (retaining walls snapped to one level, slopes smoothed); ground classes from OSM (roads, pavements, squares, parks, water, rail) as in Warsaw. Roads take their surface from OSM `surface` or the square they cross.
- **Buildings: OSM footprints + Catastro floors.** OSM and Catastro footprints coincide at IoU 0.957 in the test area (Spain's OSM buildings largely come from Catastro). OSM is kept as the footprint because it carries names (82), Wikidata (58), colours (57) and the building/part structure the Warsaw rules rely on; it has levels on only 213 of 1 025 buildings. Catastro (`catastro.py`) gives the floors of the parts under an OSM feature without height (336 features here, 3.2 m per floor) and adds the Catastro buildings OSM lacks (overlap < 30 %, 2 here). Heights come from the LiDAR; Warsaw's rule stays: the OSM/Catastro height wins only where the LiDAR sees nothing tall (p90 < 35 % of it, a building finished after the flight) or misses a spire. No feature triggered it in the test area.
- **Vegetation:** above-ground cells (nDSM > 2.2 m) green in the leaf-on orthophoto **or classed vegetation by the PNOA** (2 637 cells only the LiDAR finds: the flight was leaf-off), never where the PNOA classes building (eaves and cornices), under `MAX_TREE` = 40 m.
- **Trees:** the municipal inventory is the backbone (423 trees in the AOI), with 21 OSM trees where no inventory tree stands within 2 m. 248 known trees get a trunk under their LiDAR crown; 179 have no crown in the leaf-off LiDAR and are drawn young at their inventory height. Only 22 LiDAR crowns have no known tree under them (private courtyards), so NDVI and multiple-return detection (optional task) is not needed here.
- **Bridges and flyovers:** Warsaw builds decks from OSM bridge ways with heights from the DSM along each way; PNOA class 17 cells next to a bridge way are added to the deck. The test area has no bridge, so this is untested; the 16 downloaded tiles all contain class 17, so it is checked when the AOI grows (Phase 5).
- **Crossings and markings:** `road_markings.py` (dtla-voxel) paints crossing bars across the carriageway following traffic, from OSM crossing ways or else marked crossing nodes; here 2 ways, 2 nodes, 5 ambiguous left unpainted. Cycle crossings red, lane markings from Warsaw (none here: no 2-lane avenue in the AOI).
- **Street lamps:** OSM has 80 in the AOI and 74 are drawn (the rest fall on buildings), so dtla-voxel's lamps every 36 m along kerbs are not needed. The inferred bridge-deck lamps (Warsaw) stay for decks without OSM lamps.
- **Colours:** roofs from the orthophoto median over each roof (Warsaw's `roof_style`); walls from OSM colours or a default palette; leaves from the palette, tinted by the viewer's season.
- **Climate and sun:** `climate.py` queries Open-Meteo at the AOI centre (40.42, −3.70; Europe/Madrid); the viewer's sun takes the centre's lon/lat from `meta.json` (`lonlat`). Madrid and Warsaw share CET/CEST, so the viewer's UTC offset is unchanged.

### Warsaw code still present

Phase 4 items:
- `labels.py` (Polish names, `FAR_TIERS`, `PICKS`, `NAMES`), `wikidata.py`, `notable.py`: replaced by `fetch_wikidata.py` from OSM wikidata tags; until then `notable.json` is absent and only greens get labels.
- `phenology.py` (DWD and iNaturalist for Central Europe) and `web/public/data/phenology.json` (Warsaw's, restored as a placeholder): the seasonal cycle for Madrid's species.
- `HISTORIC_CORE` (empty) and the wall palettes: the Madrid palette and Madrid de los Austrias.

Not used by the Madrid build:
- `flood.py` and `web/src/flood.ts` (the Vistula gauge): no river in the area; the viewer's flood loader fails quietly.
- `window_counts.json` and `window_photos.py`: lit-window statistics counted on Warsaw photos, kept as generic behaviour by building type.

Viewer (cleaned after Checkpoint 3):
- the floodlight is generic (`floodlight()` in `sky.ts`, material `FLOODLIT` = 7);
- `flood.ts` and the river gauge slider are gone, as is the zouk dance floor;
- train liveries are Renfe's, Iryo's and Ouigo's; the tram keeps a default livery, idle with no tram paths.

Still left in the viewer:
- the `web/tools/*` camera poses in Warsaw coordinates;
- `posthog-js` in `package.json` (`stats.ts` imports it lazily; it never runs without the removed bootstrap);
- comments explaining tuning with Warsaw examples.

Documents: `README.md`, `IDEAS.md`, `visual_ref.md` and `research_*.md` are Warsaw's (README rewrite in Phase 6).

### Known defects in the test area

- Roof colours split between clay tile and a cold grey: the ortho median over flat or mixed roofs picks up grey; Phase 4's palette should pull Madrid roofs toward tile, zinc and slate.
- Street lamps are Warsaw's 1 × 1 columns 10 m high with a lit top: heavy at street level in Sol.
- Tree crowns of young (procedural) trees are boxy; only 4 conifers in the inventory get conifer crowns.
- No labels yet (Phase 4); the search lists 666 OSM places.
- No bridges to test the class 17 decks.

## Madrid identity (Phase 4)

### Areas and caches

`pipeline.toml` defines the build areas (`[areas.<name>]`: centre, size, rotation); `[aoi] area` picks one, `MADRID_AREA=<name>` overrides it. Everything cut to an area lives in `$MADRID_CACHE/areas/<cx>_<cy>_<w>x<h>_r<deg>/`:

- downloads: `osm.json` and `osm_parts/`, `catastro/`, `ortho/`, `trees.json`, `wikidata.json`;
- rasters: `elevation_<source>.npz`, `prep.npz`, `ground.npz`.

What does not depend on the area stays in `raw/`: the LiDAR tiles, the whole tree inventory, climate, phenology and the Wikidata entity cache. `web/public/data` holds whatever area was built last.

The full area (`full`): X 439 000–442 750, Y 4 472 950–4 475 700 (3.75 × 2.75 km), from the Templo de Debod to the east edge of the Retiro and from Glorieta de Bilbao to Atocha. Confirmed by the user. It needs 12 LiDAR tiles (`fetch_pnoa_lidar.py` no longer adds a margin `prep_lidar.py` never reads).

Full-area inputs:
- OSM: 259 018 elements, 60 MB.
- Inventory trees: 43 913.
- Catastro: 10 349 buildings.
- Orthophoto: 15 400 × 11 400 px, July 2023.
- LiDAR: 92.5 M points, rasterised in 72 s with 1.6 GB peak memory. Empty surface cells 2.5 %; observed ground 48 % (parks).

**Catastro WFS failures:** dense tiles sometimes come back with the start of the GML replaced by an "Object moved" error page. Such a tile is split in four down to 60 m; a tile that still fails is skipped and listed under `skipped` in the GeoJSON (one 31 m square of building parts near Calle de Toledo in the full area). The LiDAR heights stand there; only Catastro's floor counts are missing.

### Palette (`palette.py`)

- **Roofs:** Arab clay tile (`ROOF_TILE`), slate, zinc and flat terrace.
  - The material comes from the OSM `roof:material`; otherwise, where OSM gives no colour, from the ortho median over the roof: red-orange → tile, dark → slate, grey → terrace; zinc only on `roof:shape=mansard` or gambrel.
  - Around Sol, 407 Catastro roofs have a median ortho colour of (174, 146, 128). About 40 % read grey: flat azoteas, which an earlier rule wrongly drew as zinc.
- **Walls:** without an OSM colour, light render (8 shades) or exposed brick (3 shades), about one in four brick; granite for places of worship. `building:material=brick/stone` picks brick or granite.
- **Madrid de los Austrias** (`landmarks.HISTORIC_CORE`, traced roughly): almagre red, ochre, cream and brick walls, tiled roofs, the historic-core roof fitting from Warsaw's rules.

### Landmarks and labels

- `fetch_wikidata.py` links landmarks to Wikidata only through the `wikidata` tag of OSM elements. Over the full area, 1 292 tagged elements map to 1 118 items, fetched in batches of 50 with `wbgetentities`; entities are cached by id in `raw/wikidata/entities.json`.
- **Required set:** all ten are tagged in OSM, so `OVERRIDES` is empty.

  | Landmark | Wikidata | OSM element |
  | --- | --- | --- |
  | Royal Palace | Q171517 | relation 30399 |
  | Almudena Cathedral | Q849711 | relation 75658 |
  | Plaza Mayor | Q1123493 | relation 16657232 |
  | Puerta del Sol | Q427163 | relation 7424032 |
  | Metrópolis | Q465250 | relation 4655046 |
  | Cibeles Fountain | Q2736564 | relation 6345116 |
  | Puerta de Alcalá | Q1140634 | way 174805987 |
  | Prado Museum | Q160112 | relation 7726080 |
  | El Retiro Park | Q1131807 | relation 13616929 |
  | Palacio de Cristal | Q2420025 | way 23596451 |

  "Cibeles" is the fountain; the Palacio de Cibeles (Q1849031) is a separate item. `ENGLISH_NAMES` corrects Wikidata English labels that are not the name used in English ("Main Square" → "Plaza Mayor").
- **Labels** (`labels.py`): Spanish name (the OSM `name`; Wikidata's Spanish label when OSM has none), English name under it where it differs (`en`, the second line of the pin and the card); kind from the OSM tags, or the Wikidata type when the building tag is generic.
  - Required landmarks show from anywhere (`far` 9000).
  - The extended set takes places (not boundaries, routes, streets, shops or chains) whose item has a heritage designation or a Wikipedia article. Distance by Wikipedia editions: ≥ 15 → 2500 m, ≥ 4 or heritage → 1300 m, else 600 m. `EXTENDED_EXCLUDE` drops items by id.
- **Info cards** (`web/src/card.ts`): on selecting a label, its names and kind plus the facts present (built, architect, height, style, heritage designation) and links to the website and Wikipedia. All static, from `meta.json`; the viewer makes no request to Wikidata.

### Seasonal cycle (`phenology.py`)

- **Classes:** the 13 commonest deciduous genera in the city inventory, by share of trees:

  | Genus | Share | Genus | Share |
  | --- | --- | --- | --- |
  | Platanus | 13.1 % | Prunus | 4.0 % |
  | Ulmus | 7.9 % | Robinia + Gleditsia | 5.5 % |
  | Celtis | 6.4 % | Populus | 2.7 % |
  | Acer | 6.2 % | Melia | 2.9 % |
  | Styphnolobium | 6.0 % | Fraxinus | 2.6 % |
  | Aesculus | 2.7 % | Pyrus | 1.9 % |
  | Tilia | 1.4 % | | |

  Plus "other deciduous" and "evergreen". Evergreens include the broadleaves Madrid plants a lot: Ligustrum (3.6 %), Quercus ilex, Olea, Magnolia. Within the full area the commonest are Styphnolobium 16.7 %, Aesculus 14.6 %, Platanus 12.3 % and Ligustrum 9.9 %.
- **Dates:** iNaturalist leaf annotations in Spain, Portugal and Italy (place ids 6774, 7122, 6973). Spain alone had too few. Leaf fall is colouring + 17 days, and the per-tree spread comes from Warsaw's DWD series.
  - Genera with too few annotations take the median of the classes: Platanus, Styphnolobium, Aesculus, Celtis, Melia and Tilia for leaf-out and colouring.
  - City medians: leaf-out 8 April, colouring 31 October, leaf fall 17 November.
  - Prunus colouring on 13 December is suspicious (cherry laurel, an evergreen, is in the genus).
- **Autumn colours:** from Warsaw's Commons photo measurements where the genus matches (Acer, Tilia, Fraxinus, Robinia, Populus, Aesculus); the rest take their median. Lawns still use Warsaw's monthly lawn colours.

### Grid rotation (`rotation_report.py`)

Share of Catastro facade length within 3° of the grid axes, i.e. drawn as straight voxel walls:

| Area | 0° | −6° (84°) | Gran Vía (68°) | Paseo del Prado (5°) | Alcalá (20°) |
| --- | --- | --- | --- | --- | --- |
| full (921 km of facades) | 9.8 % | **25.0 %** | 5.7 % | 5.2 % | 4.4 % |
| Sol, 500 m | **17.6 %** | 11.9 % (85°) | 7.6 % (80°) | — | 2.5 % |

There is no single best rotation:
- The Barrio de Salamanca's Ensanche grid east of Recoletos is turned about −6° (72–90 % of its facades aligned at −6°, 2–4 % at 0°) and dominates the full area by length.
- The historic centre (Sol, Austrias, Letras, Jerónimos) fits 0° better (up to 79 % per 750 m block).

Screenshots of 600 m test areas at both rotations: `docs/img/rot-*`.

## Full area and performance (Phase 5)

### Build

`sh scripts/build_data.sh` for the full area (3750 × 2750 cells, 202 levels over base 578 m), each step timed by `measure.py`. Downloads and LiDAR tiles were already cached, so the Catastro time (7.3 min) is from the tile grid; a first build adds about 1 h of Catastro WFS and a few minutes of Overpass and WMS.

| Step | Time | Peak memory |
| --- | --- | --- |
| prep_lidar (92.5 M points) | 71 s | 1.5 GB |
| prep (rasters + ortho on the grid) | 79 s | 3.8 GB |
| voxelize | 447 s | **12.8 GB** |
| zones / windows / places / phenology / terrain | 16 / 6 / 4 / 3 / 1 s | ≤ 1.4 GB |
| cost1m (meshes 660 tiles in the browser) | ~1 min | browser |

The whole volume fits in memory (12.8 GB of the 38 GB machine), so the 128-row band fill from dtla-voxel was not adopted.

### Sizes

- `web/public/data`: **27 MB**.
  - Breakdown: tiles 13 MB (660 level-1 nodes, 1f foliage, 12 level-8 nodes), `trees.json` 6.4 MB, `traffic.json` 4.1 MB, zones, places, foliage and terrain about 3 MB.
  - Production build (`web/dist`): 29 MB.
- Cache `$MADRID_CACHE`: **4.1 GB**.
  - LiDAR tiles: 1.6 GB (19 tiles).
  - Full area: 1.2 GB (orthophoto, rasters, OSM, Catastro).
  - Shared Catastro tiles, test areas, inventory CSV.
- Full area content:
  - 14 523 building features (4 111 parts); 8 459 take Catastro floors and 108 Catastro buildings are added.
  - 51 463 trees: 43 065 from the inventory, 2 911 from OSM and 5 487 LiDAR crowns with no known tree. Of these, 44 551 are drawn under a LiDAR crown and 6 591 young.
  - 2 202 street lamps; crossings 403 from ways, 407 from nodes and 114 ambiguous.
  - 5 529 bridge deck cells (349 from PNOA class 17), 131 underpass passages, 1 301 church window cells.
  - 410 labels, 9 982 search places, 321 palette entries.

### Rendering (`scripts/profile.py`, `docs/profile.json`)

Headless Chromium on the development laptop's Intel UHD 620 (integrated), ANGLE GL. Desktop at render size 1 (the whole city at 1 m: 15.9 M triangles, 424 MB of GPU buffers, 247 MB of column data per `cost1m.py`):

| View | fps | triangles | no shadows | no post-processing | JS heap |
| --- | --- | --- | --- | --- | --- |
| overview (whole map) | 5.4 | 21.2 M | 6.6 | 8.3 | 0.5 GB |
| palace | 10.1 | 5.7 M | 11.8 | 20.3 | 1.1 GB |
| sol | 14.4 | 2.2 M | 16.0 | 33.8 | 1.3 GB |

- Post-processing (N8AO, bloom, tilt-shift, tone) is the largest single cost on this GPU, about half the frame time. Shadows cost 10–20 %.
- On a weak GPU the viewer's adaptive render size lowers the 1 m budget by itself; the figures above are with it pinned at 1.

**Phone** (Playwright iPhone 13 emulation, the viewer's own 0.75 M-triangle budget):

| View | fps | triangles | no shadows | no post-processing | JS heap |
| --- | --- | --- | --- | --- | --- |
| overview | 25.4 | 2.9 M | 26.5 | 38.1 | 194 MB |
| palace | 25.6 | 1.5 M | 31.3 | 52.9 | 165 MB |
| sol | 30.5 | 1.1 M | 31.6 | 59.9 | 194 MB |

- 88–110 level-1 tiles are loaded, plus 12 level-8 clay tiles.
- Before `cost1m.py` existed, every city block cost 0 triangles in `zones.json`, so the budget never bit: the emulated phone loaded all 1 320 tiles with 0.8–1.3 GB of heap. Warsaw generated that table with `web/tools/cost1m.mjs`; `scripts/cost1m.py` is its port and runs in `build_data.sh`.
- The 2 and 4 m tile levels (Phase 5 option) are not needed: phones stay within budget with clay beyond, and desktops load the whole map.

### Defects reviewed at scale

- **Map edges:** two crashes on features cut by the edge, both fixed. Church windows were probed past the grid, and a stairwell just off the map broke the underpasses.
- **Lane offsets:** a lane line folded on a tight bend (Barrio de Salamanca) stopped the build; now dashes are laid on each piece.
- **Bridges and flyovers:** the Viaducto de Segovia deck stands over the Calle de Segovia valley with lane markings and traffic (`docs/img/phase5-viaduct.png`); class 17 added 349 deck cells next to OSM bridge ways.
- **Tunnels and underpasses:** 131 passages and 113 stairwells carved (Warsaw's `underpass.py`).
- **Construction sites:** not reviewed one by one (`todo.md`).
- **Catastro:** one 31 m square of building parts the service cannot serve is skipped (`skipped` in the GeoJSON).

### Crowns, lamps and labels after the extension

- **Crown clearance** (`voxelize.py`, after the per-trunk dome): `crown_bot` is raised to 4.5 m over `_hard` ground (water aside) and to 3 m over every surface but lawns, beds and scrub. Rim cells left thinner than a voxel are not filled (`leaf_at`), and `veg` itself is unchanged because the parked-car test reads it. A trunk under a bare rim cell stops at the crown's top. 977 609 canopy cells raised, 40 605 rim cells left bare.
- **Measuring foliage height:** decode `tiles/1f` (counts, ground, runs) and take the lowest leaf run per column against the column's ground. `docs/img/crowns-*-{before,after}.png` are pedestrian views (eye 1.7 m, target 20 m ahead).
- **Street-level screenshots:** the viewer's tilt limit (`TILT` = 0.48π in `web/src/nav/nav.ts`) lifts a camera that looks less than 3.6° down. A target 120 m away 1 m lower puts the eye at about 9 m, so street-level cameras need a target about 20 m ahead.
- **Lamps:** heights by the road beside the post (`lamp_height` in `voxelize.py`); 2 287 lamps.

### Extended area at −6° (after Phase 6)

The full area now runs from the Templo de Debod to just past Calle del Doctor Esquerdo, with the grid at −6°: 4 400 × 2 850 cells, centre 441 126.2, 4 474 323.7 (`DECISIONS.md`). It needs 24 LiDAR tiles (X 438–443 km, Y 4472–4476 km).

| Step | Time | Peak memory |
| --- | --- | --- |
| fetch_osm (9 Overpass tiles, first download) | 648 s | 0.9 GB |
| fetch_catastro (new tiles only) | 2 472 s | 0.7 GB |
| prep_lidar (24 tiles) | 119 s | 1.7 GB |
| prep | 95 s | 4.8 GB |
| voxelize | 553 s (1 162 s on a second run with the machine busy) | **15.9 GB** |
| cost1m (805 level-1 tiles) | 55 s | browser |

- **Inputs:** OSM 342 525 elements (81 MB); 49 065 inventory trees; Catastro 18 177 buildings and 129 898 parts.
- **Output:** 17 003 building features (4 697 parts); 422 labels; 18.6 M triangles at 1 m (498 MB of GPU buffers).
- **Sizes:** `web/public/data` is 32 MB; the cache is 7.1 GB.
- **Downloads:**
  - The IGN orthophoto WMS answered some 1 km tiles with "502 Proxy Error" for a while. `fetch_ortho.py` keeps the tiles it got, so re-running it finishes the mosaic.
  - The Catastro WFS now fails on four 31 m squares of building parts near Calle de Toledo, not one; they are listed under `skipped`.

## Publication (Phase 6)

Not published yet: creating the public GitHub repository was blocked by the permission settings of the working session and is left to the user (`todo.md` has the commands). Everything else for publication is done:

- **Workflow:** `.github/workflows/pages.yml` builds the viewer with the pnpm lockfile and deploys `web/dist` to GitHub Pages on every push to `main` (Warsaw's workflow, the same as dtla-voxel's but with pnpm; the analytics variables are removed). The data is committed, so the workflow does not build it.
- **Removed from the viewer:** the PostHog analytics library and Warsaw's sharing image.
- **Attribution review before publishing:**
  - Every commit is the user's (`Agboyano <agboyano@protonmail.com>`), with no trailers.
  - The repository has no AI credits. The remaining mentions are the `CLAUDE.md` rules file, referred to by name.
  - The inherited `web/tools` scripts' temp paths were renamed.
