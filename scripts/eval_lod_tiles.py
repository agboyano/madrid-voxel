"""Technique 1, stage A (docs/renderer-evaluation-plan.md): 2 m and 4 m tiles for an offline count, not for the viewer.

Rebuilds the 1 m volume from the published level-1 tiles (tiles/1 with tiles/1f's crowns and grass laid over it) and
writes levels 2, 4 and 8 with tiles.py's own export and downsample, so they are what the pipeline would write. Level 8
is written again only to check the rebuild against the published clay. What the rebuild lacks: tree trunks (in neither
level-1 file; the clay keeps them) and the clock faces' block colouring (face_ids come from voxelize.py's palette).

Output goes to a directory outside the repository (default $MADRID_CACHE/eval/lod), never to web/public/data.

usage: PYTHONPATH=scripts uv run python scripts/eval_lod_tiles.py [out dir]
"""
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np

import tiles

DATA = Path(__file__).resolve().parent.parent / "web" / "public" / "data"


def read_node(path, N):
    """Node file -> (counts (N+2)^2, ground (N+2)^2, runs (n, 3))."""
    with gzip.GzipFile(path, "rb") as fh:
        b = fh.read()
    n2 = (N + 2) ** 2
    counts = np.frombuffer(b, np.uint16, n2)
    ground = np.frombuffer(b, np.uint8, n2, offset=2 * n2)
    runs = np.frombuffer(b, np.uint16, offset=3 * n2).reshape(-1, 3)
    return counts, ground, runs


def lay(vol, g, path, tx, ty, N):
    """Write a level-1 node's own cells (apron left out) into vol (H, D, W) and its ground into g; empty cells kept."""
    if not path.exists():
        return
    counts, ground, runs = read_node(path, N)
    H, D, W = vol.shape
    rows = np.arange(N + 2)[:, None] + ty * N - 1
    cols = np.arange(N + 2)[None, :] + tx * N - 1
    core = np.zeros((N + 2, N + 2), bool)
    core[1:N + 1, 1:N + 1] = True
    core &= (rows >= 0) & (rows < D) & (cols >= 0) & (cols < W)
    if g is not None:
        gr, gc = np.broadcast_to(rows, core.shape)[core], np.broadcast_to(cols, core.shape)[core]
        g[gr, gc] = ground.reshape(N + 2, N + 2)[core]
    if not len(runs):
        return
    col = np.repeat(np.arange(counts.size), counts.astype(np.int64))  # column of each run
    lens = runs[:, 1].astype(np.int64)
    k = core.ravel()[col] & (lens > 0)
    col, run = col[k], runs[k]
    lens = run[:, 1].astype(np.int64)
    ri = np.repeat(np.arange(len(run)), lens)
    z = run[ri, 0].astype(np.int64) + np.arange(lens.sum()) - np.repeat(np.cumsum(lens) - lens, lens)
    c = col[ri]
    keep = z < H
    vol[z[keep], (c[keep] // (N + 2)) + ty * N - 1, (c[keep] % (N + 2)) + tx * N - 1] = run[ri[keep], 2]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("MADRID_CACHE", Path.home() / "data/madrid-voxel-cache")) / "eval" / "lod"
    meta = json.loads((DATA / "meta.json").read_text())
    N, W, D, H = meta["tiles"]["N"], meta["W"], meta["D"], meta["H"]
    l1 = next(l for l in meta["tiles"]["levels"] if l["s"] == 1)
    vol = np.zeros((H, D, W), np.uint16)
    g = np.zeros((D, W), np.uint8)
    for ty in range(l1["ny"]):
        for tx in range(l1["nx"]):
            lay(vol, g, DATA / "tiles" / "1" / f"{tx}_{ty}.bin", tx, ty, N)
            lay(vol, None, DATA / "tiles" / "1f" / f"{tx}_{ty}.bin", tx, ty, N)  # crowns and grass over the bare earth
        print(f"row {ty + 1}/{l1['ny']}", flush=True)
    tiles.LEVELS = (2, 4, 8)
    info = tiles.export(vol, g, out, print)
    (out / "levels.json").write_text(json.dumps(info))


if __name__ == "__main__":
    main()
