# Plan: Madrid in voxels

Each phase ends with a **checkpoint**: stop, summarise and wait for the user's approval before continuing.

At every checkpoint, also run an attribution audit and include the result in the summary: `git log --format='%an <%ae>%n%B'` must show only the user's identity and no `Co-Authored-By` for Claude or Anthropic, no "Generated with Claude Code" and no `Claude-Session` lines; the same applies to any pull request opened in the phase.

---

## Phase 0: Setup and understanding the code

The user starts this phase with a new, empty repository (not a GitHub fork) containing only `CLAUDE.md`, `PLAN.md`, `docs/research.md` and `.claude/settings.json`.

- [x] Check that `.claude/settings.json` exists with attribution disabled (`"attribution": {"commit": "", "pr": "", "sessionUrl": false}`) and that `/status` lists it among the loaded setting sources. If it is missing, stop and tell the user.
- [x] Install a **local, unversioned** `commit-msg` hook at `.git/hooks/commit-msg` (make it executable) that rejects AI attribution:

  ```sh
  #!/bin/sh
  # Reject AI attribution in commit messages.
  if grep -qiE 'co-authored-by:.*(claude|anthropic)|noreply@anthropic\.com|claude-session:|generated with \[?claude' "$1"; then
    echo "commit-msg: AI attribution found in the commit message. Remove it and commit again." >&2
    exit 1
  fi
  ```

- [x] Test the hook: a commit message containing `Co-Authored-By: Claude <noreply@anthropic.com>` must be rejected, and a normal message accepted. Do not leave the test commit in the history.
- [x] Check that the git identity (`git config user.name` and `user.email`) is the user's, and record it in `NOTES.md` without changing it.
- [x] Clone `https://github.com/stared/warsaw-vibe-voxel` into `../warsaw-vibe-voxel` (outside the repository, read-only) and record the commit hash used (it will go in `NOTES.md`).
- [x] Copy the Warsaw working tree into this repository **without its `.git` folder** and without overwriting the four files above. Copy its `LICENSE` as `LICENSE-warsaw-vibe-voxel`.
- [x] Commit it as a single commit by the user, for example `Import warsaw-vibe-voxel at <hash> (MIT, © 2026 Piotr Migdał)`, with no attribution trailers.
- [x] Check that the Warsaw tiles already generated are in the repository (`web/public/data`). If they are not, stop and tell the user.
- [x] Install the Node dependencies and start **only the viewer** with those tiles (`cd web && npm install && npm run dev`), without changing anything. **Do not run the Warsaw data pipeline** or download its data.
- [x] Install the project's Python dependencies (without running the scripts) and record in `NOTES.md` any installation problems, especially with geospatial libraries (PDAL, GDAL, laspy, rasterio).
- [x] Record the size of `web/public/data` in `NOTES.md` as a reference.
- [x] Read `scripts/` and `web/src/` and write a pipeline map in `NOTES.md`: each script, its inputs, its outputs, execution order and the format of intermediate files. Since it is not run, infer this from the code.
- [x] Identify everything Warsaw-specific (landmarks, trees, Vistula/`flood.py`, trams, Palace of Culture, palette) and list it in `NOTES.md` with file and line.
- [x] Voxel size inventory in `NOTES.md` ("1 m assumptions" section): list, with file and line, every place in the pipeline and viewer where 1 m is fixed, explicitly or implicitly. Check at least:
  - Tile levels (1 and 8 m, plus the `1f` foliage set; there are no 2 or 4 m levels) and cell size in `tiles.py`, `stream.ts` and the viewer's reader.
  - Height encoding in the tiles: data type and maximum representable height (check whether a 250 m building would fit with 0.5 m voxels).
  - Object scales: pedestrians, trees, street lamps, crossings, vehicles.
  - Landmarks and hand-tuned corrections in voxel coordinates.
  - Shadows, lighting, camera (distances, zoom limits) and the streaming refinement criterion.
  - Finally, a short estimate of what moving to 0.5 m voxels would involve: affected files, expected data size and risks.
- [x] Clone `https://github.com/sigman78/dtla-voxel` into `../dtla-voxel` (outside the repository, read-only).
- [x] Analyse `../dtla-voxel` and document in `NOTES.md`, for each piece, what it does, what it depends on and how much adaptation Madrid would need:
  - `prep_lidar.py` and `fetch_*.py` (point cloud and area-limited downloads).
  - `voxelize.py`: fill in 128-row bands; compare with Warsaw's `voxelize.py`.
  - `layers.py` (2D fusion) and `aoi.py` (rotated grid).
  - `road_markings.py` and street lamp placement.
  - `.github/workflows/` and the profiling harness (`artifacts/profiling`, `docs/rendering-profile.html`).
  - Tree detection from NDVI and multiple returns (optional).
- [x] Check that the tile format (`tiles.py`) is identical in both projects.
- [x] Create `scripts/screenshot.py` (Playwright, headless) that starts the viewer, opens a view from URL parameters (`cam`, `hour`, etc.) and saves a screenshot in `docs/img/`. Test it with the Warsaw tiles and save 2 or 3 screenshots as a visual reference of how the result should look.
- [x] Create `NOTES.md` and `DECISIONS.md`.

**Checkpoint 0:** Warsaw viewer running with reference screenshots, Python dependencies installed, `NOTES.md` with the pipeline map, the list of Warsaw-specific code and a proposal of which pieces of `../dtla-voxel` to copy and in which phase.

> **Optional diagnosis:** rebuild the Warsaw data only if something fails in Phase 2 and it is unclear whether the problem lies in the Madrid changes or in the environment. It is not a required step.

---

## Phase 1: Madrid data sources

Test area: **500 × 500 m centred on Puerta del Sol** (approx. X 440 290, Y 4 474 260 in EPSG:25830; verify).

- [ ] Copy `LICENSE` from `../dtla-voxel` as `LICENSE-dtla-voxel` before bringing in any code from that project.
- [ ] `scripts/aoi.py`: define the Madrid AOI with centre, size and rotation as parameters (initial rotation 0°), starting from LA's `aoi.py`.
- [ ] Use LA's `fetch_*.py` as the template for all downloads: read only the area needed and cache in `$MADRID_CACHE`.
- [ ] `fetch_osm.py`: Overpass download limited to the AOI.
- [ ] `fetch_pnoa_lidar.py`: 1 × 1 km LAZ tiles of the 3rd coverage (NPC02) covering the AOI. It is the **single source for elevation and classification**. Find out whether the Centro de Descargas del CNIG allows automated downloads; if not, give manual download instructions (rule 5 in `CLAUDE.md`). If NPC03 is ever published for Madrid, use it instead.
- [ ] `fetch_trees.py`: tree inventory from datos.madrid.es, filtered to the AOI. Map the Spanish column names to English identifiers.
- [ ] `fetch_catastro.py`: INSPIRE buildings for municipality 28079, clipped to the AOI.
- [ ] `fetch_ortho.py`: most recent orthophoto available for the AOI.
- [ ] Report in `NOTES.md`: for each source, date, CRS, height reference and actual resolution. For the PNOA, using `pdal info` or similar:
  - Measured density in pts/m² (~5 expected) and capture date from the header.
  - Classes present and point count per class (check that the bridge class, 17, exists).
  - Whether the points carry near-infrared (RGBNir): compute a test NDVI over an area with trees, for example Paseo del Prado.
  - Classification errors visible around Sol (cars, awnings, street furniture).

**Checkpoint 1:** source report. If the files have no infrared or important classes are missing, propose alternatives (NDVI from the PNOA orthophoto, classification supported by OSM and Catastro).

---

## Phase 2: Minimal elevation test

- [ ] Adapt LA's `prep_lidar.py` to turn the NPC02 cloud into rasters of ground (equivalent to a DTM), surface (equivalent to Warsaw's NMPT) and classes. Use the PNOA classification instead of LA's class inference. Guidelines:
  - **Rasterise directly into the rotated grid:** assign each point to its cell in the `aoi.py` frame (centre + rotation); never rasterise in UTM and rotate afterwards, to avoid resampling twice. Changing the rotation in Phase 4 must only mean re-running this step.
  - **Resolution as a pipeline parameter,** set according to source density. With NPC02 (~5 pts/m²) the main resolution is 1 m. Use 0.5 m only if the Warsaw code needs it for something specific (check in the Phase 0 pipeline map); in that case, measure the percentage of empty cells and interpolate them explicitly.
  - **Compatibility:** the rasters must have the format, origin and orientation that Warsaw's fusion expects, so it can be reused unchanged. Document exactly what it expects in `NOTES.md`.
- [ ] Design the elevation source abstraction layer (common intermediate format) so that adding the municipal 2026 flight in the future only means writing a new `fetch_` and an adapter. The raster resolution must be changeable through configuration without touching code.
- [ ] Generate voxels for the test AOI with ground and elevation only, generic palette.
- [ ] Screenshots from 3 views (top-down, oblique over Sol, street level).
- [ ] Assess quality: holes in roofs, roof edges and cornices, inner courtyards, trees, artefacts. Measure the percentage of 1 m roof cells with no points and how they are filled.
- [ ] **Optional, only if roofs come out with many holes or very ragged edges:** download the Ayuntamiento DSM 2023 for the AOI (`fetch_dsm.py`), build a variant with its heights and compare screenshots. Bear in mind it dates from 2023 (the LiDAR is from 2024) and is unclassified.

**Checkpoint 2:** the user approves the NPC02 elevation result, or decides whether it is worth complementing with the DSM 2023. Log it in `DECISIONS.md`.

---

## Phase 3: Full fusion in the test area

- [ ] Reorganise the fusion into 2D layers following the structure of LA's `layers.py` (ground, buildings, roofs, vegetation, bridge decks and flyovers).
- [ ] Classification: ground, buildings, vegetation, water, from PNOA + OSM + Catastro.
- [ ] Buildings: footprints (Catastro or OSM; document which and why) with LiDAR heights and roofs. Adapt Warsaw's rules: OSM/Catastro wins where the LiDAR sees nothing tall (building completed after the flight).
- [ ] Trees: municipal inventory with species for seasonal foliage; trees with no LiDAR crown become young trees.
- [ ] Optional: measure how many LiDAR crowns have no tree in the inventory (private courtyards, gardens). If there are many, fill them in with LA's NDVI and multiple-return detection, computing NDVI from the PNOA cloud's own infrared (or from the orthophoto if the cloud lacks it). Log the decision in `DECISIONS.md`.
- [ ] Flyovers and bridges from PNOA class 17.
- [ ] Streets, pavements, squares, parks and water from OSM.
- [ ] Pedestrian crossings and road markings, adapting LA's `road_markings.py`.
- [ ] Street lamps: check how many OSM has in the AOI; if few, place them along kerbs as LA does.
- [ ] Roof and vegetation colours from the orthophoto.
- [ ] Remove or stub out all the Warsaw-specific code listed in Phase 0.
- [ ] Screenshots of the 3 reference views.

**Checkpoint 3:** the test area is recognisable as Madrid. List of known defects.

---

## Phase 4: Madrid identity

- [ ] Madrid palette in `palette.py`: exposed brick, Spanish clay roof tiles, slate (Madrid de los Austrias), granite, light render, zinc roofs.
- [ ] `fetch_wikidata.py`: link landmarks through the **`wikidata=Q…` tag of OSM objects**, never by name search. Collect every OSM feature in the AOI that has the tag and query Wikidata for those IDs in one batch (SPARQL or `wbgetentities`), cached in `$MADRID_CACHE`. Report in `NOTES.md` how many features have the tag and which important landmarks lack it.
- [ ] Landmarks (English name plus Spanish name where it differs). Required set, which must all be linked: Palacio Real, Almudena Cathedral, Plaza Mayor, Puerta del Sol, Metrópolis Building, Cibeles, Puerta de Alcalá, Prado Museum, Retiro Park and Palacio de Cristal. If any lacks the OSM tag, map its Wikidata ID explicitly in a small override table, documented in `DECISIONS.md`.
- [ ] Extended set: propose to the user, at the checkpoint, which other tagged features in the AOI deserve a label (selection criteria such as heritage status or a Wikipedia article), to avoid cluttering the map.
- [ ] Landmark info cards: when a landmark is selected, show a short card with the facts Wikidata provides, only those present for each item: year built or opened, architect, height, architectural style, heritage designation (Bien de Interés Cultural), official website and Wikipedia link. Store the facts as static data generated at build time; the viewer makes no runtime requests to Wikidata.
- [ ] Credit Wikidata (CC0) in the README alongside the other data sources.
- [ ] Try 2 or 3 grid rotations (0°, aligned with Gran Vía, aligned with Paseo del Prado) and compare screenshots of the staircase effect.
- [ ] Adjust the seasonal tree cycle to the most common species in the Madrid inventory.

**Checkpoint 4:** the user approves palette, rotation, the landmark list (required and extended sets) and the info cards.

---

## Phase 5: Full area and performance

- [ ] Extend the AOI to the proposed final area: from Templo de Debod/Plaza de España to Retiro, and from Bilbao to Atocha (approx. 4.5 × 3.2 km; confirm the limits with the user).
- [ ] If voxelisation does not fit in memory, adopt the 128-row band fill from LA's `voxelize.py`.
- [ ] Measure and record in `NOTES.md`: build time, peak RAM, cache size and `web/public/data` size.
- [ ] Adapt LA's profiling harness to measure shadows, post-processing and tile memory.
- [ ] Review defects at scale (map edges, tunnels, flyovers, construction sites).
- [ ] Test mobile performance (Playwright emulation) and adjust levels of detail if needed.
- [ ] Option, only if distant blocks drawn as grey 8 m clay or frame rate are a problem at full area: add 2 and 4 m tile levels with dtla-voxel's `tiles.py` (trailing `detail` block) and port its screen-space level selection (`tileSelection.ts`) to the viewer. Byte-compatible with the current tiles, about +10 % data, but a large viewer change (foliage, building ids, window shader and collisions assume level 1 is the finest). Log the decision in `DECISIONS.md`.
- [ ] Final screenshots of 5 iconic views.

**Checkpoint 5:** full area approved.

---

## Phase 6: Publication

- [ ] GitHub Actions workflow that builds the viewer and deploys it to GitHub Pages, starting from LA's `.github/workflows/`.
- [ ] README in English: what it is, screenshots, how to build it, data sources with attributions and licences, credits to Piotr Migdał (warsaw-vibe-voxel) and sigman78 (dtla-voxel).
- [ ] Known limitations section (as in dtla-voxel).
- [ ] Final attribution review before publishing: search the whole repository (code, comments, docs, package metadata, workflow files, site HTML) and the git history for AI credits or attribution, and remove any found. The GitHub contributors list must show only the user; upstream authors are credited in the README and licence files, not through git history.
- [ ] Check that the published site loads correctly.

**Checkpoint 6:** site published.

---

## Phase 7 (future): data updates

**Municipal 2026 flight**, once the Ayuntamiento publishes it on the Geoportal:

- [ ] Check format, CRS, actual density and classification codes; create an equivalence table with the PNOA classes if needed.
- [ ] Add `fetch_madrid2026.py` and its adapter to the intermediate format.
- [ ] Refine the intermediate raster resolution according to density (with ~30 pts/m², 0.5 m or even 0.25 m) to improve roof edges and cornices. Measure empty cells to choose the value.
- [ ] Rebuild and compare before/after screenshots.

**PNOA-LiDAR NPC03**, once published for Madrid:

- [ ] Change the version in `fetch_pnoa_lidar.py`, rebuild and compare screenshots. **Do not change the resolution:** it is the same cloud with the same density as NPC02; only the classification improves.

> **1 m voxels:** kept in all cases. Moving to 0.5 m voxels would multiply data volume by 8 and require changing the tile format and the viewer. It would be a separate project, to be considered only if the user asks for it.
