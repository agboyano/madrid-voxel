// Technique 1, stage A (docs/renderer-evaluation-plan.md): what this viewer draws today at a given level, in the terms
// tools/lodselect.mjs gives dtla-voxel's rule: the triangles of the tile meshes in view (visible meshes whose box meets
// the frustum, as three.js culls them) and the share of the screen at 1 m, against 8 m clay. The screen is the ground
// (plane at the view target's height) under the same 64 x 40 grid of pixels; a pixel is 1 m when the city block under
// it is real (city.ts flags, block ids per cell), clay when it is not, and "none" outside every block.
// usage: node tools/lodshare.mjs [base, default http://localhost:5173] [view:level,... default the six of the plan]
import { launch } from './launch.mjs';
const [base = 'http://localhost:5173', list = 'overview:0.14,top:0.25,prado:0.21,cibeles:0.25,sol:0.43,street:0.39'] = process.argv.slice(2);
const browser = await launch();
for (const item of list.split(',')) {
  const [view, level] = item.split(':');
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
  await page.goto(`${base}/?view=${view}&level=${level}&date=06-15&hour=11&weather=clear&ui=0`);
  await page.waitForFunction(() => window.__ready && !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 500 });
  await page.waitForFunction(() => { const s = window.__streamer, c = window.__three.city(); return s.inflight === 0 && s.queue.length === 0 && c.settled; }, null, { timeout: 900000, polling: 500 });
  await page.waitForTimeout(3000);
  const r = await page.evaluate(async () => {
    const T = window.__three, S = window.__streamer, cam = T.camera;
    const U = T.daylight.uniforms;
    const blk = U.uZBlk.value.image.data, flags = U.uZFBlk.value.image.data, W = S.meta.W, D = S.meta.D;
    cam.updateMatrixWorld();
    // three is not on window: the frustum from the camera's projection and view matrices (planes in world space), as THREE.Frustum does
    const m = cam.projectionMatrix.clone().multiply(cam.matrixWorldInverse).elements;
    const planes = [[m[3] - m[0], m[7] - m[4], m[11] - m[8], m[15] - m[12]], [m[3] + m[0], m[7] + m[4], m[11] + m[8], m[15] + m[12]],
      [m[3] + m[1], m[7] + m[5], m[11] + m[9], m[15] + m[13]], [m[3] - m[1], m[7] - m[5], m[11] - m[9], m[15] - m[13]],
      [m[3] - m[2], m[7] - m[6], m[11] - m[10], m[15] - m[14]], [m[3] + m[2], m[7] + m[6], m[11] + m[10], m[15] + m[14]]];
    const meets = (b) => planes.every(([a, bb, c, d]) => a * (a > 0 ? b.max.x : b.min.x) + bb * (bb > 0 ? b.max.y : b.min.y) + c * (c > 0 ? b.max.z : b.min.z) + d >= 0);
    const tris = { buildings: 0, foliage: 0, clay: 0 };
    for (const n of S.nodes.values()) {
      if (!n.mesh?.visible) continue;
      const L = S.N * n.s, box = { min: { x: n.tx * L, y: 0, z: n.ty * L }, max: { x: Math.min((n.tx + 1) * L, W), y: S.meta.H, z: Math.min((n.ty + 1) * L, D) } };
      if (!meets(box)) continue;
      tris[n.s === 8 ? 'clay' : n.foliage ? 'foliage' : 'buildings'] += n.mesh.geometry.drawRange.count / 3;
    }
    // the ground under a grid of pixels
    const t = T.controls.target, share = { real: 0, clay: 0, none: 0 };
    const inv = cam.projectionMatrixInverse.elements, w = cam.matrixWorld.elements;
    const unproject = (x, y) => { // NDC (x, y, 1) -> world point on the far plane
      const v = [x, y, 1, 1], p = [0, 0, 0, 0];
      for (let i = 0; i < 4; i++) p[i] = inv[i] * v[0] + inv[4 + i] * v[1] + inv[8 + i] * v[2] + inv[12 + i] * v[3];
      const q = [p[0] / p[3], p[1] / p[3], p[2] / p[3]];
      return [w[0] * q[0] + w[4] * q[1] + w[8] * q[2] + w[12], w[1] * q[0] + w[5] * q[1] + w[9] * q[2] + w[13], w[2] * q[0] + w[6] * q[1] + w[10] * q[2] + w[14]];
    };
    const o = cam.position;
    for (let j = 0; j < 40; j++) for (let i = 0; i < 64; i++) {
      const f = unproject((i + 0.5) / 32 - 1, 1 - (j + 0.5) / 20), dir = [f[0] - o.x, f[1] - o.y, f[2] - o.z];
      if (dir[1] >= 0) continue;
      const k = (t.y - o.y) / dir[1], x = o.x + dir[0] * k, z = o.z + dir[2] * k;
      if (x < 0 || z < 0 || x >= W || z >= D) continue;
      const b = blk[Math.floor(z) * W + Math.floor(x)];
      share[!b ? 'none' : flags[b] ? 'real' : 'clay']++;
    }
    return { tris, share, level: T.level() };
  });
  const n = r.share.real + r.share.clay + r.share.none, pc = (k) => `${(100 * r.share[k] / n).toFixed(0)} %`;
  console.log(view.padEnd(9), `level ${r.level.toFixed(2)}`, `| in view: buildings ${(r.tris.buildings / 1e6).toFixed(2)} M, foliage ${(r.tris.foliage / 1e6).toFixed(2)} M, clay ${(r.tris.clay / 1e6).toFixed(2)} M, total ${((r.tris.buildings + r.tris.foliage + r.tris.clay) / 1e6).toFixed(2)} M`,
    `| screen: 1 m ${pc('real')}, clay ${pc('clay')}, outside blocks ${pc('none')}`);
  await page.close();
}
await browser.close();
