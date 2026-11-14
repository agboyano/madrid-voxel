// Do the slow frames left after the swap limit (DECISIONS.md, 2026-11-14) come from redraws of the sun's shadow map?
// Technique 2's abandonment test (docs/renderer-evaluation-plan.md): it is dropped if there are fewer than 6 redraws a
// minute in normal navigation and fewer than 20 % of the slow frames coincide with one. Records every frame's interval
// and whether the sun's map was redrawn in it, and why (as tools/redraws.mjs: a refit, a swap, or other, which is the
// light itself moving with the hour), while the visitor rotates, tilts, pans, zooms, flies between views and drags
// the hour. A frame is slow over 100 ms (the plan's flight criterion) and, separately, over twice the median of its
// activity. A redraw is drawn in the frame whose rAF callback rendered it and shows up as that frame's interval or the
// next (the GPU runs behind), so a slow frame coincides with one if either of its two frames redrew; the chance of
// that at random is given alongside.
// usage: node tools/slowframes.mjs [base, default http://localhost:5173] [query, e.g. "level=0.3"] [out.json]
import { launch } from './launch.mjs';
import fs from 'node:fs';
const [base = 'http://localhost:5173', query = '', out] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
await page.goto(`${base}/?view=overview&date=06-21&hour=16&weather=clear${query ? `&${query}` : ''}`);
await page.waitForFunction(() => window.__three?.daylight?.gate, null, { timeout: 60000, polling: 50 });
await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 250 });
await page.waitForTimeout(20000);
await page.evaluate(() => {
  const d = window.__three.daylight, g = d.gate, f = g.onBeforeShadow;
  let why = new Set(), drawn = '';
  const fit = d.fitSun.bind(d), still = d.redrawShadow.bind(d);
  d.fitSun = (...a) => { why.add('fit'); return fit(...a); };
  d.redrawShadow = () => { why.add('swap'); return still(); };
  g.onBeforeShadow = function (a, b, c, cam, ...rest) {
    if (cam === d.sun.shadow.camera) { drawn = [...why].join('+') || 'other'; why = new Set(); }
    return f.call(this, a, b, c, cam, ...rest);
  };
  // registered after the app's loop, so each tick runs right after that frame's render
  const rec = window.__rec = { frames: [], label: '' };
  let last = performance.now();
  const tick = (t) => {
    rec.frames.push({ dt: t - last, redraw: drawn, label: rec.label, level: window.__three.level() });
    last = t; drawn = '';
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});
const label = (l) => page.evaluate((l) => { window.__rec.label = l; }, l);
const cx = 720, cy = 450;
const drag = (button, dx, dy) => async () => {
  await page.mouse.move(cx - 50 * dx, cy - 50 * dy); await page.mouse.down({ button });
  for (let i = -50; i < 50; i++) { await page.mouse.move(cx + i * dx, cy + i * dy); await page.waitForTimeout(50); }
  await page.mouse.up({ button });
};
const views = await page.evaluate(() => fetch('data/meta.json').then((r) => r.json()).then((m) => m.views));
const flyTo = (v) => page.evaluate((v) => window.__three.flyTo(v), views[v]);
const acts = [
  ['still', () => page.waitForTimeout(5000)],
  ['rotate', drag('right', 4, 0)],
  ['tilt', drag('right', 0, 2)],
  ['pan', drag('left', 4, 0)],
  ['zoom', async () => { await page.mouse.move(cx, cy); for (let i = 0; i < 50; i++) { await page.mouse.wheel(0, i < 25 ? -40 : 40); await page.waitForTimeout(100); } }],
  // a tour of the views (main.ts flyTo, as the search's viewpoints do), each flight left to settle
  ['fly', async () => { for (const v of ['top', 'palace', 'plazamayor', 'overview', 'sol', 'granvia', 'cibeles', 'overview']) { await flyTo(v); await page.waitForTimeout(2600); } }],
  // the hour slider dragged from 16:00 to 19:00 in 10 s, as its input events would (bar.ts: onHour -> setHour)
  ['hour', async () => { for (let i = 0; i <= 200; i++) { await page.evaluate((h) => window.__three.setHour(h), 16 + 3 * i / 200); await page.waitForTimeout(50); } }],
  ['still', () => page.waitForTimeout(5000)],
];
for (const [l, act] of acts) { await label(l); await act(); }
await label('');
await page.waitForTimeout(200);
const frames = await page.evaluate(() => window.__rec.frames.slice(1));
await browser.close();
if (out) fs.writeFileSync(out, JSON.stringify({ query, frames }));

const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)] ?? 0; };
const pct = (a, b) => (b ? (100 * a / b).toFixed(0) + ' %' : '-');
const rows = [];
for (const l of [...new Set(frames.map((f) => f.label))].filter(Boolean)) {
  const idx = frames.map((f, i) => (f.label === l ? i : -1)).filter((i) => i >= 0);
  const fs_ = idx.map((i) => frames[i]), secs = fs_.reduce((s, f) => s + f.dt, 0) / 1000;
  const med = median(fs_.map((f) => f.dt));
  // the frame itself or the one before redrew
  const near = (i) => frames[i].redraw || (i > 0 && frames[i - 1].redraw);
  const causes = {};
  for (const f of fs_) if (f.redraw) causes[f.redraw] = (causes[f.redraw] ?? 0) + 1;
  const redraws = fs_.filter((f) => f.redraw).length;
  const slow = (lim) => { const s = idx.filter((i) => frames[i].dt > lim); return [s.length, s.filter(near).length]; };
  const [s100, c100] = slow(100), [s2, c2] = slow(2 * med);
  const levels = fs_.map((f) => f.level);
  rows.push({ l, n: fs_.length, secs, med, p95: [...fs_.map((f) => f.dt)].sort((a, b) => a - b)[Math.floor(fs_.length * 0.95)],
    redraws, perMin: redraws / secs * 60, causes, s100, c100, s2, c2, chance: idx.filter(near).length / idx.length,
    redrawDt: median(idx.filter(near).map((i) => frames[i].dt)), otherDt: median(idx.filter((i) => !near(i)).map((i) => frames[i].dt)),
    level: `${Math.min(...levels).toFixed(2)}-${Math.max(...levels).toFixed(2)}` });
}
console.log(query || '(adaptive level)');
console.log('activity  frames    s  median  p95  | redraws /min  causes               | >100 ms  with redraw | >2x median  with redraw | chance | dt redraw/other | level');
for (const r of rows) {
  console.log(r.l.padEnd(8), String(r.n).padStart(7), r.secs.toFixed(1).padStart(5), r.med.toFixed(0).padStart(6), r.p95.toFixed(0).padStart(5), ' |',
    String(r.redraws).padStart(7), r.perMin.toFixed(0).padStart(4), ' ', Object.entries(r.causes).map(([k, v]) => `${k} ${v}`).join(', ').padEnd(20), '|',
    String(r.s100).padStart(7), `${r.c100} (${pct(r.c100, r.s100)})`.padStart(12), ' |', String(r.s2).padStart(10), `${r.c2} (${pct(r.c2, r.s2)})`.padStart(12), ' |',
    pct(r.chance * 1000, 1000).padStart(6), ' |', `${r.redrawDt.toFixed(0)} / ${r.otherDt.toFixed(0)} ms`.padStart(15), ' |', r.level);
}
