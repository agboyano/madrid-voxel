# What changed from Warsaw, and what was taken from dtla-voxel

Madrid in voxels started from a snapshot of [warsaw-vibe-voxel](https://github.com/stared/warsaw-vibe-voxel) and took pieces from [dtla-voxel](https://github.com/sigman78/dtla-voxel) (snapshot `90bc1a6`, 2026-11-06). This document sums up how the pipeline and the viewer differ from Warsaw's, and how each technique of dtla-voxel was weighed. It is a map of decisions taken elsewhere, not a new record.

Each line cites its source:
- **D** is `DECISIONS.md`, by the date and title of the entry.
- **N** is `NOTES.md`, by section.
- **REP** is `docs/renderer-evaluation-plan.md`.
- **N8** is `docs/n8ao-evaluation.md`.

Timings come from the development laptop, an Intel UHD 620 with Chromium on Vulkan. Nothing was measured on a real phone or a dedicated GPU.

## Summary

| Area | Warsaw | Madrid |
| --- | --- | --- |
| Elevation | GUGiK DSM and DTM rasters, no point classes | the classified PNOA-LiDAR point cloud, rasterised straight onto the grid, through a common format any later flight can feed |
| Buildings | OSM | OSM footprints, LiDAR heights, Catastro floors and the buildings OSM lacks |
| Trees | three Warsaw databases | the municipal inventory with girths, OSM, and LiDAR-only crowns; trunks drawn at their measured width, bare limbs in winter |
| Seasons | Central European dates | dates from Mediterranean-climate regions, Madrid's own autumn colours, lawns from Sentinel-2 |
| Labels | name search, pageviews and about 150 hand picks | only through OSM's `wikidata` tag, chosen by rule; cards with facts written at build time |
| Streaming | blocks by distance to the focus, grey clay | blocks in view first, coloured clay, the adapted level remembered, no bare ground while trees load |
| Lighting | shadow redraws every 300 ms of block swaps, N8AO on or off by level | redraws limited while moving, sun at true north, N8AO fading with distance and its absence made up in tone |
| Input | mouse and keyboard | adds touch controls and a gamepad |
| Delivery | data revalidated by the browser | content-hashed data files, cached for good |
| Build | 26 GB peak, 55 MB of data, part of it run by hand | 15.9 GB peak, 32 MB of data, one timed script |

## Data pipeline and architecture

- **One elevation source.**
  - Warsaw read finished GUGiK rasters (0.5 m DSM, 1 m DTM).
  - Madrid rasterises the classified PNOA-LiDAR NPC02 cloud straight onto its rotated grid (`scripts/prep_lidar.py`), at 1 m, because the cloud has 5.9 own points/m².
  - Overlap points (class 12, 42 % of the points) are used for heights.
  - The 72 % of cells with no ground point are filled by a multi-scale push-pull.
  - Sources: D 2026-11-11 "Intermediate elevation rasters at 1 m", "Overlap points (class 12)", "Ground gaps by multi-scale fill".
- **A common elevation format.** Each source writes `elevation_<source>.npz`, named in a `SOURCES` table and chosen in `pipeline.toml` `[elevation]`. A 2026 municipal flight or the NPC03 cloud only needs a new adapter. Source: N "Common elevation format".
- **2D layers, then 3D.**
  - Warsaw's single `voxelize.py` (2 051 lines) is split into `layers.py` (2D fusion, dtla-voxel's structure) and `voxelize.py` (3D).
  - The split was checked to be byte-identical to the old code.
  - The palette has its own module (`palette.py`), and builds log through `buildlog.py`.
  - Source: D 2026-11-11 "Reuse Warsaw's fusion, reorganised into layers".
- **Grid rotation.** Warsaw's grid turns 21.5° to follow the Palace of Culture. Madrid's turns −6° to follow the Ensanche: 25 % of facade length lies within 3° of the grid, against 9.8 % at 0° (`scripts/rotation_report.py`). Source: D 2026-11-11 "Full area extended east to Doctor Esquerdo, grid at −6°".
- **Buildings.**
  - OSM footprints take LiDAR heights.
  - Where OSM has no height, Catastro's floor count gives one (3.2 m a floor).
  - Catastro also adds the buildings OSM lacks: footprints agree at IoU 0.957, 8 459 features take Catastro floors and 108 buildings are added.
  - Catastro comes in 500 m WFS tiles on a shared grid, split down to 60 m on failure, with the ATOM file for four squares where the service fails.
  - Sources: D 2026-11-11 "Building footprints from OSM, floors from Catastro", "Catastro tiles on a shared world grid", "Catastro ATOM file…".
- **Downloads by area.**
  - OSM comes from Overpass in tiles of at most about 1.5 km, cached per tile (dtla-voxel's `fetch_osm.py`). Warsaw cut a daily Geofabrik extract with osmium.
  - The orthophoto comes from the IGN WMS, so a new rotation needs no new download.
  - The PNOA-LiDAR is downloaded by hand behind a reCAPTCHA; `fetch_pnoa_lidar.py` lists and checks the tiles.
  - Sources: N "`fetch_*.py`"; D 2026-11-10 "Orthophoto from the IGN PNOA WMS", "PNOA-LiDAR downloaded by hand".
- **Named areas and caches.** `pipeline.toml` holds several areas (`full`, `sol` and rotation tests), each cached under its centre, size and rotation; `MADRID_AREA` overrides it. Warsaw had one fixed area and fixed file names. Source: D 2026-11-11 "Areas and caches per AOI".
- **The whole build in one script.** Warsaw's `build_data.sh` ran 6 steps and left 9 to be run by hand. Madrid's runs every step, with each step's time and peak memory, in an order that rebuilds a changed area correctly. Sources: N "Execution order"; D 2026-11-11 "Build order…".
- **Block costs in the build.**
  - Warsaw priced its city blocks by hand.
  - Madrid runs `scripts/cost1m.py` in the build. Without it every block cost nothing, and an emulated phone loaded all 1 320 tiles (0.8–1.3 GB of heap) instead of 88–110 (about 200 MB).
  - Source: D 2026-11-11 "Price the city blocks".
- **Memory and size.** Peak memory falls from about 26 GB to 15.9 GB, and the data from 55 MB to 32 MB, for 12.5 km². Sources: warsaw-vibe-voxel README; N "Extended area at −6°".
- **Trees.**
  - Warsaw merged three Warsaw sources.
  - Madrid merges the municipal inventory (48 048 trees with species, height and girth), OSM within 2 m (3 224) and crowns seen only in the LiDAR (7 297).
  - Crowns clear 6 m over roads, 4.5 m over pavements and 3 m over lawns: columns with leaves under 3 m fell from 34.3 % to 1.5 %.
  - Sources: D 2026-11-10 "Whole-city download"; D 2026-11-11 "Crowns raised further".
- **Trunks at their measured width.**
  - Trunks are no longer 1 m voxel columns.
  - `scripts/trunks.py` writes a record per tree (`trunks.bin`, 660 kB), with the diameter from the inventory girth, or fitted to crown height where the girth is missing.
  - The viewer draws them as instanced boxes.
  - Source: D 2026-11-13 "Trunks at their inventory width, with bare limbs in winter".
- **Roofs and walls.**
  - Roofs are clay tile, slate, zinc or flat terrace, read from the orthophoto. About 40 % of the roofs round Sol read grey and are drawn as terraces.
  - Walls are Madrid render and brick, with a Madrid de los Austrias palette in the historic core.
  - Sources: D 2026-11-11 "Madrid roof materials from the ortho"; N "Palette".
- **Street lamps.**
  - Warsaw drew 1×1 columns and inferred some lamps.
  - Madrid takes OSM's lamps only (2 774) and draws four voxel shapes chosen from their tags: fernandino, wall, bent mast and two-arm.
  - Sources: D 2026-11-11 "Madrid street lamp heights", "Fernandino street lamps, in voxels".
- **Crossings** come from dtla-voxel's `road_markings.py`: 403 from crossing ways, 407 from nodes, and 114 ambiguous ones left unpainted. Source: D 2026-11-11 "Lamps from OSM, crossings from dtla-voxel…".
- **Bridges** add the LiDAR's bridge class (17) next to OSM bridge ways: 349 deck cells. Source: N "Defects reviewed at scale".
- **Labels by Wikidata id only.**
  - 1 292 OSM elements with a `wikidata` tag give 1 118 items. Ten are required by id, and the rest are chosen by rule from the number of Wikipedia editions.
  - The result is 422 labels, in Spanish first with English under it.
  - Warsaw searched by name and box, ranked by pageviews and kept about 150 hand picks.
  - Sources: D 2026-11-11 "Required landmarks by Wikidata id", "Extended label set by rule", "Labels in Spanish…".
- **Seasons for Madrid.**
  - Leaf dates come from iNaturalist in 14 Mediterranean-climate regions: plane trees leaf out on 2 April and colour on 18 November, checked against pollen peaks.
  - Autumn colours for Madrid's own species are measured from Commons photos.
  - Lawns change month by month as measured by Sentinel-2 (202 scenes), with a dry-meadow class that turns straw in July and August.
  - Sources: D 2026-11-11 "Leaf dates from Mediterranean-climate regions", "Madrid's own autumn colours", "Lawns from Sentinel-2".
- **The Sierra de Guadarrama** is baked into a 64 kB skyline from the IGN's MDT200 (`scripts/horizon.py`). Source: D 2026-11-13 "The Sierra de Guadarrama in the sky".
- **Content-hashed data.**
  - The build copies each data file under a hash of its content and lists it in `meta.json`. The viewer fetches those with `force-cache`.
  - GitHub Pages revalidates after 10 minutes; now a second visit requests no tile.
  - Source: D 2026-11-13 "Content-hashed data files".
- **Site and voxel size in the data.** `meta.json` carries `voxel` and `lonlat`, where Warsaw hard-coded its latitude in `sun.ts`. Source: N "Madrid code and VOXEL_SIZE".

## Viewer: rendering and streaming

- **Coloured clay, chosen by what is in view.**
  - The 8 m clay takes palette colours, 30 % desaturated, where Warsaw's was flat grey and read white from above. It costs about 8 % in the overview.
  - Blocks within 150 m of the focus are real first, then blocks in view, by camera and focus distance. Warsaw went by focus distance only.
  - Source: D 2026-11-13 "Coloured clay…".
- **The slider is a ceiling.**
  - In Warsaw moving the render-size slider stopped the adapting. Here it sets the most the level may grow to, and the panel says when the size was lowered.
  - The adapted level is kept in the browser: a simulated slow device restarted at 0.32 instead of 0.75.
  - Sources: same; D 2026-11-13 "Blocks turn real with their trees; the level is remembered".
- **No bare ground while trees load.** A block coming back from clay waits for its foliage tiles before its clay is cut, also during the first load. Source: same entry.
- **One tile-cache slot per 128 m footprint** (dtla-voxel). Warsaw's single slot let an 8 m clay node answer inside a loaded 1 m tile: 163 wrong answers out of 163. Source: D 2026-11-13 "World's tile cache per finest-tile footprint".
- **Shadows.**
  - **Biases:** sized from the shadow map's texel and scaled by the sun's elevation (dtla-voxel `6fd3b9d`). Warsaw's 0.5–3 m offset detached golden-hour shadows.
  - **Sun position:** the sun follows true north (−0.45° meridian convergence), at its true elevation, on Madrid's calendar, and the sky's light turns with it (dtla-voxel `cf1c7e1`).
  - **Redraws for block swaps:** the sun's map follows them at most every 1.5 s while the camera moves (Warsaw: every 300 ms). Rotating 47° now redraws it 5 times instead of 16–19, and a stale map differs in at most 0.10 % of pixels.
  - Sources: D 2026-11-13 "Shadow biases from the texel", "The sun follows true north…"; D 2026-11-14 "The sun's shadow map follows block swaps…"; REP "Fewer redraws for block swaps".
- **N8AO graded.**
  - The screen-space occlusion fades out between 3.5 and 5.5 km of camera distance, where it adds almost nothing: the overview went from 98 to 88 ms at level 0.5.
  - Below level 0.4, where it is off, the sky's light is dimmed so the city keeps its tone: the step fell from 5–20/255 to 0–6/255.
  - Sources: D 2026-11-14 "N8AO fades out with camera distance…"; N8.
- **Fewer allocations.** Garbage per second halved (43.5 → 22.1 MB/s with the view still), from a column index kept in a field (dtla-voxel `98283fe`), reused sim grids and label buffers. Source: D 2026-11-13 "Fewer allocations per frame".
- **A lost WebGL context recovers.** Warsaw's page went black for good. Madrid re-meshes each tile from its cached file into the same mesh. Source: D 2026-11-13 "Re-mesh tiles after a lost WebGL context".
- **Trees.**
  - Trunks are instanced boxes per foliage tile. Limbs show only outside full leaf.
  - Bare crowns drop every leaf voxel; Warsaw kept 30 % as brown cubes.
  - Flights and clicks stop at tree crowns. Walking is unchanged.
  - Sources: D 2026-11-13 "Trunks…"; N "Flying into tree crowns".

## Viewer: features and UI

- **Landmark cards** (`web/src/card.ts`): year built, architect, height, style, heritage designation, website and Wikipedia, all written at build time. Warsaw opened the landmark's website. Source: PLAN Phase 4.
- **Touch controls** (`web/src/nav/touch.ts`): a stick, and *Walk here*, *Jump* and *Fly up* buttons, with gesture hints shown once. On a phone there had been no way back up from the street. Source: D 2026-11-11 "Touch controls and gamepad support".
- **Gamepad** in the standard layout, with its own legend. Keys, stick and pad feed one input (`web/src/nav/input.ts`). Source: same.
- **Search in Spanish:** "Search Madrid…", with Spanish kind names and action words (`scripts/places.py`, `web/src/bar.ts`).
- **Madrid's views** (nine, from the overview to Calle Mayor at street level), the overview framed to the map's width, and larger labels and controls on computer screens. Source: D 2026-11-11 "Overview frames the whole map".
- **Trains** carry Spanish liveries (Cercanías, Renfe and others) in `web/src/sim/trains.ts`.

## Tooling

- **Screenshots:** `scripts/screenshot.py` runs Playwright with the system Chromium on the GPU (ANGLE on Vulkan). Warsaw's `shot.mjs` used macOS Metal flags. Source: D 2026-11-10 "Screenshot harness…".
- **Profiles:** `scripts/profile.py` records fps, triangles, GPU memory, heap and tiles per view, with variants without shadows and without post-processing, and an emulated phone. Source: N "Rendering".
- **Harnesses in `web/tools/`:**
  - `passes.mjs`: GPU time of each pass through timer queries, with mean, p95, canvas and GPU.
  - `redraws.mjs`: how often the sun's shadow map is redrawn, and why.
  - `shadowswap.mjs`: what a stale shadow map looks like.
  - `mergekey.mjs`: what each field of the mesher's merge key costs in quads.
  - `uploads.mjs`, `allocs.mjs`, `ctxloss.mjs`, `walkstuck.mjs`.
  - `launch.mjs`: the shared Linux and Vulkan launcher.
- **Reports in the build:**
  - `scripts/lidar_report.py`: density, classes, NDVI.
  - `scripts/rotation_report.py`: facade angles.
  - `scripts/labels_doc.py`: `docs/labels.md`.
  - `scripts/measure.py`: time and memory per step.
- **No unit tests** in either project. The checks are scripted browser runs and screenshots.

### Evaluation switches

URL parameters for A/B measurements. None is on by default, and none is meant for visitors.

| Parameter | Effect | Default | Where |
| --- | --- | --- | --- |
| `level=0..1` | fixes the render size; nothing adapts it | adapts, from the remembered level | `web/src/main.ts` |
| `mountains=0` | no Sierra skyline | shown | `web/src/main.ts` |
| `trunks=0` | no instanced trunks and limbs | shown | `web/src/main.ts` |
| `trunkmin=<m>` | narrowest trunk drawn | 0.25 | `web/src/trunks.ts` |
| `stillmove=<ms>` | shortest gap between shadow redraws for block swaps while moving (300: as Warsaw) | 1500 | `web/src/main.ts` |
| `ao=merge` | meshes without per-vertex occlusion (technique 3 of REP) | off | `web/src/mesher.worker.ts` |
| `n8=on\|off` | forces N8AO on or off whatever the level | by level and distance | `web/src/post.ts` |
| `n8q=<mode>` | N8AO quality mode (`Performance`, `Low`, `Medium`, `High`, `Ultra`) | `Medium` | `web/src/post.ts` |
| `n8full=1` | N8AO at full resolution | half | `web/src/post.ts` |
| `n8up=0` | N8AO without depth-aware upsampling | on | `web/src/post.ts` |
| `n8fade=0` | no fade of N8AO with camera distance | fades 3.5–5.5 km | `web/src/post.ts` |
| `aotone=clear,cloudy` | how much the sky's light is dimmed when N8AO is off below level 0.4 (`1,1`: not at all) | `0.7,0.75` | `web/src/daylight.ts` |

## What Warsaw had that Madrid dropped or does not use

- **The Vistula flood slider** is gone from the viewer, since there is no river in the area. `scripts/flood.py` remains, unused. Source: D 2026-11-11 "Checkpoint 3…".
- **Trams.** Central Madrid has no tram, so the data has none (`traffic.json` and `meta.json` list 0 tram routes, against 67 and 101 in Warsaw). The tram simulation code in `web/src/sim` is still there and stays idle. The search no longer offers to follow one. Source: N "Warsaw code still present".
- **Hand curation of landmarks:** Warsaw's 64 building overrides, monuments and part parents, its pageview ranking, the Palace of Culture's floodlight and other Warsaw-only details. Madrid's curation is still to do (`todo.md`). Source: N "Warsaw code still present".
- **Analytics** (PostHog) and Warsaw's sharing image. Source: D 2026-11-11 "Remove the analytics library".
- **Still from Warsaw:**
  - the lit-window habits and the traffic model (signal timings, density through the day);
  - the parked-car step, which freezes the vehicles the LiDAR caught into the voxels.

  Sources: README "Known limitations"; `scripts/traffic.py`.

## Decisions against dtla-voxel

What dtla-voxel does or proposes, and what Madrid did with it. Of 24 items, 6 were adopted, 7 adapted, 7 turned down, and 4 evaluated with measurements.

| dtla-voxel | Madrid | Status | Why | Source |
| --- | --- | --- | --- | --- |
| `scripts/prep_lidar.py`: points straight into the rotated grid, reprojected from EPSG:3857, classes 2, 17 and 1, ground from USGS | same idea; no reprojection, the PNOA's own classes, overlap points for heights, ground from class 2 with a push-pull fill, a common elevation format | adapted | the PNOA cloud is already classified; one elevation source | D 2026-11-11 "Intermediate elevation rasters at 1 m"; N "Common elevation format" |
| `scripts/aoi.py` helpers (cache from the environment, corners, lon/lat box, grid transform) | merged into Warsaw's `aoi.py` under Warsaw's names | adapted | about 20 Warsaw modules import those names | N "Coordinate frame" |
| `fetch_osm.py` (Overpass in a 3×3 grid, cached per part); `fetch_lidar.py`, `fetch_naip.py` patterns | OSM downloader copied; retries and partial files reused for the PNOA check and the IGN orthophoto | adopted / adapted | download only the area; the LiDAR is behind a reCAPTCHA | N "`fetch_*.py`"; D 2026-11-10 "PNOA-LiDAR downloaded by hand" |
| `scripts/voxelize.py`: fill in 130-row bands, about 3–4 GB peak | Warsaw's whole-volume fill kept | rejected (twice) | 12.8 GB, then 15.9 GB after the eastern extension, fit on a 38 GB machine; bands would rewrite every whole-volume pass | D 2026-11-11 "No band fill, no 2 and 4 m tile levels" |
| `scripts/layers.py`: a dict of 2D layers read by the 3D fill | the structure, with Warsaw's rules; LA's class inference, palette and palms left out | adapted | Warsaw's zones, traffic, windows and foliage depend on its fusion | D 2026-11-11 "Reuse Warsaw's fusion, reorganised into layers" |
| Bridge decks from class 17 | class-17 cells next to OSM bridge ways added to Warsaw's decks (349 cells) | adapted | decks the OSM heights missed | N "Defects reviewed at scale" |
| `scripts/road_markings.py`: crossing bars along the traffic, ambiguous ones refused | copied; Warsaw's white lane markings kept instead of LA's double yellow | adopted | Spanish road markings | D 2026-11-11 "Lamps from OSM, crossings from dtla-voxel…" |
| Street lamps every 36 m along both kerbs | OSM's 2 774 lamps only, in four shapes | rejected | OSM maps them; 36 m would double them | same |
| Tree detection from NDVI and multiple returns | not used | rejected | 22 crowns without an inventory tree in the test area; NDVI is weak on a leaf-off flight | same; N "PNOA-LiDAR NPC02" |
| `scripts/tiles.py`: levels of 1, 2, 4 and 8 m, with a block of thin voxels | Warsaw's 1 and 8 m tiles kept | rejected | the tile format is fixed by the project's rules; no measured need | D 2026-11-10 "Keep Warsaw's `tiles.py`" |
| Mountain skyline from USGS 3DEP (`9eeb73e`) | the same from the IGN's MDT200 (`scripts/horizon.py`) | adapted | same agency, datum and licence as the PNOA | D 2026-11-13 "The Sierra de Guadarrama in the sky" |
| `.github/workflows/pages.yml` (`2888f5c`) | Warsaw's workflow with pnpm, analytics removed | adopted, with changes | the lockfile is pnpm's | N "Publication (Phase 6)" |
| Content-hashed data (`3e77ad7`, `version-data.mjs`) | hashed copies and `force-cache`; no Cloudflare `_headers`, plain copies kept | adapted | GitHub Pages ignores `_headers`; tabs open across a deploy | D 2026-11-13 "Content-hashed data files" |
| `web/tools/profile.mjs`, `docs/rendering-profile.html` | own `scripts/profile.py` and `web/tools/passes.mjs`, with per-pass timer queries as in `profile.mjs` | adapted | dtla's harness needs its own instrumented viewer and Windows paths | N "Rendering"; REP |
| Adaptive levels of detail (`tileSelection.ts`): 1/2/4/8 m tiles by projected size | the block and clay model kept, and improved (coloured clay, blocks in view first) | rejected (twice); staged evaluation planned, not run | a large viewer change for no measured need; +71 % data; no popping mitigation; at the adapted level the cost is per fragment | D 2026-11-11 "No band fill…"; D 2026-11-13 "Coloured clay…"; REP technique 1 |
| Coarser shadow geometry (`shadowTiles.ts`): 4 m tiles cast beyond 192 m | redraws for block swaps limited instead | evaluated; a cheaper fix adopted | 85–100 % of redraws while moving came from block swaps; dtla's 31 % was the whole frame with shadows redrawn every frame | REP technique 2; D 2026-11-14 "The sun's shadow map follows block swaps…" |
| AO out of the mesher's merge key (`bench-mesh-merging.mjs`: 20–29 % fewer quads on a sample) | measured on the whole city: −24.2 % triangles, frames 13–20 % faster in far views; but without per-vertex AO the far city reads flat, and N8AO cannot replace it there | evaluated; kept as `?ao=merge` only | fails the image check at level 0.3 | REP technique 3; N8 §6 |
| N8AO at half resolution, about 1 ms on a GTX 1080 Ti | 6–18 ms here (10–25 % of the frame); fades with distance, tone kept below level 0.4; cheaper quality modes turned down | evaluated; own grading adopted | cheaper modes save 2–4 %, under the 5 % bar | N8; D 2026-11-14 "N8AO fades out…" |
| Shadow biases from the texel, scaled by elevation (`6fd3b9d`) | adopted, with a ×3 factor on staircase walls | adopted | Warsaw's offsets detached golden-hour shadows | D 2026-11-13 "Shadow biases from the texel" |
| Sun at true north, true elevation, sky light turning with it (`cf1c7e1`) | adopted, with the spherical convergence formula | adopted | it agrees with pyproj to 0.0001° | D 2026-11-13 "The sun follows true north…" |
| One tile-cache slot per finest footprint (`1034c95`, `98283fe`) | adapted; dtla's first fix (finest nodes only) turned down | adapted | clay queries would scan the levels again | D 2026-11-13 "World's tile cache per finest-tile footprint" |
| Column index in a field instead of a returned pair (`98283fe`) | adopted, with reused grids and buffers | adopted | garbage per second halved | D 2026-11-13 "Fewer allocations per frame" |
| Paced GPU uploads (`1034c95`) | tried at 4 MB a frame and dropped | rejected after measuring | 66 frames over 100 ms against 55–62 without, and tiles shown later | D 2026-11-13 "No paced GPU uploads" |
| Lost WebGL context: geometry disposed, tiles reloaded (`1034c95`) | each mesh keeps its place and is re-meshed from the cached file | adapted | reloading through the city model would bring tiles back as clay first | D 2026-11-13 "Re-mesh tiles after a lost WebGL context" |

## Open items

`todo.md` lists what is left. On the rendering side, two follow-ups of these evaluations remain:

- **A far-field occlusion term.** Per-fragment occlusion, or a cheap darkening of gaps from the height data, would let the mesher drop per-vertex occlusion (−24 % triangles) without the far city reading flat (REP, technique 3; N8 §6).
- **Technique 1 stages A and B** (REP): 2 and 4 m tiles measured offline, then drawn at a fixed level, before any change to the block model.
