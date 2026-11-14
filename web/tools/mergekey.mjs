// How much each field of the mesher's merge key splits the greedy rectangles: mesh every 1 m base and foliage tile with
// the real mesher (src/mesher.worker.ts, run in a vm), the key as it is and with one field or several left out, and
// count the quads. Each variant must cover exactly the same face area per direction (only the partition changes).
// Offline, no rendering: it says what a change would save in geometry, not what it would look like or cost in frames.
// Technique 3 of docs/renderer-evaluation-plan.md; idea from dtla-voxel's web/tools/bench-mesh-merging.mjs (3e77ad7).
// usage: node tools/mergekey.mjs [out.json]      (reads public/data; no server)
import fs from 'node:fs';
import vm from 'node:vm';
import { stripTypeScriptTypes } from 'node:module';
import { gunzipSync } from 'node:zlib';

const [out] = process.argv.slice(2);
const KEY = 'key = (((ang * 4096 + a) * 256 + aob) * 256 + gm) * 16384 + bidAt(px, py) + 1;';
const VARIANTS = {
  original: KEY,
  noAO: 'key = (((ang * 4096 + a) * 256 + 255) * 256 + gm) * 16384 + bidAt(px, py) + 1;',
  noGround: 'key = (((ang * 4096 + a) * 256 + aob) * 256 + 0) * 16384 + bidAt(px, py) + 1;',
  noBuilding: 'key = (((ang * 4096 + a) * 256 + aob) * 256 + gm) * 16384 + 0 + 1;',
  noAOGround: 'key = (((ang * 4096 + a) * 256 + 255) * 256 + 0) * 16384 + bidAt(px, py) + 1;',
  noAOGroundBuilding: 'key = (((ang * 4096 + a) * 256 + 255) * 256 + 0) * 16384 + 0 + 1;',
};
const src = fs.readFileSync('src/mesher.worker.ts', 'utf8');
if (!src.includes(KEY)) throw new Error('the merge key in src/mesher.worker.ts changed: update KEY');
const clean = (s) => stripTypeScriptTypes(s).replace(/^export /gm, '').replace(/^self\.onmessage[\s\S]*?^};$/m, '');
const mesh = Object.fromEntries(Object.entries(VARIANTS).map(([name, key]) => {
  const ctx = vm.createContext({ self: {}, console });
  vm.runInContext(clean(src.replace(KEY, key)) + '\nglobalThis.api = { decode, meshTile };', ctx);
  return [name, ctx.api];
}));

const meta = JSON.parse(fs.readFileSync('public/data/meta.json', 'utf8'));
const { W, D } = meta, N = meta.tiles.N, L1 = meta.tiles.levels.find((l) => l.s === 1);
const zb = gunzipSync(fs.readFileSync('public/data/zones.bin'));
const bld = new Uint16Array(zb.buffer.slice(zb.byteOffset + W * D * 2, zb.byteOffset + W * D * 4));
const read = (dir, tx, ty) => { const b = gunzipSync(fs.readFileSync(`public/data/tiles/${dir}/${tx}_${ty}.bin`)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
const idsOf = (x0, y0) => { // as stream.ts buildingIds
  const ids = new Uint16Array(N * N);
  for (let r = 0; r < N && y0 + r < D; r++) ids.set(bld.subarray((y0 + r) * W + x0, (y0 + r) * W + Math.min(x0 + N, W)), r * N);
  return ids;
};
// face area per direction (normal index 0-5), from the quads' corners
const area = (o) => {
  const a = new Float64Array(6);
  for (let q = 0; q < o.quads; q++) {
    const p = o.pos, v = q * 4, n = o.attr[v * 4] & 7, xs = [], ys = [], zs = [];
    for (let k = 0; k < 4; k++) { xs.push(p[(v + k) * 3]); ys.push(p[(v + k) * 3 + 1]); zs.push(p[(v + k) * 3 + 2]); }
    const ext = [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), Math.max(...zs) - Math.min(...zs)].filter((e) => e > 0);
    a[n] += ext[0] * ext[1];
  }
  return [...a];
};

const tot = {};
for (const kind of ['base', 'foliage']) for (const name of Object.keys(VARIANTS)) tot[`${kind}/${name}`] = { quads: 0, ms: 0 };
const t0 = performance.now();
for (let ty = 0; ty < L1.ny; ty++) {
  for (let tx = 0; tx < L1.nx; tx++) {
    const x0 = tx * N, y0 = ty * N, baseBuf = read('1', tx, ty), folBuf = read('1f', tx, ty), ids = idsOf(x0, y0);
    for (const kind of ['base', 'foliage']) {
      let ref = null;
      for (const [name, api] of Object.entries(mesh)) {
        const cols = api.decode(kind === 'base' ? baseBuf : folBuf, N);
        const under = kind === 'foliage' ? api.decode(baseBuf, N) : null;
        const s = performance.now(), o = api.meshTile(N, 1, x0, y0, cols, kind === 'base' ? ids : null, under), ms = performance.now() - s;
        const a = area(o);
        if (!ref) ref = a;
        else if (a.some((x, k) => Math.abs(x - ref[k]) > 1e-6)) throw new Error(`${kind} ${tx}_${ty} ${name}: face area changed`);
        tot[`${kind}/${name}`].quads += o.quads; tot[`${kind}/${name}`].ms += ms;
      }
    }
  }
  process.stdout.write(`\rrow ${ty + 1}/${L1.ny}  ${((performance.now() - t0) / 1000).toFixed(0)} s`);
}
console.log();
const rows = Object.entries(tot).map(([k, v]) => {
  const [kind, name] = k.split('/'), o = tot[`${kind}/original`].quads;
  return { kind, variant: name, Mtris: +(v.quads * 2 / 1e6).toFixed(2), vsOriginal: `${(100 * (v.quads / o - 1)).toFixed(1)} %`, meshS: +(v.ms / 1000).toFixed(1) };
});
const all = (name) => tot[`base/${name}`].quads + tot[`foliage/${name}`].quads;
for (const name of Object.keys(VARIANTS)) rows.push({ kind: 'city', variant: name, Mtris: +(all(name) * 2 / 1e6).toFixed(2), vsOriginal: `${(100 * (all(name) / all('original') - 1)).toFixed(1)} %`, meshS: '' });
console.table(rows);
if (out) { fs.writeFileSync(out, JSON.stringify({ when: new Date().toISOString(), tiles: L1.nx * L1.ny, rows }, null, 1)); console.log('->', out); }
