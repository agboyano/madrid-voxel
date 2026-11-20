# To do

What is left after phases 0–6. Each item says why it is pending and where to start. The reasons behind what was done are in `DECISIONS.md`, the measurements in `NOTES.md`.

## Needs the user

- **Review the labels.** `docs/labels.md` lists all 422: 10 required, 412 extended by rule. Drop unwanted ones by adding their Wikidata id to `EXTENDED_EXCLUDE` in `scripts/labels.py`, and log it. This review was planned for Checkpoint 4. Since the labels take the Spanish name from OSM and the English one from Wikidata, pairs that name different things lose the English line (no word in common between the OSM name and Wikidata's Spanish label: 26 at the last build, such as "IED Madrid" over "Palace of Altamira"). Where the OSM `wikidata` tag is simply wrong (the Ministerio de Sanidad building points to a body housed in it), fix the tag in OSM.

## Landmarks and look

- **Required landmarks, two passes done** (`landmarks.details_geometry`, `monuments.MONUMENTS`; first pass in `docs/img/lm-before-*.png` and `lm-after-*.png`, second in `lm2-*.png`; `DECISIONS.md`, 2026-11-15). The Puerta de Alcalá, the Cibeles group and the Metrópolis's Victory are measured on photographs; the brick course at the foot of the Royal Palace's courtyards is gone. Still rough:
  - At 1 m the sculpture is placed and sized, not modelled: Cibeles's lions and goddess, and the Puerta de Alcalá's groups, are blocks of a few voxels.
  - The Royal Palace's courtyard facades have no windows (`edge_windows` paints only the outer edges).
  - `scripts/patch.py alcala palace almudena metropolis cristal monuments` redoes them in about 3 min after a full build with `LMCACHE=1`.

## Seasons, weather and life

- **Leaf dates still on the median** (needs the user: an account). Even with every Mediterranean-climate region, iNaturalist has too few leaf annotations for:
  - Styphnolobium (8 620 trees);
  - the horse chestnut (6 444) and the chinaberry (491);
  - the leaf-out of Celtis and Tilia.

  The way to measure them in Madrid itself is Copernicus **HR-VPP**: start and end of season per 10 m pixel, 2017 onwards. It needs a free account:
  1. Register at https://www.wekeo.eu/ (or the Copernicus Land Monitoring Service).
  2. In the WEkEO data viewer, find the HR-VPP "Vegetation Phenology and Productivity parameters" (VPP) dataset.
  3. Select Sentinel-2 tile **30TVK**, years 2017–2024, season 1, the layers **SOSD**, **EOSD** and **QFLAG**.
  4. Download the GeoTIFFs to `$MADRID_CACHE/raw/hrvpp/`, without renaming them.

  Then `phenology.py` can take, per genus, the pixel medians over single-genus street alignments of the inventory (the method in `docs/seasons-and-life-sources.md`, §1).
- **PEP725 / AEMET** phenological series are given on request: https://pep725.eu/dataset/ (non-commercial use; cite Templ et al. 2018) and AEMET's climatological data bank. Useful for Aesculus and Tilia.
- **Autumn colours with small samples:** Melia (5 photos), Ulmus (6, of *Ulmus minor*: Commons had no autumn canopies of *U. pumila*), Celtis (7, mixing *C. australis* and *C. occidentalis*). The horse chestnut keeps Warsaw's measurement (Central Europe). More photos would steady them: iNaturalist research-grade photos from the Madrid region, October to December.
- **Flowering:** almonds and the purple plum blossom white and pink in February and March; the viewer has no flowering phase.

## Street lamps

The lamps come from the Ayuntamiento's inventory and the viewer draws them (`scripts/lamps.py`, `scripts/lampmap.py`, `web/src/lamps.ts`; `DECISIONS.md`, 2026-11-15). Left from checkpoint C:
- **Checks not run yet:**
  - `web/tools/abdiff.mjs` by day, to confirm that only the lamps changed in the rebuilt tiles;
  - the balance of street light and lit windows against the night photos (`web/tools/photoshot.mjs`, `scripts/window_photos.json`);
  - screenshots at the blue hour, and with `--cam` in Salamanca (only the Retiro has one: `docs/img/lampmap-retiro.png`).
- **Modern luminaires barely show:** their heads (0.25 × 0.14 × 0.65 m) are small and seen from below; at night they read as a thin line. Try a larger head or a brighter lantern colour for `MODERN` in `lamps.ts` (`LANTERN`, `HEAD`).
- **A lantern at head height in Sol** (`docs/img/lamps-after-street.png`, in front of the Carlos III statue): its post stands below the square, probably a lamp of a sunken level whose `z` is that level's ground. Find it in `lamps.bin` and decide from the ground under it.
- **The Retiro reads greenish in the overview:** the average of its lit paths over the lawns. Park lanterns are at 0.35 of a street lantern (`PARK` in `lampmap.py`); lower it, or light only the paths, if it should be darker.
- **`lampmap.bin` is 1.6 MB**, against the 0.3–0.6 MB estimated in the plan. It loads after the first frame. A PNG of the light plane would be about 1.1 MB, decoded off the main thread.
- **GPU memory is computed, not measured:** `web/tools/mem.mjs` changes by tens of MB between runs (its 4 s wait catches the tiles mid-stream), so the saving (16.7 MB canvas → 6.3 MB map + 1.7 MB lamp buffers) comes from the texture and buffer sizes.
- **Heights are assumptions:** the inventory has none (`STYLE_HEIGHT`, `WALL_HEIGHT` in `lamps.py`). Replace them if the Ayuntamiento's luminaire catalogue gives heights by model.
- **Lamps on bridge decks get no light on the ground:** the map has one level (40 on the Viaducto de Segovia).

## Pipeline and viewer

- **Construction sites** were not reviewed one by one at full scale (OSM `landuse=construction`, buildings finished after the 2024 flight).
- **`VOXEL_SIZE` other than 1 m:** the viewer reads `meta.voxel` and refuses data built at another size (`web/src/main.ts`, `boot`; `docs/img/voxel-size-refused.png`). Drawing them is a separate project, as `PLAN.md` says for 0.5 m: the "1 m assumptions" section of `NOTES.md` lists what would have to change (tile format, mesher, ground bytes, terrain steps).
- **Desktop performance on integrated GPUs (Intel UHD 620),** where the adaptive render level settles at 0.15–0.3. The 5.4 fps first written here was the whole map at full render size, before the work below, and has not been measured again. Done since (`DECISIONS.md`, 2026-11-13 and 14):
  - **Post-processing:** N8AO is off below level 0.4, fades out between 3.5 and 5.5 km of camera distance, and no longer renders the scene twice more for transparent materials (`docs/n8ao-evaluation.md`).
  - **Sun's shadow map:** redrawn far less often while moving, in flights and in hour drags (`docs/renderer-evaluation-plan.md`).
  - **Street life:** only the instances in use are sent to the GPU, and the population is 0.7 on desktop and 0.5 on phones (`docs/sim-evaluation-plan.md`).
  - **Still open:** a far-field occlusion term (technique 3 of `docs/renderer-evaluation-plan.md`); the cheaper agents' shadow map and 20 Hz logic (C3 and C8 of `docs/sim-evaluation-plan.md`), not evaluated.
- **Touch and gamepad controls on real devices.** They were tested in headless Chromium with an emulated phone and a fake gamepad (`NOTES.md`, "Viewer: touch and gamepad controls"). The stick now works on a real phone in portrait and landscape. Still to check: the other mobile browser (iOS Safari or Android Chrome, whichever was not tested), and whether the pad shows over plain HTTP on the local network (a real Xbox controller works).
- **Published site:** once published, check it after each data change. The workflow deploys `web/dist` on every push to `main`.

## Road tunnels

The road tunnels are carved and driven (`scripts/tunnels.py`; `DECISIONS.md` and `NOTES.md`, 2026-11-20). Left:
- **Looking inside:** the viewer lifts the camera to the ground stored in the tiles, the street over a tunnel. Walking or following a car into a tunnel needs the camera's ground to know the bores (the floor raster `tunnels.FLOOR` could be exported beside the tiles).
- **Not carved:** car-park ramps and aisles (service ways), tunnels with one portal in the map (Francisco Silvela, Paseo de la Virgen del Puerto), Calle 30, the metro and the railway.
- **Screenshots of the other portals** (Bailén, Atocha, Plaza Mayor): the cameras tried so far did not face a portal.

## Future (PLAN.md Phase 7)

- **Municipal 2026 flight** (30 pts/m², 7 cm imagery), once on the Geoportal: a `fetch_` script, an entry in `SOURCES` in `prep_lidar.py` with its class table, and `resolution` 0.5 or 0.25 in `pipeline.toml`.
- **PNOA-LiDAR NPC03** for Madrid, once published: the same files with better classification. Put them in `raw/pnoa_lidar/` and change the source's file pattern.
