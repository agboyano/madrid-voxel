// Walk-mode collision check: World must answer every voxel query from the finest loaded tile.
// At a low render level the city is mostly 8 m clay; a query that lands on clay must not make
// later queries near the walker (inside the same 8 m tile) read clay instead of its 1 m tile.
// usage: node tools/walkstuck.mjs [outdir] [level]   (dev server on :5173; $CHROMIUM picks the browser)
import { chromium } from 'playwright-core';
const [out = '/tmp', level = '0.1'] = process.argv.slice(2);
const browser = await chromium.launch({
  headless: true, executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
  args: ['--use-angle=gl', '--ignore-gpu-blocklist', '--enable-gpu'],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errs = [];
page.on('pageerror', (e) => errs.push(e.message));
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
const idle = () => page.waitForFunction(() => window.__streamer.inflight === 0 && window.__streamer.queue.length === 0, null, { timeout: 60000 })
  .catch(() => console.log('streamer still busy, going on'));
await page.goto('http://localhost:5173/?hour=12');
await page.waitForFunction(() => window.__ready === true, null, { timeout: 180000 });
await page.evaluate((l) => { // the Render size slider, as scripts/screenshot.py sets it
  const input = [...document.querySelectorAll('label')].find((e) => e.textContent.trim() === 'Render size')?.querySelector('input');
  input.value = l;
  input.dispatchEvent(new Event('input'));
}, level);
await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 300000 });
await idle();
await page.evaluate(() => window.__three.nav.setWalk());
await page.waitForFunction(() => window.__three.nav.mode === 'walk', null, { timeout: 60000 });
await page.waitForTimeout(1500);

// every query World answers from a coarse tile while a finer one is loaded there is a wrong answer
await page.evaluate(() => {
  const w = window.__three.nav.world, s = window.__streamer, node = w.node.bind(w), fine = s.levels.at(-1), L = s.N * fine;
  window.__wrong = 0;
  w.node = (x, r) => {
    const d = node(x, r);
    if (d && d.s > fine && s.columns(`${fine}/${Math.floor(x / L)}_${Math.floor(r / L)}`)) window.__wrong++;
    return d;
  };
});

// deterministic: the walker's surroundings, read before and after one query on clay in the same coarse tile
const probe = await page.evaluate(() => {
  const { nav } = window.__three, w = nav.world, s = window.__streamer, P = nav.walkPos, feet = nav.feet;
  const fine = s.levels.at(-1), coarse = s.levels[0], L = s.N * fine, C = s.N * coarse;
  const read = () => {
    const a = [];
    for (let dx = -4; dx <= 4; dx++) for (let dz = -4; dz <= 4; dz++) {
      const x = P.x + dx, z = P.z + dz;
      a.push(w.support(x, z, feet + 1.05), w.blocked(x, z, feet + 1.05, feet + 1.9) ? 1 : 0);
    }
    return a;
  };
  window.__wrong = 0;
  w.solid(P.x, P.z, 0); // starts from the walker's own tile
  const before = read(), wrongBefore = window.__wrong;
  const bx = Math.floor(P.x / C) * C, bz = Math.floor(P.z / C) * C;
  let clay = null;
  for (let x = bx; x < bx + C && !clay; x += L) for (let z = bz; z < bz + C && !clay; z += L)
    if (w.inside(x + 1, z + 1) && !s.columns(`${fine}/${x / L}_${z / L}`)) clay = [x + L / 2, z + L / 2];
  if (!clay) return { clay: null };
  w.solid(clay[0], clay[1], 0);
  const after = read();
  return { clay, at: [P.x, P.z].map(Math.round), feet, wrongBefore, wrongAfter: window.__wrong - wrongBefore,
    differ: before.filter((v, i) => v !== after[i]).length };
});
console.log('probe', JSON.stringify(probe));

// in the running viewer: walk forward and count wrong answers (labels, street life and nav all query World)
await page.evaluate(() => { window.__wrong = 0; });
const p0 = await page.evaluate(() => window.__three.nav.walkPos.toArray());
await page.keyboard.down('KeyW'); await page.waitForTimeout(5000); await page.keyboard.up('KeyW');
const p1 = await page.evaluate(() => window.__three.nav.walkPos.toArray());
const moved = Math.hypot(p1[0] - p0[0], p1[2] - p0[2]);
const wrong = await page.evaluate(() => window.__wrong);
console.log('walk', JSON.stringify({ from: p0.map(Math.round), to: p1.map(Math.round), moved: +moved.toFixed(1), wrong }));
await page.screenshot({ path: `${out}/walkstuck.png` });
console.log('errors', errs);
await browser.close();
const ok = probe.clay && probe.differ === 0 && probe.wrongBefore + probe.wrongAfter === 0 && wrong === 0;
console.log(ok ? 'PASS' : probe.clay ? 'FAIL' : 'SKIP: no clay-only tile next to the walker; lower the level');
process.exit(ok ? 0 : 1);
