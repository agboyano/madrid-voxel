// Technique 1, stage A (docs/renderer-evaluation-plan.md): mesh every node of every level once in the viewer's own
// mesher, the 2 m and 4 m levels from scripts/eval_lod_tiles.py served in place of tiles the site does not have, and
// record each node's triangles, GPU bytes and column-data bytes -> <out.json>, for tools/lodselect.mjs. Level 1 is
// the base tile and its foliage tile apart. Also records the sun's direction (15 June, 11:00) for the selection.
// usage: node tools/lodcost.mjs <dir with 2/ and 4/> <out.json> [base, default http://localhost:5173]
import { launch } from './launch.mjs';
import fs from 'node:fs';
import path from 'node:path';
const [dir, out, base = 'http://localhost:5173'] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
await page.route(/\/data\/tiles\/[24]\/\d+_\d+\.bin/, (route) => {
  const m = route.request().url().match(/tiles\/([24])\/(\d+_\d+\.bin)/);
  const f = path.join(dir, m[1], m[2]);
  return fs.existsSync(f) ? route.fulfill({ body: fs.readFileSync(f), contentType: 'application/octet-stream' }) : route.fulfill({ status: 404 });
});
await page.goto(`${base}/?ui=0&date=06-15&hour=11&weather=clear`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 300000 });
const levels = JSON.parse(fs.readFileSync(path.join(dir, 'levels.json'), 'utf8')).levels;
const res = await page.evaluate(async (levels) => {
  const S = window.__streamer, rows = [];
  S.update = () => {}; // freeze the streamer: we drive it
  S.group.visible = false; // never uploaded, so the attributes keep their arrays (stream.ts releases them on upload)
  for (const l of levels) if (!S.dims[l.s]) S.dims[l.s] = l;
  const measure = (n, s, kind) => {
    const dataB = n.data ? ['counts', 'ground', 'runs', 'off'].reduce((a, k) => a + (n.data[k]?.byteLength ?? 0), 0) : 0;
    const geo = n.mesh?.geometry, tris = geo ? geo.drawRange.count / 3 : 0;
    const bytes = geo ? Object.values(geo.attributes).reduce((a, at) => a + (at.array?.byteLength ?? 0), 0) : 0;
    rows.push({ s, kind, tx: n.tx, ty: n.ty, tris, bytes, dataB });
  };
  for (const s of [1, 2, 4, 8]) {
    const d = S.dims[s];
    for (let ty = 0; ty < d.ny; ty++) {
      const ps = [];
      for (let tx = 0; tx < d.nx; tx++) ps.push(S.request(s, tx, ty, 1e9, true));
      S.pump(); await Promise.all(ps);
      if (s === 1) {
        const fs_ = [];
        for (let tx = 0; tx < d.nx; tx++) fs_.push(S.requestFoliage(tx, ty, 1e9));
        S.pump(); await Promise.all(fs_);
      }
      for (let tx = 0; tx < d.nx; tx++) {
        const n = S.nodes.get(S.key(s, tx, ty));
        measure(n, s, 'base');
        if (s === 1) { const f = S.nodes.get(`f/${tx}_${ty}`); measure(f, 1, 'foliage'); S.free(f); }
        S.free(n);
      }
    }
  }
  const L = window.__three.daylight.lightDir;
  return { rows, light: [L.x, L.y, L.z], meta: { W: S.meta.W, D: S.meta.D, H: S.meta.H, N: S.N } };
}, levels);
res.files = {};
for (const s of [1, 2, 4, 8]) for (const k of s === 1 ? ['1', '1f'] : [String(s)]) {
  const d = s === 1 || s === 8 ? path.join('public/data/tiles', k) : path.join(dir, k);
  res.files[k] = fs.readdirSync(d).reduce((a, f) => a + fs.statSync(path.join(d, f)).size, 0);
}
fs.writeFileSync(out, JSON.stringify(res));
for (const s of [1, 2, 4, 8]) for (const kind of ['base', 'foliage']) {
  const R = res.rows.filter((r) => r.s === s && r.kind === kind);
  if (!R.length) continue;
  const sum = (k) => R.reduce((a, r) => a + r[k], 0);
  console.log(`level ${s} ${kind.padEnd(7)} ${String(R.length).padStart(4)} nodes  ${(sum('tris') / 1e6).toFixed(2).padStart(6)} M tris  ${(sum('bytes') / 2 ** 20).toFixed(0).padStart(5)} MB GPU  ${(sum('dataB') / 2 ** 20).toFixed(0).padStart(4)} MB columns`);
}
console.log('download (gz)', Object.entries(res.files).map(([k, b]) => `${k} ${(b / 2 ** 20).toFixed(2)} MB`).join(', '));
await browser.close();
