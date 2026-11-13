"""Rendering profile of the viewer: frame rate, GPU load and memory per view, and what shadows and post-processing cost.

Adapted in spirit from dtla-voxel's profiling harness (web/tools/profile.mjs, docs/rendering-profile.html: same views,
toggles one at a time) on this viewer's own hooks (window.__three, window.__streamer). For each view the viewer loads
at the fixed Render size (as scripts/screenshot.py), then over SECONDS it measures:
  fps            frames per second (requestAnimationFrame count)
  triangles      triangles drawn per frame, draw calls
  gpu            geometries and textures held by the renderer (three.js renderer.info.memory)
  heap           JS heap in use (Chromium's performance.memory), MB
  tiles          tile nodes loaded by the streamer, level 1 and level 8
and repeats with shadows off (no light casts) and with post-processing off (the composer bypassed). A phone profile
(--phone) emulates a 390 x 844 screen at device pixel ratio 3 with touch, as Playwright's iPhone 13.

Output: a table on stdout and docs/profile.json (append --out to change).

usage: uv run python scripts/profile.py [--views overview,sol,top] [--phone] [--seconds 8] [--level 1] [--query trunks=0]

--level fixes the Render size (?level=; default 1, the whole city at 1 m; lower levels draw the rest as 8 m clay).
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from screenshot import CHROMIUM, CHROMIUM_ARGS, ROOT, is_up, start_server, wait_idle

MEASURE = """async (seconds) => {
  const t = window.__three, r = t.renderer;
  let frames = 0, tris = 0, calls = 0, run = true;
  const tick = () => { if (!run) return; frames++; tris += r.info.render.triangles; calls += r.info.render.calls; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  await new Promise((ok) => setTimeout(ok, seconds * 1000));
  run = false;
  const nodes = [...window.__streamer.nodes.values()];
  return { fps: +(frames / seconds).toFixed(1), triangles: Math.round(tris / Math.max(frames, 1)),
    calls: Math.round(calls / Math.max(frames, 1)), geometries: r.info.memory.geometries, textures: r.info.memory.textures,
    heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
    tiles_1: nodes.filter((n) => n.s === 1).length, tiles_8: nodes.filter((n) => n.s === 8).length };
}"""
NO_SHADOWS = """() => { const t = window.__three; t.scene.traverse((o) => { if (o.isLight) o.castShadow = false; });
  t.renderer.shadowMap.autoUpdate = false; }"""
NO_POST = """() => { const t = window.__three; t.post.composer.render = () => t.renderer.render(t.scene, t.camera); }"""


def profile(url, views, seconds, phone, level, query=""):
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM, args=CHROMIUM_ARGS)
        ctx = browser.new_context(**(p.devices["iPhone 13"] if phone else {"viewport": {"width": 1600, "height": 1000}}))
        for view in views:
            for variant, patch in (("baseline", None), ("no shadows", NO_SHADOWS), ("no post", NO_POST)):
                page = ctx.new_page()
                # a phone keeps the viewer's own budget (0.75 M triangles at most)
                date = "" if "date=" in query else "&date=6-15"  # --query may set its own date
                page.goto(f"{url}?view={view}{date}&hour=11" + ("" if phone else f"&level={level:g}") + (f"&{query}" if query else ""))
                page.wait_for_function("window.__ready === true", timeout=300_000)
                wait_idle(page, 300)
                if patch:
                    page.evaluate(patch)
                page.wait_for_timeout(1500)
                m = page.evaluate(MEASURE, seconds)
                rows.append(dict(view=view, variant=variant, phone=phone, level=level, query=query, **m))
                print(f"{view:10s} {variant:11s} fps {m['fps']:5.1f}  tris {m['triangles'] / 1e6:5.2f} M  calls {m['calls']:5d}  "
                      f"geo {m['geometries']:5d}  tex {m['textures']:3d}  heap {m['heap_mb']} MB  "
                      f"tiles {m['tiles_1']}+{m['tiles_8']}", flush=True)
                page.close()
        browser.close()
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--views", default="overview,sol,top")
    ap.add_argument("--seconds", type=float, default=8)
    ap.add_argument("--phone", action="store_true")
    ap.add_argument("--level", type=float, default=1.0, help="Render size, 0-1 (ignored with --phone)")
    ap.add_argument("--url", default="http://localhost:5173/")
    ap.add_argument("--query", default="", help="extra raw query string, e.g. 'trunks=0'")
    ap.add_argument("--out", default=str(ROOT / "docs" / "profile.json"))
    args = ap.parse_args()
    server = None if is_up(args.url) else start_server(args.url)
    try:
        rows = profile(args.url, args.views.split(","), args.seconds, args.phone, args.level, args.query)
    finally:
        if server:
            server.terminate()
    out = Path(args.out)
    old = json.loads(out.read_text()) if out.exists() else {"runs": []}
    old["runs"].append(dict(when=time.strftime("%Y-%m-%d %H:%M"), gpu="headless Chromium, ANGLE Vulkan", rows=rows))
    out.write_text(json.dumps(old, indent=1))
    print("->", out, file=sys.stderr)


if __name__ == "__main__":
    main()
