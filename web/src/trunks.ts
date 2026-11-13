import * as THREE from 'three';
import type { TileStreamer } from './stream';
import type { Meta } from './types';
import { dataUrl, fetchGzip, hash } from './util';
import { ZONES_PARS, type VoxelUniforms } from './voxelMaterial';

// Tree trunks and their bare branches (scripts/trunks.py: trunks.bin), drawn at their own width instead of as 1 m
// voxel columns: one instanced mesh of thin boxes per 1 m foliage tile, shown and freed with it (stream.ts, city.ts).
// Deciduous trees get a central leader and a few limbs into the crown the LiDAR measured: hidden by the leaf voxels in
// summer, the tree's shape in winter. Evergreens get only the trunk.

const REC = 16; // bytes per trunk: x, y f32; z u16; hb, ht, top, r, d, flags u8
const EVERGREEN = 1, YOUNG = 4;
const BARK = new THREE.Color(1, 1, 1), LIMB = new THREE.Color(0.88, 0.9, 0.93); // tints of the material's bark colour

export class Trunks {
  private readonly data: DataView;
  private readonly byTile = new Map<number, number[]>();
  private readonly geo: THREE.BufferGeometry;
  private readonly mat: THREE.MeshStandardMaterial;
  private readonly cell: number; // metres to cells
  private readonly nx: number;
  readonly minTrunk: number; // m: the narrowest trunk drawn (a 17 cm trunk is under a pixel a street away)
  readonly minLimb: number;
  private bare = true; // limbs shown: off while the city is in full leaf (they would only poke out under low crowns)
  private inLeaf: [number, number] | null = null;
  private S: TileStreamer | null = null;

  constructor(buf: ArrayBuffer, meta: Meta, U: VoxelUniforms, N: number, opts: { minTrunk?: number } = {}) {
    this.data = new DataView(buf);
    this.cell = 1 / (meta.voxel ?? 1);
    this.minTrunk = opts.minTrunk ?? 0.25;
    this.minLimb = Math.min(0.12, this.minTrunk * 0.5);
    const nx = Math.ceil(meta.W / N);
    for (let i = 0, n = buf.byteLength / REC; i < n; i++) {
      const k = Math.floor(this.data.getFloat32(i * REC + 4, true) / N) * nx + Math.floor(this.data.getFloat32(i * REC, true) / N);
      const list = this.byTile.get(k);
      if (list) list.push(i); else this.byTile.set(k, [i]);
    }
    this.nx = nx;
    // a box from y = 0 to 1 without its end caps (they sit inside the crown or the ground)
    const box = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), idx = box.index!.array, keep: number[] = [];
    for (const g of box.groups) if (g.materialIndex !== 2 && g.materialIndex !== 3) for (let j = g.start; j < g.start + g.count; j++) keep.push(idx[j]);
    box.setIndex(keep);
    box.clearGroups();
    this.geo = box;
    this.mat = new THREE.MeshStandardMaterial({ color: 0x65574a, roughness: 0.95, metalness: 0 });
    this.mat.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, { uZOn: U.uZOn, uZBlk: U.uZBlk, uZFBlk: U.uZFBlk, uSnow: U.uSnow });
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec3 vWp; varying float vUp;')
        .replace('#include <begin_vertex>', `#include <begin_vertex>
          vWp = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
          vUp = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * objectNormal).y;`);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>\n${ZONES_PARS}\nuniform float uSnow; varying vec3 vWp; varying float vUp;`)
        // where the budget leaves the block to the 8 m clay, the clay has the tree; snow lies on what faces up
        .replace('#include <color_fragment>', `#include <color_fragment>
          if (!zreal(floor(vWp))) discard;
          diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.86, 0.88, 0.92), uSnow * smoothstep(0.35, 0.75, vUp));`);
    };
    this.mat.customProgramCacheKey = () => 'trunks';
  }

  static async load(meta: Meta, U: VoxelUniforms, N: number, opts: { minTrunk?: number } = {}) {
    return new Trunks(await fetchGzip(dataUrl('trunks.bin')), meta, U, N, opts);
  }

  // every trunk and limb on a 1 m tile, as one instanced mesh (none if the tile has no trees)
  tile(tx: number, ty: number): THREE.InstancedMesh | undefined {
    const ids = this.byTile.get(ty * this.nx + tx);
    if (!ids) return undefined;
    const segs: number[] = []; // ax, ay, az, bx, by, bz, width, limb
    for (const i of ids) this.tree(i, segs);
    // trunks first, then limbs: in full leaf the mesh draws only the first `trunks` instances
    const order = [...Array(segs.length / 8).keys()].sort((p, q) => segs[p * 8 + 7] - segs[q * 8 + 7]);
    const n = order.length, mesh = new THREE.InstancedMesh(this.geo, this.mat, n);
    mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), a = new THREE.Vector3(),
      d = new THREE.Vector3(), s = new THREE.Vector3(), c = new THREE.Color();
    let trunks = 0;
    for (let k = 0; k < n; k++) {
      const o = order[k] * 8;
      if (!segs[o + 7]) trunks++;
      a.set(segs[o], segs[o + 1], segs[o + 2]);
      d.set(segs[o + 3], segs[o + 4], segs[o + 5]).sub(a);
      const len = d.length();
      q.setFromUnitVectors(up, d.divideScalar(len));
      mesh.setMatrixAt(k, m.compose(a, q, s.set(segs[o + 6], len, segs[o + 6])));
      const v = 0.88 + 0.24 * hash(a.x * 0.37 + a.z * 1.91 + k);
      mesh.setColorAt(k, c.copy(segs[o + 7] ? LIMB : BARK).multiplyScalar(v));
    }
    mesh.computeBoundingSphere();
    mesh.userData.all = n;
    mesh.userData.trunks = trunks;
    mesh.count = this.bare ? n : trunks;
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.matrixAutoUpdate = false;
    return mesh;
  }

  private tree(i: number, out: number[]) {
    const v = this.data, o = i * REC, C = this.cell;
    const x = v.getFloat32(o, true), y = v.getFloat32(o + 4, true), z = v.getUint16(o + 8, true);
    const hb = v.getUint8(o + 10), ht = v.getUint8(o + 11), top = v.getUint8(o + 12);
    const R = v.getUint8(o + 13) / 10 * C, flags = v.getUint8(o + 15);
    const D = Math.max(v.getUint8(o + 14) / 100, this.minTrunk) * C, minL = this.minLimb * C;
    const rnd = (k: number) => hash(x * 12.9898 + y * 78.233 + k * 37.719);
    const seg = (ax: number, ay: number, az: number, bx: number, by: number, bz: number, w: number, limb: number) =>
      out.push(ax, ay, az, bx, by, bz, Math.max(w, minL), limb);
    if (flags & YOUNG) { // a young tree: its clear trunk, a thin leader up through the narrow crown, three twigs
      seg(x, z, y, x, z + hb, y, D, 0);
      seg(x, z + hb, y, x, z + Math.max(ht, hb + 1), y, D * 0.6, 1);
      if (!(flags & EVERGREEN)) for (let k = 0; k < 3; k++) {
        const az = (k + rnd(k)) * 2.094, h0 = z + hb + (ht - hb) * (0.2 + 0.25 * k);
        seg(x, h0, y, x + Math.cos(az) * 1.1 * C, h0 + 1.3 * C, y + Math.sin(az) * 1.1 * C, D * 0.35, 1);
      }
      return;
    }
    seg(x, z, y, x, z + hb + (flags & EVERGREEN ? 0.5 : 0.3), y, D, 0); // into the crown's underside
    const ch = top - hb;
    if (flags & EVERGREEN || ch < 1.5 || R < 0.8 * C) return;
    // a deciduous crown: a leader halfway up and 3-5 limbs fanning out at 35-55 degrees, their ends within the crown
    // (out to 2/3 of its radius, up to 3/4 of its depth); the bigger crowns fork once more along each limb
    const n = Math.min(5, Math.max(3, Math.round(2 + R / C / 2.5))), w = D * 0.9 / Math.sqrt(n), h0 = z + hb;
    seg(x, h0 - 0.2, y, x, h0 + 0.55 * ch, y, D * 0.5, 1);
    const rot = rnd(0) * Math.PI * 2;
    for (let k = 0; k < n; k++) {
      const az = rot + (k + 0.6 * (rnd(k + 1) - 0.5)) * 2 * Math.PI / n, el = (35 + 20 * rnd(k + 11)) * Math.PI / 180;
      const lh = R * (0.5 + 0.15 * rnd(k + 21)), rise = Math.min(lh * Math.tan(el), 0.75 * ch);
      const bx = x + Math.cos(az) * lh, by = h0 + rise, bz = y + Math.sin(az) * lh;
      seg(x, h0 - 0.2, y, bx, by, bz, w, 1);
      if (R < 2.5 * C) continue;
      for (const side of R < 4 * C ? [k % 2 ? 1 : -1] : [1, -1]) { // forks from 60 % along the limb, outwards and up
        const px = x + (bx - x) * 0.6, py = h0 + rise * 0.6, pz = y + (bz - y) * 0.6, a2 = az + side * 0.6;
        const l2 = lh * 0.45, r2 = Math.min(l2 * Math.tan(el + 0.25), h0 + 0.8 * ch - py);
        seg(px, py, pz, px + Math.cos(a2) * l2, py + Math.max(r2, 0.2), pz + Math.sin(a2) * l2, w * 0.6, 1);
      }
    }
  }

  // the days the city is in full leaf (foliage.ts: the medians of leafing out and turning), limbs hidden
  setLeafDays(leaf: number, colour: number) { this.inLeaf = [leaf + 20, colour - 20]; }

  season(day: number) {
    const bare = !this.inLeaf || day < this.inLeaf[0] || day > this.inLeaf[1];
    if (bare === this.bare) return;
    this.bare = bare;
    for (const n of this.S?.nodes.values() ?? []) if (n.extra) n.extra.count = bare ? n.extra.userData.all : n.extra.userData.trunks;
  }

  // trunks for the foliage tiles already in (the file came after them)
  attachAll(S: TileStreamer) {
    this.S = S;
    S.onFoliage = (tx, ty) => this.tile(tx, ty);
    for (const n of S.nodes.values()) if (n.foliage && n.state === 'ready') S.attachExtra(n);
  }
}
