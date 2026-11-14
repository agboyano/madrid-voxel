// What the sun's frame held over a flight (main.ts FLY_HOLD) looks like: fly from <from> to <to>, slowed down to
// <ms>, freeze the loop at <fraction> of it and capture <out>-held.png, then fit the frame to the camera as it would be
// without the hold, redraw, and capture <out>-followed.png from the same pose.
// usage: node tools/flyshadow.mjs <from view> <to view> <fraction> <out prefix> [ms, default 8000] [query]   (dev server on :5173)
import { launch } from './launch.mjs';
const [from, to, fraction, out, ms = '8000', query = ''] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
await page.addInitScript(() => { const raf = window.requestAnimationFrame.bind(window); window.__pause = false;
  window.requestAnimationFrame = (cb) => raf((t) => (window.__pause ? window.requestAnimationFrame(cb) : cb(t))); });
await page.goto(`http://localhost:5173/?view=${from}&date=06-21&hour=17&weather=clear&ui=0${query ? `&${query}` : ''}`);
await page.waitForFunction(() => window.__ready && !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 500 });
await page.waitForFunction(() => { const s = window.__streamer, c = window.__three.city(); return s.inflight === 0 && s.queue.length === 0 && c.settled; }, null, { timeout: 900000, polling: 500 });
await page.waitForTimeout(3000);
const views = await page.evaluate(() => fetch('data/meta.json').then((r) => r.json()).then((m) => m.views));
await page.evaluate(([v, ms]) => window.__three.flyTo({ ...v, ms }), [views[to], +ms]);
await page.waitForTimeout(+fraction * +ms);
await page.evaluate(() => { window.__pause = true; });
await page.waitForTimeout(300);
const pose = () => page.evaluate(() => { const T = window.__three, c = T.camera.position, t = T.controls.target; return `camera ${c.x.toFixed(0)},${c.y.toFixed(0)},${c.z.toFixed(0)} target ${t.x.toFixed(0)},${t.z.toFixed(0)}`; });
const frame = () => page.evaluate(() => { const c = window.__three.daylight.sun.shadow.camera; return `frame ${(c.right - c.left).toFixed(0)} m wide`; });
console.log(await pose(), '| held', await frame());
await page.screenshot({ path: `${out}-held.png` });
await page.evaluate(() => { const T = window.__three; T.daylight.fitShadow(T.controls.target, T.camera, T.map, performance.now()); T.post.composer.render(); });
console.log(await pose(), '| followed', await frame());
await page.screenshot({ path: `${out}-followed.png` });
await browser.close();
