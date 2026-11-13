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

// inside something solid (a tile that came in around the walker, say): walking must get out of it
const post = await page.evaluate(() => {
  const { nav } = window.__three, w = nav.world, P = nav.walkPos;
  for (let r = 2; r < 60; r++) for (let dx = -r; dx <= r; dx++) for (const dz of [-r, r]) {
    const x = Math.floor(P.x) + dx + 0.5, z = Math.floor(P.z) + dz + 0.5, g = w.groundAt(x, z);
    if (!w.blocked(x, z, g + 1, g + 2)) continue;
    // a post: open ground on all four sides
    if ([[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => w.blocked(x + a, z + b, g + 1, g + 3) || Math.abs(w.groundAt(x + a, z + b) - g) > 1)) continue;
    nav.goal = null; nav.vy = 0;
    nav.walkPos.set(x, 0, z);
    nav.feet = g;
    return { at: [x, z], g };
  }
  return null;
});
let out_ = null;
if (post) {
  await page.keyboard.down('KeyW'); await page.waitForTimeout(6000); await page.keyboard.up('KeyW');
  out_ = await page.evaluate(({ at }) => {
    const { nav } = window.__three, w = nav.world, P = nav.walkPos;
    return { moved: +Math.hypot(P.x - at[0], P.z - at[1]).toFixed(1), inside: w.blocked(P.x, P.z, nav.feet + 1.05, nav.feet + 1.9) };
  }, post);
}
console.log('post', JSON.stringify(post), JSON.stringify(out_));

// walking off the loaded detail: a street that runs on into a 1 m tile not loaded yet, where the clay leaves the way
// open. The tile is loaded once to find such a street, then freed and fetched again over a slow network (every 1 m tile
// held back HOLD ms, as on a phone): the walker must wait at the border, not walk on through clay, and go on once it is in
const HOLD = 15000;
await page.route(/\/data\/tiles\/1\/\d+_\d+\.bin/, async (r) => { await new Promise((ok) => setTimeout(ok, HOLD)); r.continue().catch(() => {}); });
const edge = await page.evaluate(async () => {
  const { nav } = window.__three, w = nav.world, s = window.__streamer, fine = s.levels.at(-1), L = s.N * fine, d = s.dims[fine];
  const P = nav.walkPos, tx0 = Math.floor(P.x / L), ty0 = Math.floor(P.z / L), pairs = [];
  for (const n of s.nodes.values()) if (n.s === fine && !n.foliage && n.data) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    const bx = n.tx + dx, by = n.ty + dy;
    if (bx >= 0 && by >= 0 && bx < d.nx && by < d.ny && !s.nodes.has(`${fine}/${bx}_${by}`))
      pairs.push([n.tx, n.ty, dx, dy, Math.hypot(n.tx - tx0, n.ty - ty0)]);
  }
  pairs.sort((a, b) => a[4] - b[4]);
  for (const [ax, ay, dx, dy] of pairs.slice(0, 8)) {
    const bx = ax + dx, by = ay + dy, key = `${fine}/${bx}_${by}`;
    await s.ensure((bx + 0.5) * L, (by + 0.5) * L, 1);
    // the border, a point along it, and a path from 3 m before it to 12 m past it
    const along = (t, k) => dx ? [(dx > 0 ? bx * L : ax * L) + dx * k, ay * L + t + 0.5] : [ax * L + t + 0.5, (dy > 0 ? by * L : ay * L) + dy * k];
    const free = [];
    for (let t = 4; t < L - 4; t += 2) {
      let ok = true, g0 = w.groundAt(...along(t, -3)), prev = g0;
      for (let k = -3; k <= 12 && ok; k++) for (const o of [-1, 0, 1]) {
        const [x, z] = along(t + o, k), g = w.groundAt(x, z);
        if (w.blocked(x, z, g, g + 3) || Math.abs(g - prev) > 1) { ok = false; break; }
        if (!o) prev = g;
      }
      if (ok) free.push([t, g0]);
    }
    s.free(s.nodes.get(key));
    for (const [t, g0] of free) {
      let wall = false;
      for (let k = 0; k <= 12; k++) for (const o of [-1, 0, 1]) { const [x, z] = along(t + o, k); if (w.blocked(x, z, g0, g0 + 2)) wall = true; }
      if (wall) continue;
      const [x, z] = along(t, -3);
      nav.goal = null; nav.vy = 0;
      nav.walkPos.set(x, 0, z);
      nav.feet = w.support(x, z, g0 + 1.5);
      nav.yaw = Math.atan2(dx, dy);
      return { key, start: [x, z], dir: [dx, dy], border: dx ? along(t, 0)[0] : along(t, 0)[1] };
    }
  }
  return null;
});
let cross = null;
const trail = []; // [seconds, metres past the border, tile loaded]
if (edge) {
  await page.keyboard.down('KeyW');
  for (let i = 0; i < 30 && !(cross && cross.past > 4 && cross.loaded); i++) {
    await page.waitForTimeout(2000);
    cross = await page.evaluate(({ dir, border, key }) => {
      const { nav } = window.__three, w = nav.world, P = nav.walkPos, g = w.groundAt(P.x, P.z);
      return { past: +((dir[0] ? P.x : P.z) * (dir[0] || dir[1]) - border * (dir[0] || dir[1])).toFixed(1),
        loaded: !!window.__streamer.columns(key), overGround: +(nav.feet - g).toFixed(1), inside: w.blocked(P.x, P.z, nav.feet + 1.05, nav.feet + 1.9) };
    }, edge);
    trail.push([2 * (i + 1), cross.past, cross.loaded ? 1 : 0]);
  }
  await page.keyboard.up('KeyW');
}
await page.unroute(/\/data\/tiles\/1\/\d+_\d+\.bin/);
console.log('edge', JSON.stringify(edge), JSON.stringify(cross), 'trail', JSON.stringify(trail));
await page.screenshot({ path: `${out}/walkstuck.png` });
console.log('errors', errs);
await browser.close();
const edgeOk = edge && cross.past > 4 && cross.loaded && !cross.inside && Math.abs(cross.overGround) < 1.5
  && trail.every(([, past, loaded]) => loaded || past <= 0);
const postOk = post && out_.moved > 0.5 && !out_.inside;
console.log(JSON.stringify({ edgeOk, postOk }));
const ok = probe.clay && probe.differ === 0 && probe.wrongBefore + probe.wrongAfter === 0 && wrong === 0 && edgeOk && postOk;
console.log(ok ? 'PASS' : probe.clay && edge && post ? 'FAIL' : 'SKIP: no clay-only tile next to the walker; lower the level');
process.exit(ok ? 0 : 1);
