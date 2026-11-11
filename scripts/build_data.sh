#!/bin/sh
# Madrid data pipeline: downloads (cached in $MADRID_CACHE) -> rasters -> fusion -> web/public/data.
# The PNOA-LiDAR tiles are downloaded by hand (fetch_pnoa_lidar.py prints which and where).
set -e
cd "$(dirname "$0")/.."
# each step's wall time and peak memory go to stderr ("MEASURE ...")
run() { PYTHONPATH=scripts uv run python scripts/measure.py "scripts/$1.py"; }
run fetch_osm
run fetch_wikidata   # landmark facts through the OSM wikidata tags
run fetch_trees
run fetch_catastro
run fetch_ortho
run fetch_pnoa_lidar
run prep_lidar      # point cloud -> $MADRID_CACHE/areas/<key>/elevation_<source>.npz
run prep            # -> areas/<key>/prep.npz (DSM, DTM, ortho, classes on the grid)
run climate         # -> web/public/data/climate.json (Open-Meteo, once)
run voxelize        # -> tiles, meta.json, trees.json, traffic.json, areas/<key>/ground.npz
run terrain
run zones           # blocks, unpriced: the viewer needs every file on the new grid before cost1m can load it
run windows
run window_stats
run places
run phenology       # seasonal cycle and foliage.bin, from trees.json
run cost1m          # triangles per tile (meshed in the viewer), for zones.py's block budget
run zones           # again, with the blocks priced
run labels_doc      # docs/labels.md, the label list for review
