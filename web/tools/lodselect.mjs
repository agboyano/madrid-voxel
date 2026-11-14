// Technique 1, stage A (docs/renderer-evaluation-plan.md): dtla-voxel's level selection applied offline to this city's
// views, with the per-node costs from tools/lodcost.mjs. A port of dtla:web/src/tileSelection.ts selectTiles with its
// balanced profile (refine past 2 px per voxel, always within 192 m, off-screen shadow casters scored at most 2.5,
// 384 leaves, 128 MiB) and no dwell (a still camera). Levels 8 -> 4 -> 2 -> 1; a 1 m leaf is its base and its foliage.
// Prints per view: the leaves by level, triangles loaded and in view (node boxes against the frustum, as three.js culls
// meshes), the GPU and column bytes, and the share of the screen each level covers (rays to the ground under a
// 64 x 40 grid of pixels). Also without the caps, which is what the rule alone asks for.
// usage: node tools/lodselect.mjs <lodcost.json> [width height, default 1600 1000]
import * as THREE from 'three';
import fs from 'node:fs';
const [file, w = '1600', h = '1000'] = process.argv.slice(2);
const { rows, light, meta } = JSON.parse(fs.readFileSync(file, 'utf8'));
const views = JSON.parse(fs.readFileSync(new URL('../public/data/meta.json', import.meta.url), 'utf8')).views;
const W = meta.W, D = meta.D, H = meta.H, N = meta.N, LEVELS = [8, 4, 2, 1];
const cost = new Map();
for (const r of rows) {
  const k = `${r.s}/${r.tx}_${r.ty}`, c = cost.get(k) ?? { tris: 0, bytes: 0, dataB: 0 };
  c.tris += r.tris; c.bytes += r.bytes; c.dataB += r.dataB; cost.set(k, c);
}
const node = (s, tx, ty) => ({ s, tx, ty, key: `${s}/${tx}_${ty}` });
const children = (n) => {
  const s = n.s / 2, L = N * s, out = [];
  for (const dy of [0, 1]) for (const dx of [0, 1]) {
    const tx = n.tx * 2 + dx, ty = n.ty * 2 + dy;
    if (tx * L < W && ty * L < D) out.push(node(s, tx, ty));
  }
  return out;
};
const boxOf = (n) => { const L = N * n.s; return new THREE.Box3(new THREE.Vector3(n.tx * L, 0, n.ty * L), new THREE.Vector3(Math.min((n.tx + 1) * L, W), H, Math.min((n.ty + 1) * L, D))); };
const bytesOf = (n) => { const c = cost.get(n.key); return c ? c.bytes + c.dataB : 0; };

function select(camera, frustum, caps) {
  const focal = +h / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)), L3 = new THREE.Vector3(...light);
  const score = (n) => {
    const box = boxOf(n), d = Math.max(1, box.clampPoint(camera.position, new THREE.Vector3()).distanceTo(camera.position));
    if (d < 192) return 1e6 / n.s;
    const projected = n.s * focal / d;
    if (frustum.intersectsBox(box)) return projected;
    if (L3.y > 0.02) {
      const dx = (-L3.x / L3.y) * H, dz = (-L3.z / L3.y) * H, sb = box.clone();
      sb.min.x += Math.min(0, dx); sb.max.x += Math.max(0, dx); sb.min.z += Math.min(0, dz); sb.max.z += Math.max(0, dz);
      if (frustum.intersectsBox(sb)) return Math.min(2.5, projected * 0.5);
    }
    return 0;
  };
  const roots = [];
  for (let ty = 0; ty * N * 8 < D; ty++) for (let tx = 0; tx * N * 8 < W; tx++) roots.push(node(8, tx, ty));
  let leaves = new Set(roots), bytes = roots.reduce((a, n) => a + bytesOf(n), 0), order = 0;
  const heap = roots.map((n) => ({ n, score: score(n), order: order++ }));
  while (heap.length) {
    heap.sort((a, b) => b.score - a.score || a.order - b.order); // highest score first, ties in insertion order
    const { n, score: sc } = heap.shift();
    if (n.s === 1 || sc <= 2) continue;
    const ch = children(n), delta = ch.reduce((a, c) => a + bytesOf(c), 0) - bytesOf(n);
    if (caps && (leaves.size + ch.length - 1 > 384 || bytes + delta > 128 * 2 ** 20)) continue;
    leaves.delete(n); for (const c of ch) { leaves.add(c); heap.push({ n: c, score: score(c), order: order++ }); }
    bytes += delta;
  }
  return [...leaves];
}

const ray = new THREE.Raycaster(), ground = new THREE.Plane();
console.log(`dtla-voxel's rule at ${w} x ${h}, sun ${light.map((v) => v.toFixed(2)).join(',')}`);
const out = {};
for (const [name, v] of Object.entries(views)) {
  const camera = new THREE.PerspectiveCamera(28, +w / +h, 0.5, 9000);
  camera.position.set(...v.pos); camera.lookAt(new THREE.Vector3(...v.target)); camera.updateMatrixWorld();
  const frustum = new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  // what three.js would draw at fixed 1 m: every 1 m node in the frustum
  let fixedLoaded = 0, fixedView = 0;
  for (const [k, c] of cost) if (k.startsWith('1/')) { fixedLoaded += c.tris; const [tx, ty] = k.slice(2).split('_').map(Number); if (frustum.intersectsBox(boxOf(node(1, tx, ty)))) fixedView += c.tris; }
  out[name] = { fixedLoaded, fixedView };
  for (const caps of [true, false]) {
    const leaves = select(camera, frustum, caps);
    const by = Object.fromEntries(LEVELS.map((s) => [s, 0])), tris = { loaded: 0, view: 0 };
    let bytes = 0;
    for (const n of leaves) { by[n.s]++; const c = cost.get(n.key); if (!c) continue; tris.loaded += c.tris; bytes += c.bytes + c.dataB; if (frustum.intersectsBox(boxOf(n))) tris.view += c.tris; }
    // screen share per level: the ground (plane at the view target's height) under a grid of pixels
    ground.set(new THREE.Vector3(0, 1, 0), -v.target[1]);
    const share = Object.fromEntries(LEVELS.map((s) => [s, 0])); let hits = 0;
    const leafAt = new Map(leaves.map((n) => [n.key, n]));
    for (let j = 0; j < 40; j++) for (let i = 0; i < 64; i++) {
      ray.setFromCamera(new THREE.Vector2((i + 0.5) / 32 - 1, 1 - (j + 0.5) / 20), camera);
      const p = ray.ray.intersectPlane(ground, new THREE.Vector3());
      if (!p || p.x < 0 || p.z < 0 || p.x >= W || p.z >= D) continue;
      hits++;
      for (const s of LEVELS) if (leafAt.has(`${s}/${Math.floor(p.x / (N * s))}_${Math.floor(p.z / (N * s))}`)) { share[s]++; break; }
    }
    out[name][caps ? 'capped' : 'uncapped'] = { by, tris, bytes, share: Object.fromEntries(LEVELS.map((s) => [s, hits ? share[s] / hits : 0])) };
  }
}
console.log('view        | fixed 1 m: loaded / in view | rule (capped): leaves 8/4/2/1, loaded / in view, GPU+columns, screen 8/4/2/1 | rule (no caps): leaves 8/4/2/1, loaded / in view');
const M = (x) => (x / 1e6).toFixed(2).padStart(5);
for (const [name, o] of Object.entries(out)) {
  const c = o.capped, u = o.uncapped, lv = (x) => LEVELS.map((s) => x.by[s]).join('/').padEnd(12), sh = (x) => LEVELS.map((s) => `${(100 * x.share[s]).toFixed(0)}`).join('/').padEnd(12);
  console.log(name.padEnd(11), '|', M(o.fixedLoaded), '/', M(o.fixedView), 'M        |', lv(c), M(c.tris.loaded), '/', M(c.tris.view), 'M ', `${(c.bytes / 2 ** 20).toFixed(0).padStart(4)} MB`, ' ', sh(c), '%  |', lv(u), M(u.tris.loaded), '/', M(u.tris.view), 'M');
}
fs.writeFileSync(file.replace(/\.json$/, '-select.json'), JSON.stringify(out));
