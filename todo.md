# To do

What is left after phases 0–6. Each item says why it is pending and where to start. The reasons behind what was done are in `DECISIONS.md`, the measurements in `NOTES.md`.

## Needs the user

- **Publish the site** (Phase 6, "check that the published site loads correctly"). Everything is ready but nothing has been pushed. With the GitHub CLI logged in:

  ```sh
  gh repo create agboyano/madrid-voxel --public --source . --remote origin
  gh api -X POST repos/agboyano/madrid-voxel/pages -f build_type=workflow   # Pages from GitHub Actions
  git push -u origin main                                                    # runs .github/workflows/pages.yml
  gh run watch                                                               # then open https://agboyano.github.io/madrid-voxel/
  ```

  Then check that the site loads: the map, the labels, a card, and the views (`?view=palace`). Pages needs a public repository on a free account; the repository is 32 MB of data plus the screenshots.

- **Review the labels.** `docs/labels.md` lists all 422: 10 required, 412 extended by rule. Drop unwanted ones by adding their Wikidata id to `EXTENDED_EXCLUDE` in `scripts/labels.py`, and log it. This review was planned for Checkpoint 4. Since the labels take the Spanish name from OSM and the English one from Wikidata, check pairs that name different things: an OSM building whose `wikidata` tag points to a body housed in it ("Ministerio de Sanidad, Servicios Sociales e Igualdad" over "Spanish Agency for Consumer Affairs, Food Security and Nutrition"). Fix the OSM tag, or drop the English name for that item.
- **A licence for this project's own code.** The upstream code is MIT (`LICENSE-warsaw-vibe-voxel`, `LICENSE-dtla-voxel`); the Madrid changes have no licence file yet.

## Landmarks and look

- **Curate the required landmarks** with `scripts/overrides.json` (wall and roof colours, facade zones) and the helpers in `landmarks.py` (`classic_rebuild`, `ortho_roof`, `_onion`, `edge_windows`) and `monuments.py`:
  - the Royal Palace (its parts take generic brick and render: it is white stone and granite);
  - the Metrópolis (slate dome, gilded statue);
  - the Puerta de Alcalá and the Cibeles fountain (sculptures, as monuments);
  - the Palacio de Cristal (glass) and the Almudena.
- **Tree crowns too low.** Foliage reaches down to 2 m, and at a crown's rim to 1 m under its LiDAR top, so leaves hang at pedestrians' heads over pavements and roads (`voxelize.py`: the 2 m floor of `crown_bot` and the per-trunk dome, whose underside rises to `crown_top - 1` at the rim). Fix: a clearance by the ground under the crown, higher over roads than over pavements, and no thin fringe of leaves at head height.
- **Label kinds:** some read oddly. Cibeles and the Metrópolis come out as "attraction" (OSM `tourism=attraction`), the Royal Palace as "castle" (`historic=castle`). Prefer the Wikidata type when the OSM kind is generic.
- **Street lamps** are Warsaw's 1 × 1 columns 10 m high, heavy at street level. Madrid's lamps are lower and ornate (the "fernandino" model in the historic centre).
- **Madrid de los Austrias:** `landmarks.HISTORIC_CORE` was traced roughly. Trace it on the orthophoto or take an official barrio boundary.
- **Orthophoto:** the PNOA orthophoto is from July 2023 and not a true orthophoto. Evaluate the Ayuntamiento's Geoportal orthophoto (newer, possibly true ortho) in `fetch_ortho.py`.

## Seasons, weather and life

- **Phenology:** Platanus, Styphnolobium, Aesculus, Celtis, Melia and Tilia had too few iNaturalist annotations in Spain, Portugal and Italy and fall back to the median. Find a better source (PEP725, Spanish phenological networks) or widen the region for those genera. Prunus colouring on 13 December is suspicious (cherry laurel, an evergreen, is in the genus).
- **Autumn colours** exist only where Warsaw measured the genus. Platanus, Styphnolobium, Ulmus and Celtis use the median; measure them on Commons photos (`scripts/foliage_photos.json`).
- **Lawns, lit windows and traffic** still use Warsaw's measurements: monthly lawn colours, night photos of Warsaw facades, signal timings and bike weights. Measure Madrid's (Commons photos, Madrid's bike counts).

## Pipeline and viewer

- **Overview view:** it frames about 2.5 km around the map's centre, so the eastern extension (Doctor Esquerdo) is out of the first view. Frame the whole map, or add a view of the east.
- **Construction sites** were not reviewed one by one at full scale (OSM `landuse=construction`, buildings finished after the 2024 flight).
- **Catastro:** four 31 m squares of building parts near Calle de Toledo are skipped because the WFS fails on it (`skipped` in `building_parts.geojson`). Retry later or take it from the ATOM download.
- **Vegetation masks and deck heights** are still computed in `voxelize.py` between 3D writes. Move them into `layers.py` to complete the 2D/3D split.
- **`VOXEL_SIZE`:** the viewer does not read `meta.voxel` yet. The "1 m assumptions" section of `NOTES.md` lists what would have to change for another voxel size.
- **Desktop performance on integrated GPUs:** post-processing is about half the frame time (5.4 fps for the whole map at full render size on an Intel UHD 620). A lighter post-processing level for weak GPUs would help.
- **`web/tools/*.mjs`** (Node harnesses inherited from Warsaw) still hold Warsaw camera poses and macOS (Metal) flags. The Python `scripts/screenshot.py`, `profile.py` and `cost1m.py` replace the ones used here.
- **Published site:** once published, check it after each data change. The workflow deploys `web/dist` on every push to `main`.

## Future (PLAN.md Phase 7)

- **Municipal 2026 flight** (30 pts/m², 7 cm imagery), once on the Geoportal: a `fetch_` script, an entry in `SOURCES` in `prep_lidar.py` with its class table, and `resolution` 0.5 or 0.25 in `pipeline.toml`.
- **PNOA-LiDAR NPC03** for Madrid, once published: the same files with better classification. Put them in `raw/pnoa_lidar/` and change the source's file pattern.
