"""Capture the viewer in a headless browser and save a PNG in docs/img/.

Starts the Vite dev server if nothing is listening on --url, opens the
viewer with the requested view parameters, waits until the tile streamer
is idle and saves a screenshot.

    uv run python scripts/screenshot.py overview --view overview
    uv run python scripts/screenshot.py sol --cam 100,80,300,0,20,0 --hour 18 --date 5-15
    uv run python scripts/screenshot.py street --view zlota --weather rain --ui 0

View parameters map one-to-one to the viewer's URL query (web/src/main.ts):
view, cam (px,py,pz,tx,ty,tz in voxel coordinates), hour, date (M-D),
weather, ui and tilt. --query appends any other raw query string.

--level fixes the viewer's "Render size" (0 to 1) through its ?level= query,
which also stops the viewer adapting it. The viewer otherwise lowers it on slow
GPUs and draws distant blocks as 8 m clay, so a fixed level keeps screenshots
comparable across machines.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT_DIR = ROOT / "docs" / "img"
VIEW_PARAMS = ("view", "cam", "hour", "date", "weather", "ui", "tilt")
# A system Chromium avoids downloading Playwright's bundled build; override with $CHROMIUM.
CHROMIUM = os.environ.get("CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
# Render WebGL on the real GPU through ANGLE's Vulkan backend; headless Chromium otherwise falls back to SwiftShader
# (as it now does with --use-angle=gl, at about 1 fps).
CHROMIUM_ARGS = ["--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"]


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def start_server(url: str) -> subprocess.Popen:
    port = urllib.parse.urlparse(url).port or 5173
    cmd = ["npx", "-y", "pnpm@12.11.2", "exec", "vite", "--port", str(port), "--strictPort"]
    proc = subprocess.Popen(cmd, cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if is_up(url):
            return proc
        time.sleep(0.5)
    proc.terminate()
    sys.exit(f"screenshot: the dev server did not start on {url}")


def build_query(args: argparse.Namespace) -> str:
    params = {k: getattr(args, k) for k in VIEW_PARAMS if getattr(args, k) is not None}
    query = urllib.parse.urlencode(params, safe=",")
    return "&".join(q for q in (query, args.query) if q)


STREAMER_IDLE = "window.__streamer.inflight === 0 && window.__streamer.queue.length === 0"


def wait_idle(page, timeout_s: int) -> None:
    try:
        page.wait_for_function(STREAMER_IDLE, timeout=timeout_s * 1000)
    except Exception:
        print("screenshot: streamer still busy, capturing anyway", file=sys.stderr)


def capture(url: str, out: Path, width: int, height: int, timeout_s: int, settle_ms: int,
            click: str | None = None) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM, args=CHROMIUM_ARGS)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.on("pageerror", lambda e: print("[pageerror]", e, file=sys.stderr))
        page.on("console", lambda m: m.type == "error" and print("[console]", m.text[:300], file=sys.stderr))
        t0 = time.monotonic()
        page.goto(url)
        page.wait_for_function("window.__ready === true", timeout=timeout_s * 1000)
        page.wait_for_function("!document.body.classList.contains('loading')", timeout=timeout_s * 1000)
        wait_idle(page, timeout_s)
        page.wait_for_timeout(settle_ms)
        if click:  # a landmark's label, by its shown name: selects it and opens its info card
            # (labels move every frame, so Playwright never finds them "stable": the event is sent directly)
            page.locator("#labels .txt", has=page.locator("b", has_text=click)).first.dispatch_event("click")
            page.wait_for_timeout(2500)
            wait_idle(page, timeout_s)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        print(f"{out.relative_to(ROOT)} ({time.monotonic() - t0:.1f} s)")
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="output file name in docs/img/, without extension")
    for k in VIEW_PARAMS:
        ap.add_argument(f"--{k}")
    ap.add_argument("--query", default="", help="extra raw query string, e.g. 'stats=0'")
    ap.add_argument("--url", default="http://localhost:5173/")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--timeout", type=int, default=180, help="seconds to wait for the viewer")
    ap.add_argument("--level", type=float, default=1.0, help="Render size, 0-1 (negative: leave it adaptive)")
    ap.add_argument("--click", help="click the label with this name (opens its info card) before capturing")
    ap.add_argument("--settle", type=int, default=2500, help="milliseconds to wait after loading")
    args = ap.parse_args()

    server = None if is_up(args.url) else start_server(args.url)
    try:
        query = build_query(args) + ("" if args.level < 0 else f"&level={args.level:g}")
        capture(f"{args.url}?{query}", OUT_DIR / f"{args.name}.png",
                args.width, args.height, args.timeout, args.settle, args.click)
    finally:
        if server:
            server.terminate()


if __name__ == "__main__":
    main()
