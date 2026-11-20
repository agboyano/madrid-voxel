"""Where the ground under the roads steps, and where bridge decks cross over each other: the measurement that decides
whether Portland's road levelling and decks drawn per way (from portland-voxel, commits 69c55f9 and 07c6500) are worth
porting. Builds the layers (as voxelize.py does) and prints:

- ground steps of 2 m or more along the carriageways on the ground (road_level.steps), the worst ways by name and
  grid position;
- pairs of bridge ways that cross without sharing a node, with their OSM layers and the deck height each has a little
  way off the crossing (the DSM's 30th percentile along it), flagged where the two stand 4 m or more apart: the case
  where today's one-height-per-cell deck loses the lower one.

    PYTHONPATH=scripts uv run python scripts/deck_road_report.py
"""
import numpy as np

import layers
import road_level
from aoi import VOXEL_SIZE
from layers import on_bridge, tunnelish

STACKED = 4.0  # m between two crossing decks from which one stands over the other
OFF = (8.0, 30.0)  # m from the crossing along each way where its own deck height is read


def deck_height(line, at, dsm_mean, D, W):
    """the deck's height (m) along line between OFF[0] and OFF[1] metres either side of the point at"""
    s0 = line.project(at)
    hs = []
    for d in np.arange(OFF[0], OFF[1], VOXEL_SIZE):
        for s in (s0 - d / VOXEL_SIZE, s0 + d / VOXEL_SIZE):
            if 0 <= s <= line.length:
                x, y = line.interpolate(s).coords[0]
                r, c = int(y), int(x)
                if 0 <= r < D and 0 <= c < W:
                    hs.append(dsm_mean[r, c])
    return float(np.percentile(hs, 30)) if hs else float("nan")


def main():
    L = layers.build()
    g, osm, dsm_mean = L["g"], L["osm"], L["dsm_mean"]
    D, W = g.shape
    names = {oid: t.get("name", "") for oid, t, _ in osm.lines}

    ways = L["road_ways"]
    each = road_level.steps_per_way(g, ways)
    total = sum(each)
    print(f"ground carriageways: {len(ways)}; ground steps of {road_level.STEP:g} m+ along them: {total}")
    worst = sorted(range(len(ways)), key=lambda i: -each[i])[:15]
    for i in worst:
        if not each[i]:
            break
        line, _, _, oid = ways[i]
        x, y = line.interpolate(0.5, normalized=True).coords[0]
        print(f"  {each[i]:3d} steps  way {oid} {names.get(oid, '')!r}  {line.length:.0f} m  at x {x:.0f} y {y:.0f}")
    dtm_jumps = 0
    for line, *_ in ways:
        P = road_level.samples(line)
        h = L["dtm"][np.clip(P[:, 1].astype(int), 0, D - 1), np.clip(P[:, 0].astype(int), 0, W - 1)]
        dtm_jumps += bool((np.abs(np.diff(h)) >= road_level.JUMP).any())
    print(f"carriageways whose DTM jumps {road_level.JUMP} m+ between neighbouring samples: {dtm_jumps}")

    bridges = [(oid, t, line) for oid, t, line in osm.lines
               if on_bridge(t) and not tunnelish(t) and (t.get("highway") or t.get("railway"))]
    print(f"\nbridge ways: {len(bridges)}")
    pairs = []
    for i, (oa, ta, la) in enumerate(bridges):
        ends_a = {la.coords[0], la.coords[-1]}
        for ob, tb, lb in bridges[i + 1:]:
            if not la.intersects(lb):
                continue
            x = la.intersection(lb)
            pts = [x] if x.geom_type == "Point" else list(getattr(x, "geoms", []))
            pts = [p for p in pts if p.geom_type == "Point" and p.coords[0] not in ends_a | {lb.coords[0], lb.coords[-1]}]
            if not pts:
                continue  # joined end to end, or overlapping along a stretch: one deck
            p = pts[0]
            ha, hb = deck_height(la, p, dsm_mean, D, W), deck_height(lb, p, dsm_mean, D, W)
            pairs.append((abs(ha - hb), oa, ta, ob, tb, p, ha, hb))
    pairs.sort(key=lambda q: -np.nan_to_num(q[0]))
    stacked = [q for q in pairs if q[0] >= STACKED]
    print(f"bridge ways crossing without a shared node: {len(pairs)}; {STACKED:g} m+ apart: {len(stacked)}")
    for dh, oa, ta, ob, tb, p, ha, hb in pairs[:20]:
        print(f"  {dh:5.1f} m  {ta.get('name', ta.get('highway') or ta.get('railway'))!r} (layer {ta.get('layer', '1')}, "
              f"{ha:.1f} m) x {tb.get('name', tb.get('highway') or tb.get('railway'))!r} (layer {tb.get('layer', '1')}, "
              f"{hb:.1f} m)  at x {p.x:.0f} y {p.y:.0f}  ways {oa} {ob}")


if __name__ == "__main__":
    main()
