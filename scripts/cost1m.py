"""What full 1 m detail costs, tile by tile: mesh every level-1 tile once in the viewer and record its triangles, GPU
bytes and column-data bytes -> {AREA}/cost1m.json.

zones.py shares each tile's triangles among the city blocks over it; the viewer spends its triangle budget on the blocks
nearest the focus and draws the rest as 8 m clay (web/src/city.ts). Without this table every block costs nothing and a
phone loads the whole map at 1 m. Port of warsaw-vibe-voxel's web/tools/cost1m.mjs to the Python harness of
scripts/screenshot.py. Run after voxelize.py (the viewer must serve the area's tiles), then re-run zones.py.

usage: PYTHONPATH=scripts uv run python scripts/cost1m.py
"""
import json

from playwright.sync_api import sync_playwright

from aoi import AREA
from screenshot import CHROMIUM, CHROMIUM_ARGS, is_up, start_server

URL = "http://localhost:5173/"
MESH_ALL = """async () => {
  const S = window.__streamer, d = S.dims[1], rows = [];
  S.update = () => {};  // freeze the streamer: we drive it
  for (let ty = 0; ty < d.ny; ty++) {
    const ps = [];
    for (let tx = 0; tx < d.nx; tx++) ps.push(S.request(1, tx, ty, 1e9, true));
    S.pump(); await Promise.all(ps);
    for (let tx = 0; tx < d.nx; tx++) {
      const n = S.nodes.get(S.key(1, tx, ty));
      const dataB = n.data ? n.data.counts.byteLength + n.data.ground.byteLength + n.data.runs.byteLength + n.data.off.byteLength : 0;
      const geo = n.mesh?.geometry, tris = geo ? geo.drawRange.count / 3 : 0;
      const bytes = geo ? Object.values(geo.attributes).reduce((a, at) => a + at.array.byteLength, 0) : 0;
      rows.push({ tx, ty, tris, bytes, dataB });
      S.free(n);
    }
  }
  return { rows };
}"""


def main():
    server = None if is_up(URL) else start_server(URL)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=CHROMIUM, args=CHROMIUM_ARGS)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(URL + "?ui=0")
            page.wait_for_function("window.__ready === true", timeout=300_000)
            res = page.evaluate(MESH_ALL)
            browser.close()
    finally:
        if server:
            server.terminate()
    out = AREA / "cost1m.json"
    out.write_text(json.dumps(res))
    rows = res["rows"]
    print(f"{len(rows)} tiles, {sum(r['tris'] for r in rows) / 1e6:.1f} M triangles, "
          f"{sum(r['bytes'] for r in rows) / 2 ** 20:.0f} MB GPU, {sum(r['dataB'] for r in rows) / 2 ** 20:.0f} MB column data -> {out}")


if __name__ == "__main__":
    main()
