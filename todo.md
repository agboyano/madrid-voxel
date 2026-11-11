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

- **Review the labels.** `docs/labels.md` lists all 422: 10 required, 412 extended by rule. Drop unwanted ones by adding their Wikidata id to `EXTENDED_EXCLUDE` in `scripts/labels.py`, and log it. This review was planned for Checkpoint 4. Since the labels take the Spanish name from OSM and the English one from Wikidata, pairs that name different things lose the English line (no word in common between the OSM name and Wikidata's Spanish label: 26 at the last build, such as "IED Madrid" over "Palace of Altamira"). Where the OSM `wikidata` tag is simply wrong (the Ministerio de Sanidad building points to a body housed in it), fix the tag in OSM.
- **A licence for this project's own code.** The upstream code is MIT (`LICENSE-warsaw-vibe-voxel`, `LICENSE-dtla-voxel`); the Madrid changes have no licence file yet.

## Landmarks and look

- **Curate the required landmarks** with `scripts/overrides.json` (wall and roof colours, facade zones) and the helpers in `landmarks.py` (`classic_rebuild`, `ortho_roof`, `_onion`, `edge_windows`) and `monuments.py`:
  - the Royal Palace (its parts take generic brick and render: it is white stone and granite);
  - the Metrópolis (slate dome, gilded statue);
  - the Puerta de Alcalá and the Cibeles fountain (sculptures, as monuments);
  - the Palacio de Cristal (glass) and the Almudena.
- **"Fernandino" street lamps** (postponed by the user). The heights are Madrid's now (8 / 5 / 4 m by street), but every lamp is still a plain 1 × 1 column with one lit voxel. At 1 m a voxel cannot draw a slender cast-iron post with its lantern. Two ways:
  - **Viewer model (preferred):** drop the lamp voxels and draw an instanced mesh at each of `meta.lamps`, like the pedestrians and cars (`web/src/sim/meshes.ts`): a base, a dark green iron shaft, a glass lantern lit at night, and a crown. The fernandino with one lantern goes in squares and pedestrian streets, the column with two arms on avenues. Keep `meta.lamps` for the light pools (`voxelMaterial.ts`).
  - **Voxels only:** dark base, shaft, lit lantern and a cap, with a 1-voxel arm on avenues. Simpler, but still blocks.
- **Madrid de los Austrias:** `landmarks.HISTORIC_CORE` was traced roughly. Trace it on the orthophoto or take an official barrio boundary.
- **Orthophoto:** the PNOA orthophoto is from July 2023 and not a true orthophoto. Evaluate the Ayuntamiento's Geoportal orthophoto (newer, possibly true ortho) in `fetch_ortho.py`.

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
- **Lit windows and traffic** still use Warsaw's measurements: night photos of Warsaw facades, signal timings and bike weights. Measure Madrid's (`docs/seasons-and-life-sources.md` §5–6).

## Pipeline and viewer

- **Construction sites** were not reviewed one by one at full scale (OSM `landuse=construction`, buildings finished after the 2024 flight).
- **Catastro:** four 31 m squares of building parts near Calle de Toledo are skipped because the WFS fails on them (`skipped` in `building_parts.geojson`). Retried on 2026-11-11 with the same result, so the records themselves seem to break the service: take them from the ATOM download.
- **Vegetation masks and deck heights** are still computed in `voxelize.py` between 3D writes. Move them into `layers.py` to complete the 2D/3D split.
- **`VOXEL_SIZE`:** the viewer does not read `meta.voxel` yet. The "1 m assumptions" section of `NOTES.md` lists what would have to change for another voxel size.
- **Desktop performance on integrated GPUs:** post-processing is about half the frame time (5.4 fps for the whole map at full render size on an Intel UHD 620). A lighter post-processing level for weak GPUs would help.
- **`web/tools/*.mjs`** (Node harnesses inherited from Warsaw) still hold Warsaw camera poses and macOS (Metal) flags. The Python `scripts/screenshot.py`, `profile.py` and `cost1m.py` replace the ones used here.
- **Published site:** once published, check it after each data change. The workflow deploys `web/dist` on every push to `main`.

## Future (PLAN.md Phase 7)

- **Municipal 2026 flight** (30 pts/m², 7 cm imagery), once on the Geoportal: a `fetch_` script, an entry in `SOURCES` in `prep_lidar.py` with its class table, and `resolution` 0.5 or 0.25 in `pipeline.toml`.
- **PNOA-LiDAR NPC03** for Madrid, once published: the same files with better classification. Put them in `raw/pnoa_lidar/` and change the source's file pattern.
