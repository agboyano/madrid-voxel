#!/bin/sh
# Madrid data pipeline: downloads (cached in $MADRID_CACHE) -> rasters -> fusion -> web/public/data.
# The PNOA-LiDAR tiles are downloaded by hand (fetch_pnoa_lidar.py prints which and where).
set -e
cd "$(dirname "$0")/.."
run() { PYTHONPATH=scripts uv run python "scripts/$1.py"; }
run fetch_osm
run fetch_trees
run fetch_catastro
run fetch_ortho
run fetch_pnoa_lidar
run prep_lidar      # point cloud -> $MADRID_CACHE/work/elevation_<source>.npz
run prep            # -> data/prep.npz (DSM, DTM, ortho, classes on the grid)
run climate         # -> web/public/data/climate.json (Open-Meteo, once)
run voxelize        # -> tiles, meta.json, trees.json, traffic.json, data/ground.npz
run terrain
run zones
run windows
run window_stats
run places
