# Decisions

Log of non-trivial decisions: date, decision, reason and rejected alternatives.

## 2026-11-10: Default branch `main`

- **Decision:** the repository's initial branch is `main`.
- **Reason:** GitHub's default, and what the Pages workflow from dtla-voxel will expect.
- **Rejected:** `master` (git's built-in default here).

## 2026-11-10: Install the viewer with pnpm from its lockfile

- **Decision:** install `web/` dependencies with `npx -y pnpm@12.11.2 install --frozen-lockfile` and run the dev server with `npx -y pnpm@12.11.2 exec vite`.
- **Reason:** the Warsaw viewer declares `packageManager: pnpm@12.11.2` and ships `pnpm-lock.yaml`; this reproduces the upstream dependency versions exactly, with no global install.
- **Rejected:** `npm install` as written in `PLAN.md`, which ignores the pnpm lockfile, resolves versions afresh and adds a `package-lock.json`.

## 2026-11-10: Screenshot harness on the system Chromium and the real GPU

- **Decision:** `scripts/screenshot.py` uses Python Playwright (dev dependency) with the system Chromium, ANGLE on the GPU (`--use-angle=gl`), and sets the viewer's "Render size" slider to 1 before capturing.
- **Reason:** headless Chromium otherwise renders with SwiftShader, which cannot stream the city in reasonable time; and the viewer's adaptive level draws most of the map as grey clay on slow GPUs, which makes screenshots depend on the machine. Setting the slider uses the existing UI, so the viewer is unchanged.
- **Rejected:** downloading Playwright's bundled Chromium (extra download, same result); reusing `web/tools/shot.mjs` (Node, macOS Metal flags, writes outside `docs/img/`); changing the viewer to accept a level parameter (Phase 0 must not change the viewer).

## 2026-11-10: Keep Warsaw's `tiles.py`

- **Decision:** keep Warsaw's `scripts/tiles.py` and tile reader as they are.
- **Reason:** dtla-voxel's tiles are byte-compatible but add levels 2 and 4 and an optional detail block that Warsaw's `city.ts` does not use; `CLAUDE.md` rule 7 forbids format changes unless the plan says so.
- **Rejected:** adopting dtla's `tiles.py` (needs viewer changes for no Madrid-specific gain).

## 2026-11-10: AOI centre on the OSM Puerta del Sol square

- **Decision:** centre the 500 × 500 m test AOI on the centre of the OSM square (relation 7424032) at X 440 316.4, Y 4 474 264.1, rotation 0°.
- **Reason:** a reproducible, documented point on the square itself; the approximate point in `PLAN.md` is 26 m away and kilometre zero is at the square's southern edge.
- **Rejected:** the approximate plan coordinates; kilometre zero.

## 2026-11-10: Whole-city download for the tree inventory

- **Decision:** download the municipal tree CSV once for the whole city (75 MB) and filter it locally to the AOI.
- **Reason:** datos.madrid.es publishes the per-tree inventory only as one file (CSV, XLSX or shapefile); there is no area query. The CSV is the smallest format and is cached.
- **Rejected:** the shapefile ZIP (49 MB but needs a GIS reader); the XLSX (64 MB, slower to parse).

## 2026-11-10: Catastro from the INSPIRE WFS, not the ATOM files

- **Decision:** read Catastro buildings and building parts from the INSPIRE Buildings WFS by bounding box, in 500 m tiles.
- **Reason:** it reads only the AOI (`CLAUDE.md` rule 4) and returns the same INSPIRE features as the ATOM download, which is one GML for the whole municipality.
- **Rejected:** the ATOM municipality download (far larger than the AOI).

## 2026-11-10: Orthophoto from the IGN PNOA WMS (July 2023, 0.25 m)

- **Decision:** take the orthophoto from the IGN WMS "PNOA máxima actualidad" at its native 0.25 m, axis-aligned in EPSG:25830, and warp it onto the rotated grid during raster preparation.
- **Reason:** it is the newest PNOA flight over the AOI, it is served by area, and the CNIG file downloads sit behind the same reCAPTCHA as the LiDAR. Warping later means a new rotation needs no new download.
- **Rejected for now:** the Ayuntamiento Geoportal orthophoto (possibly newer or a true orthophoto; to evaluate at the checkpoint); colours from the LiDAR points' own RGB (a Phase 3 option).

## 2026-11-10: PNOA-LiDAR downloaded by hand

- **Decision:** `fetch_pnoa_lidar.py` does not download; it lists the tiles needed, validates the LAZ files placed in the cache by their headers and prints manual instructions.
- **Reason:** the CNIG download centre protects downloads with reCAPTCHA and refuses scripted searches. `CLAUDE.md` rule 5 asks for manual instructions instead of alternative sources or workarounds.
- **Rejected:** scripting the CNIG site; third-party mirrors of the PNOA files.

## 2026-11-11: Keep the PNOA orthophoto for roof and vegetation colours

- **Decision:** use the IGN PNOA orthophoto (July 2023, 0.25 m) for colours.
- **Reason:** approved at Checkpoint 1; it is already downloaded, aligns with Catastro and the trees, and is a leaf-on summer image.
- **Rejected:** the Ayuntamiento Geoportal orthophoto (not evaluated); the LiDAR points' own RGB (March 2024, leaf-off).

## 2026-11-11: Overlap points (class 12) for heights, class from neighbours

- **Decision:** use class 12 (overlap) points for surface heights, and take their semantic class from the non-overlap points of the same cell or its neighbours.
- **Reason:** 42 % of the points in the AOI are class 12, largely on roofs; they are valid measurements but carry no ground, building or vegetation class. Approved at Checkpoint 1.
- **Rejected:** dropping overlap points (halves the density, more empty cells); treating them as unclassified.

## 2026-11-11: Intermediate elevation rasters at 1 m, rasterised on the rotated grid

- **Decision:** `prep_lidar.py` writes the common elevation format at 1 m (`pipeline.toml`), assigning each point to its cell of the rotated grid; `prep.py` expands the DSM to the 0.5 m that Warsaw's `voxelize.py` expects by nearest neighbour.
- **Reason:** NPC02 has 5.9 own points/m², about 1.5 per 0.5 m cell, too few for a 0.5 m surface without interpolating most cells; nothing in Warsaw's code needs true 0.5 m detail. Rasterising on the rotated grid avoids a second resampling.
- **Rejected:** a 0.5 m DSM from NPC02 (many empty cells); rasterising north-up and rotating (two resamplings); changing the six places in `voxelize.py` that hard-code ×2 (not needed).

## 2026-11-11: Ground gaps by multi-scale fill; vehicles out of the surface

- **Decision:** the DTM fills cells without ground points (72 % of the AOI, mostly under buildings) with a push-pull multi-scale average, smoothed only where filled. Vehicle points (class 64) are left out of the DSM.
- **Reason:** `voxelize.py` requires a gap-free DTM, and the fill is O(n) for the full area. Parked cars are not part of the city's surface; the viewer animates its own vehicles.
- **Rejected:** Delaunay or griddata interpolation (slow on the full area); the Ayuntamiento DTM (a second source, against the single-source rule).

## 2026-11-11: A minimal voxeliser for the elevation test

- **Decision:** test the elevation with `voxelize_elevation.py`, which writes only what the viewer needs, instead of running Warsaw's `voxelize.py`.
- **Reason:** Phase 2 asks for ground and elevation only; Warsaw's `voxelize.py` needs the Phase 3 inputs and stops on Warsaw names (it looks the Palace of Culture up by name).
- **Rejected:** stubbing Warsaw's `voxelize.py` for this phase (more changes to code that Phase 3 reworks anyway).

## 2026-11-11: No Ayuntamiento DSM 2023 for now

- **Decision:** skip the optional DSM 2023 test.
- **Reason:** only 1.2 % of roof cells have no LiDAR point and they fill cleanly; the visible defects come from fusion (facades, pitched roofs, trees), not from the elevation source. Pending the user's approval at Checkpoint 2.

## 2026-11-11: Building footprints from OSM, floors from Catastro

- **Decision:** OSM footprints, with heights from the LiDAR; Catastro gives floors where OSM has no height or levels, and adds the buildings OSM lacks.
- **Reason:** OSM and Catastro footprints coincide (IoU 0.957); OSM carries the names, Wikidata links, colours and the building/part structure the fusion rules use, Catastro the floor count of every volume (OSM has levels on 21 % of buildings).
- **Rejected:** Catastro footprints alone (no names, tags or parts, would need a new styling path); OSM alone (no floors for the "built after the flight" rule on 79 % of buildings).

## 2026-11-11: Reuse Warsaw's fusion, reorganised into layers

- **Decision:** keep Warsaw's fusion rules (`voxelize.py`), removing what is Warsaw-specific, and reorganise them into `layers.py` (2D, dtla-voxel's structure) and `voxelize.py` (3D fill).
- **Reason:** the viewer's features (zones, traffic, windows, foliage, underpasses) depend on what Warsaw's fusion produces; a byte-identical split keeps that behaviour while giving the dtla-voxel structure.
- **Rejected:** rebuilding the fusion on dtla-voxel's `layers.py` and `voxelize.py` (its LA class inference and palette do not apply, and the viewer's Warsaw data products would have to be re-derived).

## 2026-11-11: Lamps from OSM, crossings from dtla-voxel, no NDVI tree detection

- **Decision:** street lamps from OSM only; crossings with dtla-voxel's `road_markings.py`; no NDVI or multiple-return tree detection.
- **Reason:** OSM maps 80 lamps in the test area (74 drawn). dtla-voxel's crossings follow traffic and fall back to marked nodes. Only 22 LiDAR crowns lack an inventory tree.
- **Rejected:** dtla-voxel's lamps every 36 m along kerbs (would double the mapped lamps); NDVI from the leaf-off PNOA cloud (weak on deciduous crowns, see Phase 1).
