// Do GPU uploads cost frames? Flies between the named views at a fixed level, recording each frame's time and the bytes it
// handed to gl.bufferData, and whether it redrew the city's shadow map, then compares the groups.
// usage: node tools/uploads.mjs [level]   (dev server on :5173; $CHROMIUM picks the browser)
import { chromium } from 'playwright-core';
const [level = '0.5'] = process.argv.slice(2);
const browser = await chromium.launch({
  headless: true, executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
  args: ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await page.goto(`http://localhost:5173/?hour=12&level=${level}`);
await page.waitForFunction(() => window.__ready === true && !document.body.classList.contains('loading'), null, { timeout: 300000 });
await page.waitForTimeout(3000);
const frames = await page.evaluate(async () => {
  const gl = window.__three.renderer.getContext(), bufferData = gl.bufferData.bind(gl);
  let bytes = 0;
  gl.bufferData = (t, d, u) => { bytes += typeof d === 'number' ? d : d?.byteLength ?? 0; return bufferData(t, d, u); };
  const d = window.__three.daylight, out = []; let last = performance.now(), run = true, redraws = d.redraws;
  // a frame's time lands in the next callback; the bytes and shadow redraws counted by then are that frame's
  const tick = (n) => { out.push([n - last, bytes, d.redraws - redraws]); bytes = 0; redraws = d.redraws; last = n; if (run) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const { views } = await (await fetch('data/meta.json')).json();
  for (const k of ['sol', 'granvia', 'cibeles', 'prado', 'palace', 'plazamayor', 'street', 'overview']) {
    window.__three.flyTo(views[k]);
    await new Promise((r) => setTimeout(r, 3500));
  }
  run = false;
  return out;
});
const pct = (a, p) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : NaN; };
const groups = {
  'nothing': (b, r) => b === 0 && !r, 'shadow only': (b, r) => b === 0 && r, 'upload < 1 MB': (b, r) => b > 0 && b < 1e6 && !r,
  'upload >= 1 MB': (b, r) => b >= 1e6 && !r, 'upload+shadow': (b, r) => b > 0 && r,
};
const all = frames.map((f) => f[0]);
console.log(`${frames.length} frames, ${(frames.reduce((a, f) => a + f[1], 0) / 1e6).toFixed(0)} MB uploaded; all frames: median ${pct(all, 0.5).toFixed(1)} ms, p95 ${pct(all, 0.95).toFixed(1)} ms, ${all.filter((t) => t > 100).length} over 100 ms`);
for (const [name, test] of Object.entries(groups)) {
  const dt = frames.filter((f) => test(f[1], f[2] > 0)).map((f) => f[0]);
  console.log(`${name.padEnd(15)} ${String(dt.length).padStart(5)} frames  median ${pct(dt, 0.5).toFixed(1)} ms  p95 ${pct(dt, 0.95).toFixed(1)} ms  max ${Math.max(...dt).toFixed(0)} ms`);
}
const big = frames.map((f, i) => [i, ...f]).sort((a, b) => b[1] - a[1]).slice(0, 8);
console.log('slowest frames (index, ms, upload MB):', big.map(([i, t, b]) => `${i}:${t.toFixed(0)}/${(b / 1e6).toFixed(1)}`).join(' '));
await browser.close();
