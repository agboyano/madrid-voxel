// What a sun shadow map left behind by block swaps looks like: turn the camera about 10 degrees (what a visitor turns in
// the 1.5 s main.ts lets swaps wait while moving) with ?stillmove=99999, so swaps never redraw the map during the turn,
// then freeze the loop and capture <out>-stale.png, redraw the map and capture <out>-fresh.png. Prints when the map was
// redrawn (the first swap after a still spell redraws at once) and how many shown tiles changed.
// usage: node tools/shadowswap.mjs <view> <level> <out prefix>      (dev server on :5173)
import { launch } from './launch.mjs';
const [view, level, out] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
await page.addInitScript(() => { const raf = window.requestAnimationFrame.bind(window); window.__pause = false;
  window.requestAnimationFrame = (cb) => raf((t) => (window.__pause ? window.requestAnimationFrame(cb) : cb(t))); });
await page.goto(`http://localhost:5173/?view=${view}&date=06-21&hour=17&weather=clear&level=${level}&stillmove=99999&ui=0`);
await page.waitForFunction(() => window.__ready && !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 500 });
await page.waitForFunction(() => { const s = window.__streamer, c = window.__three.city(); return s.inflight === 0 && s.queue.length === 0 && c.settled; }, null, { timeout: 900000, polling: 500 });
await page.waitForTimeout(3000);
await page.evaluate(() => { const d = window.__three.daylight, g = d.gate, f = g.onBeforeShadow; window.__n = 0; window.__t = []; const s = window.__streamer; window.__set = () => [...s.group.children].filter((m) => m.visible).map((m) => m.id); window.__set0 = window.__set();
  g.onBeforeShadow = function (a, b, c, cam, ...r) { if (cam === d.sun.shadow.camera) window.__n++, window.__t.push(performance.now()); return f.call(this, a, b, c, cam, ...r); }; });
const T0 = await page.evaluate(() => performance.now());
const cx = 800, cy = 500;
await page.mouse.move(cx - 60, cy); await page.mouse.down({ button: 'right' });
for (let i = -30; i < 30; i++) { await page.mouse.move(cx + i * 2, cy); await page.waitForTimeout(40); }
await page.mouse.up({ button: 'right' });
// let the controls' damping finish and the budget catch up, with the map still as it was before the turn
await page.waitForTimeout(150);
await page.evaluate(() => { window.__pause = true; });
await page.waitForTimeout(200);
console.log(await page.evaluate((T0) => { const a = new Set(window.__set0), b = window.__set(); return `redraws at ${window.__t.map((t) => ((t - T0) / 1000).toFixed(2)).join(',')} s; tiles shown +${b.filter((x) => !a.has(x)).length} -${[...a].filter((x) => !b.includes(x)).length}; az ${(Math.atan2(window.__three.camera.position.x - window.__three.controls.target.x, window.__three.camera.position.z - window.__three.controls.target.z) * 57.3).toFixed(0)}`; }, T0));
await page.screenshot({ path: `${out}-stale.png` });
await page.evaluate(() => { window.__three.daylight.redrawShadow(); window.__three.post.composer.render(); });
await page.screenshot({ path: `${out}-fresh.png` });
await browser.close();
