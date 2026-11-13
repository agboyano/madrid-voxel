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

## 2026-11-11: Checkpoint 3 — bridge test deferred, viewer cleaned now

- **Decision:** test the class 17 decks when the AOI grows in Phase 5; remove the Warsaw remnants from the viewer now (floodlight schedule, Vistula flood, zouk floor, Polish train liveries).
- **Reason:** the test area has no bridge, and the download caches are not keyed by AOI, so moving the AOI to a bridge would reuse the wrong cached data. Approved by the user at Checkpoint 3.

## 2026-11-11: Full area now, 3.75 × 2.75 km

- **Decision:** move to the full area in Phase 4: X 439 000–442 750, Y 4 472 950–4 475 700 (Templo de Debod to the Retiro's east edge, Glorieta de Bilbao to Atocha), rotation decided at Checkpoint 4.
- **Reason:** nine of the ten required landmarks lie outside the 500 m test area. Chosen by the user; limits confirmed.
- **Rejected:** linking landmarks without drawing them; an intermediate 1.5 km area.

## 2026-11-11: Areas and caches per AOI

- **Decision:** build areas in `pipeline.toml`; everything cut to an area cached in its own folder (key: centre, size, rotation).
- **Reason:** the downloads and rasters were cached under fixed names, so a new AOI would have reused another's data.

## 2026-11-11: Madrid roof materials from the ortho, grey roofs as terraces

- **Decision:** roofs take one of four Madrid materials (tile, slate, zinc, terrace) from OSM or the ortho; grey roofs are flat terraces, zinc only on mansards.
- **Reason:** Warsaw's desaturated ortho median drew a cold grey over Madrid's mixed and flat roofs; about 40 % of roofs round Sol read grey in the ortho, and in central Madrid those are azoteas.
- **Rejected:** grey as zinc (the first try turned half the roofs blue-grey).

## 2026-11-11: Required landmarks by Wikidata id; Cibeles is the fountain

- **Decision:** `REQUIRED` in `fetch_wikidata.py` lists the ten by Wikidata id; each is linked through its OSM element's `wikidata` tag. Cibeles is the Fuente de Cibeles (Q2736564). `ENGLISH_NAMES` fixes English labels that are not the name used in English (Plaza Mayor).
- **Reason:** the ids were read off the tagged OSM elements in the area; no override table was needed.

## 2026-11-11: Phenology from iNaturalist in Spain, Portugal and Italy

- **Decision:** leaf-out and colouring dates from iNaturalist leaf annotations in Spain, Portugal and Italy; leaf fall = colouring + 17 days; spread between trees from Warsaw's DWD series.
- **Reason:** the German DWD network does not fit Madrid's climate; Spain alone has too few annotations per genus.
- **Rejected:** DWD dates (Central Europe); Spain only (most genera fall back to the median).

## 2026-11-11: Grid rotation 0° for the full area

- **Decision:** keep the full area at 0°.
- **Measured** (`rotation_report.py`, share of Catastro facade length within 3° of the grid):
  - over the full area, 0° → 9.8 %, −6° → 25.0 %, Gran Vía (68°) → 5.7 %, Paseo del Prado (5°) → 5.2 %;
  - at Sol, 0° → 17.6 %, −6° → 11.9 %;
  - the Barrio de Salamanca's Ensanche is turned −6° (72–90 % of its facades aligned at −6°), while the historic centre (Sol, Austrias, Letras, Jerónimos) fits 0°.
- **Screenshots** of 600 m test areas at both rotations (`docs/img/rot-*`): the difference is small at Sol and visible but modest in Salamanca.
- **Reason:** at −6° the rectangle's corners reach X 438 km, which needs four more LiDAR tiles. They can only be downloaded by hand (reCAPTCHA), and the user asked to finish without stopping. Shifting the centre to fit the downloaded tiles drops the Templo de Debod and Glorieta de Bilbao. Most landmarks are in the centre, which 0° fits.
- **Rejected:** −6° with a no-data wedge in the south-west corner; aligning with Gran Vía or Paseo del Prado, both worse than 0°.
- **Revisit:** download `PNOA_2024_MAD_438-4473..4476_H30_NPC02.LAZ` and set `rotation = -6` (`todo.md`).
- **Superseded** by "Full area extended east to Doctor Esquerdo, grid at −6°" below.

## 2026-11-11: Catastro tiles on a shared world grid

- **Decision:** Catastro WFS tiles are 500 m squares on a fixed world grid (origin 438 950, 4 472 900), cached by coordinates in `raw/catastro_tiles` and shared by all areas.
- **Reason:** the WFS is slow (~45 s per tile); a new or rotated area now downloads only the tiles it adds.

## 2026-11-11: The user asked to finish every phase without checkpoints

- **Decision:** from Phase 4 on, decisions normally taken at checkpoints are taken here and recorded in this file; what remains goes to `todo.md`.

## 2026-11-11: Extended label set by rule, listed for review

- **Decision:** label places whose Wikidata item has a heritage designation or a Wikipedia article, excluding boundaries, routes, streets, shops and items that are people, events or organisations. Distance by Wikipedia editions (≥ 15 → 2 500 m, ≥ 4 or heritage → 1 300 m, else 600 m). The full list (410 labels) is in `docs/labels.md`; items can be dropped by id in `EXTENDED_EXCLUDE`.
- **Reason:** the user asked to finish without checkpoints, so the review the plan put at Checkpoint 4 moves to `todo.md`.

## 2026-11-11: No band fill, no 2 and 4 m tile levels

- **Decision:** keep Warsaw's whole-volume `voxelize.py` and the 1 m + 8 m tile levels.
- **Reason:** the full area peaks at 12.8 GB, which fits. Phones keep within their budget once `cost1m.py` prices the blocks (about 100 tiles, ~200 MB heap); desktops load the whole map.
- **Rejected:** dtla-voxel's band fill (a large rewrite for memory not needed); dtla-voxel's 2/4 m levels and screen-space selection (a large viewer change for no measured need).

## 2026-11-11: Price the city blocks with cost1m.py

- **Decision:** port Warsaw's `web/tools/cost1m.mjs` to `scripts/cost1m.py` and run it in the build.
- **Reason:** without per-tile triangle counts, `zones.json` gave every block a cost of 0 and the viewer's triangle budget never applied; an emulated phone loaded all 1 320 tiles.

## 2026-11-11: Remove the analytics library

- **Decision:** remove PostHog (`posthog-js` and its lazy import) and Warsaw's sharing image from the viewer.
- **Reason:** they belonged to the Warsaw deployment; the Madrid site collects nothing.

## 2026-11-11: Publication prepared, left to the user

- **Decision:** the repository is ready to publish (workflow, README, attribution review), but it has not been pushed anywhere. Creating the public repository was blocked by the permission settings of the session that did the work, and publishing a public repository under the user's account is the user's call.
- **How:** `todo.md` gives the commands (create `agboyano/madrid-voxel` or another name, enable Pages in "GitHub Actions" mode, push `main`). Pages on a free account needs a public repository.

## 2026-11-11: Labels in Spanish, English under them

- **Decision:** at the user's request, map labels and info cards show the Spanish name first and the English name under it where it differs (the reverse of the Phase 4 rule in `CLAUDE.md`, which is updated). The Spanish name is the OSM `name` of the linked element, falling back to Wikidata's Spanish label; the English name is `ENGLISH_NAMES`, then Wikidata's English label, then OSM `name:en`.
- **Reason:** the OSM name is the one on the street signs and in the search index ("Palacio de Cristal", "Plaza Mayor", "Monumento a Alfonso XII"); Wikidata's Spanish labels are often formal or historic names ("Palacio de Cristal del Retiro", "Plaza Mayor de Madrid", "Palacio de Quintana" for the Mando Aéreo General) or name the person a statue honours rather than the statue.
- **Rejected:** Wikidata's Spanish label first (above); keeping the `local` field (the viewer now reads `en` for the second line, as Warsaw's did for its English names).

## 2026-11-11: Full area extended east to Doctor Esquerdo, grid at −6°

- **Decision:** at the user's request, the full area reaches Calle del Doctor Esquerdo with the Hospital Gregorio Marañón inside, and the grid is turned −6°. Centre 441 126.2, 4 474 323.7; 4 400 × 2 850 m (12.5 km², +22 %).
- **How the edges were set:** in the −6° frame (u east, n north, from the old centre) the area spans u −1 950…2 450, n −1 400…1 450.
  - **West:** keeps the Templo de Debod (u −1 834).
  - **North:** reaches Glorieta de Bilbao (n 1 179) and Manuel Becerra, where Doctor Esquerdo starts (n 1 391).
  - **South:** reaches Atocha (n −1 149).
  - **East:** the Doctor Esquerdo axis runs at u 2 300–2 380 from the hospital northwards, and the hospital reaches u 2 287. The edge keeps the street and the first metres of its east side. South of O'Donnell the street bends west towards Pacífico; that part is inside too.
- **Reason:** −6° aligns the Barrio de Salamanca's Ensanche, which the extension makes even larger (25 % of facade length aligned against 9.8 % at 0°, `rotation_report.py`). The user downloaded the five LiDAR tiles it needs (438-4473…4476 and 443-4474).
- **Cost:** voxelize 553 s, peak 15.9 GB (was 447 s, 12.8 GB); `web/public/data` 32 MB (was 27 MB).
- **Rejected:** the dtla-voxel band fill, still not needed at 15.9 GB on a 38 GB machine.

## 2026-11-11: Build order: every viewer file before cost1m

- **Decision:** `build_data.sh` runs zones, windows, places and phenology before `cost1m.py`, then zones again with the blocks priced. It also writes `docs/labels.md` (`labels_doc.py`).
- **Reason:** `cost1m.py` loads the viewer, which reads `zones.bin` and the other grids. After a change of area these still had the old size, and the viewer failed (`Invalid typed array length`). Within the same area the old order worked by accident.

## 2026-11-11: Hospitals can carry labels

- **Decision:** `amenity=hospital` joins the place tags in `labels.py`, so a hospital whose Wikidata item has a heritage designation or a Wikipedia article gets a label like any other place.
- **Reason:** the Hospital Gregorio Marañón, which the user asked to have on the map, is tagged `wikidata=Q30253672` (Wikipedia in 4 languages) but carried no label, because `amenity=hospital` was not a place kind.

## 2026-11-11: Clearance under tree crowns

- **Decision:** leaves start at least 4.5 m above carriageways, cycle lanes, parking and rails, and 3 m above every other surface people walk on: pavements, squares, tree pits, and the gravel and earth of boulevards and park paths. Over lawns, beds and scrub the old 2 m floor stays. A crown's rim left thinner than one voxel over a walked or driven surface loses its leaves. Constants `CLEAR_ROAD` and `CLEAR_WALK` in `voxelize.py`.
- **Reason:** the user saw foliage hanging at passers-by's heads. The crown underside was a dome from 38 % of the tree's height over the trunk up to one voxel under the LiDAR top at the rim, with a 2 m floor, so rims came down to 2 m over pavements and roads. Street trees in Madrid are pruned to clear walkers and traffic.
- **Measured** over all level-1 foliage tiles (lowest leaf voxel per column above the ground):
  - leaf columns with leaves under 3 m fell from 34.3 % to 17.9 %;
  - nearly all that remain (347 634) are over grass; 1 401 are over other surfaces, about 0.1 %.
  - Floating leaf voxels removed after the fill fell from 45 988 to 37 034.
- **Rejected:** a single 3 m floor everywhere, which would strip the low crowns of park trees over lawns; leaving gravel and earth at 2 m, since the Salón del Prado and the Retiro's paths are gravel.

## 2026-11-11: Overview frames the whole map

- **Decision:** the overview camera's distance follows the map width (its width plus 10 % across the viewer's 43° horizontal field of view at 16:10), keeping the old pose's slope.
- **Reason:** the fixed pose framed about 2.5 km, so the eastern extension was out of the first view.

## 2026-11-11: Label kinds from Wikidata when OSM's mislead; English only when it names the same thing

- **Decision:**
  - `attraction`, `castle` and `place of worship` join the OSM kinds that defer to the Wikidata type, skipping vague types ("building", "tourist destination", "Monument (Spain)", "organization").
  - The English line is dropped when the OSM name and Wikidata's Spanish label share no word (articles, prepositions and "Madrid" aside), unless `ENGLISH_NAMES` sets it.
- **Reason:**
  - Cibeles and the Metrópolis read "attraction", the Royal Palace "castle"; now "fountain", "building" and "royal palace".
  - Many OSM buildings carry the name of their current occupant while their Wikidata item names the historic building or a body housed in it ("Ministerio de Sanidad…" over "Spanish Agency for Consumer Affairs…"); 26 pairs at the last build. The Wikidata names stay searchable (`alt`).

## 2026-11-11: Madrid street lamp heights

- **Decision:** where OSM gives no height, a lamp is 8 m beside a carriageway at least 12 m wide, 5 m beside other roads, and 4 m in squares and pedestrian streets (Warsaw's 10 m and 6 m before).
- **Reason:** Madrid's avenues have columns of about 8 m, its ordinary streets lower posts and wall brackets, and its squares and pedestrian streets the low "fernandino" lantern posts. The 10 m columns stood over the walkers.

## 2026-11-11: Crowns raised further: 6 / 4.5 / 3 m

- **Decision:** at the user's request after seeing Calle de Serrano, the clearances go up: 6 m over carriageways, cycle lanes, parking and rails (`CLEAR_ROAD`), 4.5 m over pavements, squares and paths (`CLEAR_WALK`), and 3 m over lawns, beds and scrub (`CLEAR_PLANTED`, new; it was the 2 m floor).
- **Reason:** with 3 m the leaves still looked close above the walkers. Serrano's plane trees branch at about 4–5 m, and buses need about 4.5 m over the road.
- **Measured:**
  - leaf columns with leaves under 3 m fell to 1.5 % (34.3 % originally); the 1.4 % under 2 m are hedges and roof gardens, not crowns;
  - 136 713 rim cells of short crowns are left without leaves, and leaf columns went from 1.95 M to 1.86 M;
  - floating leaf voxels removed fell to 29 938.

## 2026-11-11: Leaf dates from Mediterranean-climate regions; Prunus split

- **Decision:**
  - **Regions:** iNaturalist's leaf annotations come from regions with Madrid's climate (Köppen Csa/BSk, Northern Hemisphere): Spain, Portugal, Italy, Greece, Provence-Alpes-Côte d'Azur, Corsica, Cyprus, Turkey, Israel, Lebanon, Morocco, Tunisia, Algeria and California (place ids in `phenology.INAT_PLACES`).
  - **Horse chestnut:** queried as *Aesculus hippocastanum*, not the genus.
  - **Prunus split:**
    - the purple-leaved *Prunus cerasifera* is a class of its own, with a measured base tint (purple all season), its own leaf-out, and no use of the "coloured leaves" annotations, which its purple leaves trigger all summer;
    - the other Prunus are queried without it;
    - the cherry laurels (*P. laurocerasus*, *P. lusitanica*) are evergreen.
  - **Checks:** every class must leaf out, colour and drop in that order, and colour by day 340.
- **Result:**
  - **Measured:** plane trees leaf out on 2 April and colour on 18 November (69 and 227 observations, mostly California and the Mediterranean); the purple plum leafs out on 11 March; the other Prunus on 31 March.
  - **Dropped date:** the Prunus colouring on 13 December disappears.
  - **Still on the median:** Styphnolobium, the horse chestnut and Melia (all phases), and the leaf-out of Celtis and Tilia.
- **Checked:** the plane trees' pollen peaks in central Madrid were 29 March 2023 and 21 March 2024 (Ayuntamiento pollen report). The flowers come with the leaves, so a 2 April leaf-out is 4–11 days later, which is consistent.
- **Rejected:**
  - a 34–44° N latitude band, worldwide: it has more data but leafs out in late April to mid-May, biased by continental North America and China;
  - the genus Aesculus: in California it is the buckeye, which leafs out in February and drops its leaves in the summer drought (it gave colouring on 5 September).

## 2026-11-11: Madrid's own autumn colours

- **Decision:** measure the autumn colour of Platanus × hispanica (12 photos), Styphnolobium japonicum (16), Ulmus (6, *U. minor*), Celtis (7, *C. australis* and *C. occidentalis*) and Melia azedarach (5), and the summer colour of the purple-leaved plum (13). Commons photos were checked one by one on contact sheets, with Warsaw's pixel method (`scripts/foliage_measure.py`).
- **Result:** at the renderer's brightness, plane trees turn ochre (`#d3b159`), Styphnolobium bright yellow (`#ffe06e`), elms `#cfb770`, hackberries `#e8d073` and chinaberries `#d7be5d`. The purple plum's tint on the greens is ×(1.62, 0.60, 1.53).
- **Rejected:** *Ulmus pumila* and *Celtis australis* alone: Commons has almost no autumn canopies of them.

## 2026-11-11: Lawns from Sentinel-2: irrigated and dry

- **Decision:** lawn colours by month come from Copernicus Sentinel-2 L2A (2022–2024, 202 scenes with under 20 % cloud) over the lawns of the AOI (`scripts/lawns_s2.py`).
  - **Lawn pixels:** a 10 m pixel counts when at least 80 % of it is an OSM lawn, meadow, park or garden without a LiDAR tree or a building, and it is green in spring (NDVI ≥ 0.5).
  - **Dry:** July–August NDVI under 0.45 marks a dry meadow.
  - **Data:** 497 irrigated pixels and 94 dry ones (2 353 two-metre cells, mostly the slopes by the Templo de Debod). The dry ones are the high bit of `foliage.bin`'s class byte, and the viewer has a second monthly series for them.
- **Calibration:** surface reflectance is bluer and duller than a photo. So the satellite gives only the changes (per month, and dry against irrigated, per channel, relative to irrigated lawns in summer), applied to the summer lawn colour of the Commons photos. A class with under 50 pixels follows the irrigated one.
- **Result:** irrigated lawns are olive green all year, darker in winter; dry meadows are green from November to April and straw-coloured (`#d3c580`) in July and August.
- **Rejected:**
  - whole parks without the spring-green test: their paths and sand made a "dry" class that was never green;
  - lawn polygons alone: 98 pixels, and one dry;
  - the reflectance as colour directly: grey-green lawns.

## 2026-11-11: Fernandino street lamps, in voxels

- **Decision:** draw Madrid's street lamps as voxel shapes, with no viewer change: the user did not want the viewer changed only for the lamps.
  - **Fernandino:** a base, a dark green cast-iron shaft, the lantern and a cap. This is the default, at 4 m in squares and pedestrian streets and 5 m in other streets.
  - **Two arms:** a column with one lantern on each side, along the kerb, on avenues or where OSM has `light:count` ≥ 2.
  - **Bent mast:** the lantern over the road, for OSM `lamp_mount=bent_mast`.
  - **Wall:** a lantern on the facade with no post, for OSM `support=wall_mounted` (431 nodes, which used to become posts at the kerb).
- **Why:** the shader already lights every `lamp` voxel at night and pools light under each `meta.lamps` entry, so the shapes light up as they are. The OSM tags say which lamps hang on walls and which masts bend.
- **Limits:**
  - at 1 m a lantern is about twice its real size;
  - the base cannot be wider than the shaft (3 × 3 m would be too big);
  - lanterns inside a crown stay hidden.
- **Rejected:** an instanced mesh in the viewer (base, shaft, glass lantern and crown, like the pedestrians). It would be finer, but it would change the viewer only for the lamps.

## 2026-11-11: Catastro ATOM file for the squares the WFS cannot serve

- **Decision:** when the WFS fails on a tile even at 31 m, read that tile's features from Catastro's ATOM file for the municipality. The file is `A.ES.SDGC.BU.28900.zip`, 117 MB, downloaded once to the cache. Four squares near Calle de Toledo get their 21 building parts and floors this way.
- **Why:** those records make every WFS query that touches them fail, on every retry. The ATOM file is the same Catastro data, and the only other way to get them.
- **Against rule 4 (downloads limited to the AOI):** the ATOM file covers the whole municipality, but it is the smallest unit Catastro offers. It is downloaded only when a tile was skipped, and only the skipped squares are read from it.

## 2026-11-11: Touch controls and gamepad support

- **Decision:**
  - **Touch:** an on-screen stick to walk and three buttons for what has no gesture (down to the street, jump, back up), drawn only on touch screens, with a gesture hint shown once per mode. The bird's-eye gestures stay as they were: they are the usual map gestures.
  - **Gamepad:** the browser's Gamepad API in the standard layout. Left stick moves (also sideways), right stick looks, the triggers rise and sink in the air (RT runs on foot), A goes down to the street or jumps, B flies back up, LB / RB move the hour.
  - **One input:** keys, stick and gamepad feed the same axes (`web/src/nav/input.ts`), so `nav.ts` has one code path for all three.
- **Why:** on a phone there was no way back up from the street except a search, going down needed a zoom gesture nobody would guess, and walking was tap by tap only. The keys were on/off, so nothing analogue could plug in.
- **Rejected:**
  - `nipplejs` for the stick: a dependency for about 40 lines of Pointer Events;
  - looking around with the phone's gyroscope: it needs a permission prompt on iOS and makes people dizzy;
  - new bird's-eye gestures.


## 2026-11-11: MIT licence for the Madrid code

- **Decision:** the code written for the Madrid port is under the MIT licence (`LICENSE`), the same as both upstream projects, whose licences stay in `LICENSE-warsaw-vibe-voxel` and `LICENSE-dtla-voxel`.
- **Why:** the repository is about to be public; without a licence the code could be read but not reused. MIT matches the code it builds on, so the whole viewer and pipeline share one set of terms.
- **Scope:** code only. The generated data in `web/public/data` derives from OpenStreetMap (ODbL), IGN/CNIG and the Ayuntamiento de Madrid (CC BY 4.0), Catastro and Wikidata (CC0), and keeps their terms (`README.md`, "Sources").
- **Rejected:** a copyleft licence (GPL), which would put stricter terms on this code than on the code it is adapted from.

## 2026-11-13: World's tile cache per finest-tile footprint

- **Decision:** `World.node()` keeps one cache slot per 128 m cell (the footprint of a 1 m tile), holding the finest tile loaded there or none. The whole cache is cleared when the streamer's version changes. The code is adapted from dtla-voxel (commits `1034c95`, `98283fe`).
- **Why:** the old single slot let an 8 m clay node answer queries inside a loaded 1 m tile, so the walker got stuck at random (`NOTES.md`, "Walking and collision").
- **Rejected:**
  - caching only nodes of the finest level, dtla-voxel's first fix: every query on clay would scan the levels again;
  - collision changes in `nav.ts` (depenetration, substeps) before measuring whether the walker still gets stuck once the cache is right.

## 2026-11-13: The walker waits for the full detail

- **Decision:**
  - A walking step is allowed only where the 1 m tile and its column data are loaded. Until it arrives, the walker stops at the border of the missing tile.
  - The detail within 150 m of the walker is kept pinned.
  - A walker found inside something solid is moved to the nearest spot within 6 m that fits.
- **Why:** the 8 m clay is a wall in some places and open in others. Where it was open, a walker crossed into a tile still loading and could end up inside a lamp or a kiosk when it arrived, stuck for good.
- **Rejected:**
  - **Walking on terrain only where detail is missing:** it lets the walker into buildings that then load around them.
  - **Clay as collision until the tile loads (as before):** it stops the walker at invisible walls in some places and lets them through in others.
  - **Splitting steps at low frame rates:** a separate problem, left for when it shows.

## 2026-11-13: Coloured clay, camera-aware blocks and the slider as a ceiling

- **Decision:**
  - **Clay colour:** the 8 m clay is drawn in its own palette colours, 30 % desaturated, not flat grey.
  - **Block choice:** the 1 m budget goes first to the blocks within 150 m of the focus, then to the blocks in view, nearest the camera and the focus first.
  - **Slider:** the Render size slider sets a ceiling and no longer switches the adapting off. `?level=` fixes the level.
  - **Light post-processing:** below level 0.4, ambient occlusion and the depth blur are off.
- **Why:**
  - From high up on slow devices the city looked white.
  - Oblique views spent their budget behind the camera, and showed clay in the foreground.
  - A visitor who raised the slider on a slow machine stayed at a few frames per second.
  - Post-processing is about half the frame on an integrated GPU.
- **Cost:** the coloured clay runs the full surface shader; at the overview that costs about 8 % on the UHD 620.
- **Rejected:**
  - **2 m and 4 m tile levels (dtla-voxel):** a large change, which Warsaw removed and the 2026-11-11 entry already turned down. Coloured clay was tried first.
  - **Ordering by projected size alone:** the overview would have put its detail at the near edge of the map instead of where the visitor looks.
  - **Dropping bloom and SMAA too:** they are cheap next to N8AO and the depth blur.

## 2026-11-13: Shadow biases from the texel, smaller at low sun

- **Decision:** the sun's normal and depth biases are sized from the shadow map's texel, capped at 0.25 m and 0.15 m and scaled by the sun's elevation (dtla-voxel `6fd3b9d`). The extra for staircase walls is a ×3 multiplier instead of +1.2 m.
- **Why:** Warsaw's normal offset grew to 3 m at low sun, which detached golden-hour shadows from their casters.
- **Rejected:** keeping a fixed floor of 0.5 m: it was the floor itself that showed as a gap at street level.

## 2026-11-13: The sun follows true north and Madrid's calendar

- **Decision:** the sun's bearing includes the UTM meridian convergence (-0.45°), its light uses the true elevation, the sky's light follows the azimuth, and the date is Madrid's (dtla-voxel `cf1c7e1`).
- **Why:** small but free corrections. Shadows pointed half a degree off, the sunset light stayed 2.5° up after the sun had gone down, and a visitor in another time zone could see "today" as the wrong day.
- **Rejected:** a full ellipsoidal convergence formula: the spherical one agrees with pyproj to within 0.0001° here.

## 2026-11-13: Fewer allocations per frame

- **Decision:** reuse arrays, objects and grids in the voxel queries, the street-life tick and the label placement, guided by a heap-sampling profile (`web/tools/allocs.mjs`). This halved the garbage per second.
- **Why:** garbage-collection pauses cost frames on phones, and the changes are local.
- **Rejected:** rewriting `carObstacle` without closures: it is Warsaw's traffic logic, and the gain (about 3.5 MB/s) did not justify the risk.

## 2026-11-13: Content-hashed data files in the build

- **Decision:** the build copies each data file under a name made from its content hash and lists the names in `meta.json`; the viewer keeps hashed files from the browser cache without asking again (dtla-voxel `3e77ad7`).
- **Why:** GitHub Pages cannot be told to cache tiles for long; repeated visits revalidated every tile, and redeploys could invalidate unchanged ones.
- **Rejected:**
  - **dtla's `_headers` and Cloudflare deployment:** GitHub Pages ignores the file.
  - **Dropping the plain copies to halve the upload:** tabs left open across a deploy would fail to load tiles.

## 2026-11-13: Re-mesh tiles after a lost WebGL context

- **Decision:** on a lost WebGL context each tile mesh is emptied, and on restore it is meshed again from its (cached) file, keeping the same mesh object.
- **Why:** the viewer went black for good when a phone dropped the context, because tile arrays are released after upload.
- **Rejected:**
  - **Keeping the arrays:** costs memory all the time for a rare event.
  - **Dropping and reloading every tile through `city.ts`:** more state to rebuild, and tiles would pop in as clay first.

## 2026-11-13: No paced GPU uploads

- **Decision:** new tiles still reach the GPU the frame they are first shown.
- **Why:** dtla-voxel's pacing (upload in a hidden draw, a few MB per frame) was implemented and measured on a flight through the views: frame times did not improve (66 frames over 100 ms against 55-62 without), and tiles appeared later.
- **Rejected:** keeping it for phones without a measurement there.

## 2026-11-13: The Sierra de Guadarrama in the sky

- **Decision:** a skyline profile baked from the IGN's MDT200 is drawn by the sky shader (dtla-voxel `9eeb73e`).
- **Why:** from mid-height views the horizon was empty; Madrid's own horizon is the Sierra. The profile costs 64 kB and one texture read.
- **Rejected:**
  - **Copernicus GLO-90:** another agency and licence, where the IGN offers the same coverage with an automatable WCS.
  - **The MDT25 or MDT05:** at 20-120 km a 200 m cell is under a pixel.
  - **Terrain geometry beyond the map:** far more cost for a band a few pixels tall.

