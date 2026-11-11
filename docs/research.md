# Madrid in voxels: prior research

*Working document, 10 November 2026*

## 1. Goal

Build an interactive 3D map of central Madrid in 1 m voxels, running in the browser, in the style of [Warsaw in voxels](https://p.migdal.pl/warsaw-vibe-voxel/) by Piotr Migdał, built from open data.

## 2. Reference project: Warsaw in voxels

- **Website:** https://p.migdal.pl/warsaw-vibe-voxel/
- **Code:** https://github.com/stared/warsaw-vibe-voxel
- **Licence:** MIT (© 2026 Piotr Migdał). The generated data derives from OpenStreetMap (ODbL) and GUGiK open data.
- **What it is:** a 3950 × 3150 m diorama of central Warsaw in 1 m voxels, anchored on the Palace of Culture spire and rotated 21.5° to align with the street grid (avoiding staircased façades).
- **Features:** date, time of day and weather changes; seasonal foliage; controllable pedestrians.

### Data sources it uses

| Source | Use |
| --- | --- |
| GUGiK NMPT 2025 (LiDAR surface model, 0.5 m raster) | Roof heights and shapes, tree crowns, vehicles |
| GUGiK orthophoto | Roof colours, green roofs, foliage tones |
| OpenStreetMap | Buildings, streets, pavements, tram tracks, etc. |
| Municipal tree inventory | Species of each tree, seasonal foliage |
| Wikidata | Place names and websites |

### Notable fusion rules

- For each building, the LiDAR height is compared with the OSM height. OSM wins where the LiDAR sees nothing tall (building completed after the flight); elsewhere the LiDAR wins.
- OSM trees with no LiDAR crown become young trees (planted after the flight).

### Architecture

- **Data pipeline (`scripts/`, Python):** run locally once; downloads, fuses, voxelises and generates tiles.
- **Viewer (`web/`, TypeScript + three.js):** static site. The city is a quadtree of tiles (`web/public/data/tiles/{1,2,4,8}/x_y.bin`, about 15 MB gzipped in total) of 128 × 128 cells of 1, 2, 4 or 8 m. It loads the whole map at 8 m and refines what is in view.

## 3. Data sources for Madrid

### 3.1 Ayuntamiento de Madrid Geoportal

- **Website:** https://geoportal.madrid.es
- Offers cartography, orthophotos, 3D building models, point clouds and a 3D viewer (digital twin), free to download (shp, dgn, dxf, dwg, ecw, jpg, kml, COG…).
- **DSM 2023:** digital surface model obtained by photogrammetric correlation (point cloud of 100 points/m²). 1 × 1 km tiles with a 10 cm grid in COG; 1 m mosaic.
  - Record: https://datos.gob.es/es/catalogo/l01280796-modelo-digital-de-superficies-mds-2023

### 3.2 Municipal 2026 flight (awaiting publication)

- **Flight dates:** 28 May to 29 June 2026 (announced on 14 July 2026).
- **Coverage:** 26,000 ha, the whole urban area.
- **Capture:** UltraCam Osprey 4.2 camera, 7 cm imagery, 7,225 nadir and 28,900 oblique images; LiDAR at 30 points/m².
- **Planned products:** new orthophoto, 3D point cloud, improved DTM, DSM and a continuous 3D mesh.
- **Publication:** through the Geoportal 3D viewer. **No date announced.** It is not confirmed whether the point cloud will be downloadable or only viewable.
- **Next flight of this kind:** 2028.
- Press release: https://diario.madrid.es/blog/notas-de-prensa/madrid-realiza-un-vuelo-fotogrametrico-pionero-para-actualizar-su-cartografia-y-utilizarlo-como-herramienta-estrategica-en-la-planificacion-urbana/

### 3.3 PNOA-LiDAR (IGN / CNIG)

- **Download:** Centro de Descargas del CNIG. Earlier coverages in 2 × 2 km LAZ files; the 3rd coverage in 1 × 1 km LAZ 1.4 files with RGB colour and near-infrared (RGBNir).
- **Licence:** CC BY 4.0.
- **3rd coverage status:** https://pnoa.ign.es/pnoa-lidar/tercera-cobertura

| Coverage | Years | Density | Vertical accuracy |
| --- | --- | --- | --- |
| 1st | 2008–2015 | 0.5 pts/m² | ~20 cm |
| 2nd | 2015–2021 | 0.5–4 pts/m² | ~15 cm |
| 3rd | 2022–2026 | 5 pts/m² (uniform) | ~10 cm |

**Comunidad de Madrid (IGN status table, September 2026):** 3rd coverage flown between March and May 2024; NPC02 cloud published; DTM/DSM v1 published (including a 0.5 m DSM); DTM/DSM v2 expected in the second half of 2026.

**Point cloud classification levels (3rd coverage):**

| Level | Description | Madrid |
| --- | --- | --- |
| NPC01 | Initial automatic classification, provisional | — |
| NPC02 | Classification with basic editing (minimum F-score 0.9; includes the bridge class, 17) | Published, **the one we will use** |
| NPC03 | Improved basic editing, more reliable | Not yet published |

### 3.4 Other sources

- **OpenStreetMap:** geometry and semantics (streets, pavements, parks, water, rail, building types). ODbL licence.
- **Catastro (INSPIRE):** building footprints with number of floors, more precise than OSM.
- **Municipal tree inventory:** Ayuntamiento open data portal (https://datos.madrid.es), with location and species.
- **Wikidata (CC0):** landmark names and facts (year, architect, height, style, heritage status, website). Linked through the `wikidata=Q…` tag that many OSM features carry, which is more reliable than matching by name.
- **Commercial (not recommended for this project):** Google Photorealistic 3D Tiles, paid models (CGTrader, etc.).

## 4. Elevation data comparison

| | DSM 2023 (Ayuntamiento) | PNOA-LiDAR 3rd cov. (NPC02) | 0.5 m DSM (IGN) | 2026 flight (Ayuntamiento) |
| --- | --- | --- | --- | --- |
| Type | Photogrammetric raster | Classified LiDAR cloud | Raster derived from the LiDAR | LiDAR cloud + 7 cm imagery |
| Density | 100 pts/m² | 5 pts/m² | 5 pts/m² (source) | 30 pts/m² |
| Published as | 10 cm (tiles), 1 m (mosaic) | 1 × 1 km LAZ | 0.5 m grid | Pending |
| Classification | No | Yes (includes bridges) | No | Probably yes |
| Infrared (NDVI) | No | Yes (RGBNir) | No | To be confirmed |
| Ground under trees | No | Yes (multiple returns) | No | Yes |
| Edges and roofs | Very detailed | Adequate | Adequate | Very good |
| Available | Yes | Yes (2024 flight) | Yes (v1; v2 expected) | No |

**Conclusions:**

- Density is not directly comparable: photogrammetry only sees visible surfaces and interpolates in shadows and vegetation; LiDAR measures directly and partly penetrates tree crowns.
- For 1 m voxels all sources have enough resolution. At 5 pts/m² there will be gaps in façades and thin elements; at 0.5–2 pts/m² cells would need filling.
- **Decision:** use PNOA-LiDAR NPC02 as the single source for elevation and classification, computing heights from the cloud itself. The IGN 0.5 m DSM is discarded because it derives from the same cloud and adds no new information. The Ayuntamiento DSM 2023 remains only as an optional test if roofs come out with many holes: it has sharper edges, but it is unclassified and comes from a flight on a different date (2023 versus 2024).
- **Raster resolution:** with ~5 pts/m², a 0.5 m cell holds about 1.25 points on average (roughly 30 % of cells empty), while a 1 m cell holds about 5 (under 1 % empty). The main raster resolution is therefore 1 m, configurable per source. NPC03 does not change this (same cloud, same density); the 2026 flight at 30 pts/m² would allow 0.5 m or even 0.25 m rasters.
- The 2026 flight will mainly bring better classification, better-defined trees and better colours.

## 5. Integration strategy

1. **Separate the source from the rest of the pipeline:** a first step turns any source into an intermediate format (classified cloud or height grid per class); voxelisation, colours, trees and rendering work only on that format.
2. **Start now, without waiting for the 2026 flight:** the hard part (voxelisation, materials, viewer) does not depend on the source.
3. **Use PNOA-LiDAR NPC02 as the single source:** it is the same kind of data the 2026 flight will provide (classified LiDAR cloud in LAZ), so switching later will mostly mean pointing at other files.
4. **Rasterise directly into the rotated grid** from the point cloud, avoiding double resampling.
5. **When the 2026 flight is published, the earlier data will no longer be needed:** it replaces it completely.

**Unknowns about the 2026 flight:** format and download availability; classification codes (possible equivalence table with PNOA); coordinate system (probably ETRS89 / UTM 30N).

To find out when the data is published: watch the Geoportal or contact the Ayuntamiento's Subdirección General de Innovación e Información Urbana.

## 6. Reusing the Warsaw code

- MIT licence: it can be copied, modified and published, keeping the copyright notice. The author explicitly encourages reuse.
- Attribute the data: OSM (ODbL), CNIG (CC BY 4.0), Ayuntamiento de Madrid (under its terms).

### Required changes

- **Elevation:** replace GUGiK's NMPT with heights computed from the PNOA-LiDAR NPC02 cloud.
- **Warsaw-specific code** (`voxelize.py` and others): `landmarks.py` with Warsaw OSM IDs, finding the Palace of Culture by name, Warsaw's tree register, the Vistula flood gauge and tram livery. Replace, simplify or remove.
- **Trees:** adapt to the Madrid inventory.
- **Framing:** choose a centre (for example, Puerta del Sol) and a rotation suited to the street grid.
- **Viewer:** reusable almost unchanged (tile streaming, rendering, weather, time of day).

### Voxel size

Both the Warsaw and Los Angeles viewers use 1 m as the finest level of the quadtree. Moving to 0.5 m voxels is conceivable (one more quadtree level, loaded only near the camera), but it would multiply finest-level data by up to 8, roughly quadruple visible faces, and touch many implicit 1 m assumptions (object scales, landmarks, height encoding, shadows). It also changes the diorama aesthetic. It only makes sense with denser data such as the 2026 flight. The plan keeps 1 m voxels, inventories the 1 m assumptions, and uses a `VOXEL_SIZE` constant in all new code.

## 7. Infrastructure

- **No backend or database needed:** the result is a static site (HTML, JS and binary tiles).
- **Development:** a local server is required (the project's own or `npx serve`); opening `index.html` via `file://` does not work because the browser blocks tile loading.
- **Hosting:** GitHub Pages, Netlify or Cloudflare Pages. Watch the size if the area grows a lot (Warsaw ≈ 15 MB, Los Angeles ≈ 19 MB).

## 8. Ports and similar projects

### Ports of the Warsaw engine

| City | Repository | Notes |
| --- | --- | --- |
| Warsaw (original) | https://github.com/stared/warsaw-vibe-voxel | Website: https://p.migdal.pl/warsaw-vibe-voxel/ |
| Los Angeles (downtown) | https://github.com/sigman78/dtla-voxel | Website: https://sigman78.github.io/dtla-voxel/ |
| Callosa de Segura | https://github.com/raulbr99/callosa-voxels | Uses PNOA-LiDAR 3rd coverage, MDT05 and Catastro; contains only the built site |
| Amsterdam | https://github.com/melvinwevers/amsterdam-voxel | Adds a year slider through the city's history |
| Genoa | https://github.com/zujk/genoa | Scaffold, not yet built; useful as a list of what needs changing |

### Other projects

- **VoxCity** (https://github.com/kunifujiwara/VoxCity): Python package that generates voxel models of anywhere from open data and simulates sunlight, sky view and microclimate. Scientific focus, not a diorama.
- **Real cities in Minecraft:** Denmark in Minecraft (2014) and Great Britain in Minecraft (Ordnance Survey, 2014); Arnis (OSM → Minecraft generator); Build The Earth (collaborative hand-built recreation).

## 9. Comparison: Warsaw vs. Los Angeles

| | Warsaw | Los Angeles |
| --- | --- | --- |
| Area | 3950 × 3150 m | 4200 × 3600 m |
| Grid rotation | 21.5° | 52° |
| Elevation | 0.5 m NMPT raster | Full EPT cloud (242 M points) + 1 m DEM |
| Colours | Orthophoto | NAIP 0.6 m (RGB + infrared) |
| Trees | Municipal inventory with species | LiDAR + NDVI + multiple returns; palms detected |
| Source classification | — | Ground and bridges only; the rest is inferred |
| Viewer | Date, time, weather, seasons, pedestrians | Time and date; traffic, metro and people on the roadmap |
| Landmarks | Labels and landmarks | Façades and roofs refined building by building |
| Documentation | Good | Excellent (steps, limits, resources, rendering profile) |
| Build resources | — | ~7 min, ~4 GB RAM, ~2.5 GB cache |
| Maturity | Original, reference for others | Small (20 commits), Windows-oriented paths |
| Tile format | Original | Identical to Warsaw |

### Pros and cons

**Warsaw**
- Pros: more complete and "alive"; its tree approach fits the Madrid inventory.
- Cons: code more tightly coupled to Warsaw, which needs cleaning up; it expects a surface raster, not a point cloud.

**Los Angeles**
- Pros: point cloud pipeline, ideal for PNOA-LiDAR; excellent documentation; downloads that read only the area needed; band-based voxelisation for large areas.
- Cons: small project, fewer viewer features, Windows paths to adjust.

## 10. Recommendation

**Recommended approach:** start from the original Warsaw project (viewer and tree handling) and, for the PNOA-LiDAR, take LA's point cloud pipeline (`prep_lidar.py`, area-limited downloads, band voxelisation). Since the PNOA cloud is already classified, LA's class inference is not needed. Both share the tile format, so combining them is viable.

The detailed, phased plan is in `PLAN.md`, and the working rules in `CLAUDE.md`.
