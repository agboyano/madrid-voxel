// How often the city's shadow map is redrawn, and why, while loading, then while the visitor rotates, tilts, pans, zooms
// and sits still. Each redraw is put down to a refit of the sun's frame (daylight.fitSun: the focus moved or the view
// grew) or to a change in what the map shows (main.ts stillChanged: the tiles shown, real or clay, and their uniforms).
// Mouse as in src/nav/nav.ts: left button pans, right rotates (sideways) and tilts (up and down), the wheel zooms.
// usage: node tools/redraws.mjs [base, default http://localhost:5173] [query, e.g. "level=0.3"]
import { launch } from './launch.mjs';
const [base = 'http://localhost:5173', query = ''] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
await page.goto(`${base}/?date=06-21&hour=16&weather=clear${query ? `&${query}` : ''}`);
await page.waitForFunction(() => window.__three?.daylight?.gate, null, { timeout: 60000, polling: 50 });
await page.evaluate(() => {
  const d = window.__three.daylight, g = d.gate, f = g.onBeforeShadow;
  let why = new Set();
  const fit = d.fitSun.bind(d), still = d.redrawShadow.bind(d);
  d.fitSun = (...a) => { why.add('fit'); return fit(...a); };
  d.redrawShadow = () => { why.add('still'); return still(); };
  window.__redraws = [];
  g.onBeforeShadow = function (a, b, c, cam, ...rest) {
    if (cam === d.sun.shadow.camera) { window.__redraws.push([...why].join('+') || 'other'); why = new Set(); }
    return f.call(this, a, b, c, cam, ...rest);
  };
});
const t0 = await page.evaluate(() => performance.now());
await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 250 });
const causes = (rs) => Object.entries(rs.reduce((o, r) => ({ ...o, [r]: (o[r] ?? 0) + 1 }), {})).map(([k, v]) => `${k} ${v}`).join(', ');
// where the camera is: focus (x, z), azimuth and elevation around it (degrees), distance to it
const pose = () => page.evaluate(() => {
  const c = window.__three.camera.position, t = window.__three.controls.target, v = c.clone().sub(t);
  return [t.x, t.z, Math.atan2(v.x, v.z) * 180 / Math.PI, Math.asin(v.y / v.length()) * 180 / Math.PI, v.length()];
});
const span = async (label, act) => {
  const a = await page.evaluate(() => [performance.now(), window.__redraws.length]), p = await pose();
  await act();
  const [t, rs] = await page.evaluate((n) => [performance.now(), window.__redraws.slice(n)], a[1]), q = await pose();
  const moved = `focus ${Math.hypot(q[0] - p[0], q[1] - p[1]).toFixed(0)} m, azimuth ${(q[2] - p[2]).toFixed(0)}°, elevation ${(q[3] - p[3]).toFixed(0)}°, distance ${p[4].toFixed(0)} -> ${q[4].toFixed(0)} m`;
  console.log(label.padEnd(26), `${rs.length} redraws in ${((t - a[0]) / 1000).toFixed(1)} s`, rs.length ? `(${causes(rs)})` : '', `| ${moved}`);
};
console.log('loading'.padEnd(26), `${await page.evaluate(() => window.__redraws.length)} redraws in ${((await page.evaluate(() => performance.now()) - t0) / 1000).toFixed(1)} s`);
await span('after load, growing 20 s', () => page.waitForTimeout(20000));
await span('still 5 s', () => page.waitForTimeout(5000));
const cx = 720, cy = 450;
const drag = (button, dx, dy) => async () => {
  // centred on the screen: a drag that ended over the side panels left the controls stuck for the next ones
  await page.mouse.move(cx - 50 * dx, cy - 50 * dy); await page.mouse.down({ button });
  for (let i = -50; i < 50; i++) { await page.mouse.move(cx + i * dx, cy + i * dy); await page.waitForTimeout(50); }
  await page.mouse.up({ button });
};
await span('rotate 5 s', drag('right', 4, 0));
await span('tilt 5 s', drag('right', 0, 2));
await span('pan 5 s', drag('left', 4, 0));
await span('zoom 5 s', async () => { await page.mouse.move(cx, cy); for (let i = 0; i < 50; i++) { await page.mouse.wheel(0, i < 25 ? -40 : 40); await page.waitForTimeout(100); } });
await span('still 5 s', () => page.waitForTimeout(5000));
console.log('level', await page.evaluate(() => window.__three.level().toFixed(2)));
await browser.close();
