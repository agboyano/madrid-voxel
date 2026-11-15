import * as THREE from 'three';
import type { Meta } from './types';
import { dataUrl, fetchGzip } from './util';
import { ZONES_PARS, type VoxelUniforms } from './voxelMaterial';

// Street lamps (scripts/lamps.py: lamps.bin), drawn at their own width instead of as 1 m voxels. Three draw calls
// whatever the view: the posts' iron and the lanterns as two instanced meshes of thin boxes for the lamps near the
// camera (rewritten only when it has moved NEAR_STEP), and every lantern as one point beyond, at night only. A 15 cm post
// is under a pixel 200 m away and a lantern 600 m away, so geometry further out would cost vertices and show nothing.
// Their light on the ground is baked (lampmap.bin, voxelMaterial.ts); none of them casts a shadow.

const REC = 16; // bytes per lamp: x, y f32; z u16; height, style, heading, arms, light, flags u8
const VILLA = 0, FERNANDINO = 1, GLOBE = 2, MODERN = 3;
const WALL = 1;
const CELL = 64; // m: the grid the lamps are indexed by
const NEAR_STEP = 50; // m the camera moves before the near lamps are rewritten
const MAX_NEAR = 3000; // lamps drawn as geometry at most (the nearest, if more are in range)
const IRON_PER_LAMP = 4, LANTERN_PER_LAMP = 2;
// lantern colours: warm white LED, sodium amber, both (lampmap.py's warmth)
const LIGHT = [new THREE.Color(1.0, 0.86, 0.68), new THREE.Color(1.0, 0.66, 0.32), new THREE.Color(1.0, 0.76, 0.5)];
const GLASS = new THREE.Color(0.32, 0.33, 0.33); // a lantern by day

// metres: [width, height] of each style's lantern, and a post's shaft width
const LANTERN: Record<number, [number, number]> = { [VILLA]: [0.42, 0.6], [FERNANDINO]: [0.4, 0.55], [GLOBE]: [0.42, 0.42], [MODERN]: [0.25, 0.14] };
const SHAFT: Record<number, number> = { [VILLA]: 0.16, [FERNANDINO]: 0.14, [GLOBE]: 0.12, [MODERN]: 0.16 };
const ARM = 1.4, HEAD = 0.65, BRACKET = 0.55; // a modern mast's arm and luminaire length, a wall bracket's reach

const POINTS_VERT = `
  uniform float uScale; uniform float uNear; uniform float uNight;
  attribute vec3 color; varying vec3 vC; varying float vA;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float d = -mv.z, px = 0.45 * uScale / d; // the lantern's width in pixels
    gl_PointSize = max(px, 1.5);
    // a lantern under the floor size keeps a share of its light, not all of it: the whole city would glare
    vA = uNight * smoothstep(uNear * 0.7, uNear, d) * clamp(px / 1.5, 0.35, 1.0);
    vC = color;
    gl_Position = projectionMatrix * mv;
  }`;
const POINTS_FRAG = `
  varying vec3 vC; varying float vA;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float a = clamp(1.0 - dot(p, p), 0.0, 1.0);
    gl_FragColor = vec4(vC * 3.0 * a * vA, 1.0);
  }`;

export class Lamps {
  readonly group = new THREE.Group();
  private readonly data: DataView;
  private readonly n: number;
  private readonly cells = new Map<number, number[]>();
  private readonly nx: number;
  private readonly C: number; // metres to cells
  private readonly iron: THREE.InstancedMesh;
  private readonly lantern: THREE.InstancedMesh;
  private readonly lanternMat: THREE.MeshBasicMaterial;
  private readonly points: THREE.Points;
  private readonly pointsMat: THREE.ShaderMaterial;
  private readonly at = new THREE.Vector2(Infinity, Infinity);
  private radius = 350; // m drawn as geometry
  private builtRadius = 0;
  private night = -1;

  constructor(buf: ArrayBuffer, meta: Meta, U: VoxelUniforms) {
    this.data = new DataView(buf);
    this.n = buf.byteLength / REC;
    this.C = 1 / (meta.voxel ?? 1);
    const cell = CELL * this.C;
    this.nx = Math.ceil(meta.W / cell);
    const pos = new Float32Array(this.n * 3), col = new Float32Array(this.n * 3);
    for (let i = 0; i < this.n; i++) {
      const o = i * REC, x = this.data.getFloat32(o, true), y = this.data.getFloat32(o + 4, true);
      const k = Math.floor(y / cell) * this.nx + Math.floor(x / cell);
      const list = this.cells.get(k);
      if (list) list.push(i); else this.cells.set(k, [i]);
      const [lx, ly, lz] = this.lanternAt(i);
      pos.set([lx, ly, lz], i * 3);
      const c = LIGHT[Math.min(this.data.getUint8(o + 14), 2)];
      col.set([c.r, c.g, c.b], i * 3);
    }

    const zoned = (mat: THREE.Material, key: string) => {
      mat.onBeforeCompile = (shader) => {
        Object.assign(shader.uniforms, { uZOn: U.uZOn, uZBlk: U.uZBlk, uZFBlk: U.uZFBlk });
        shader.vertexShader = shader.vertexShader
          .replace('#include <common>', '#include <common>\nvarying vec3 vWp;')
          .replace('#include <begin_vertex>', '#include <begin_vertex>\nvWp = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;');
        shader.fragmentShader = shader.fragmentShader
          .replace('#include <common>', `#include <common>\n${ZONES_PARS}\nvarying vec3 vWp;`)
          // where the budget leaves the block to the 8 m clay, the lamp would stand on ground that is not there
          .replace('#include <color_fragment>', '#include <color_fragment>\nif (!zreal(floor(vWp))) discard;');
      };
      mat.customProgramCacheKey = () => key;
      return mat;
    };
    // every part is a unit box centred on the origin, scaled and turned to the heading
    const box = new THREE.BoxGeometry(1, 1, 1);
    const mesh = (geo: THREE.BufferGeometry, mat: THREE.Material, n: number) => {
      const m = new THREE.InstancedMesh(geo, mat, n);
      m.frustumCulled = false;
      m.count = 0;
      m.matrixAutoUpdate = false;
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      return m;
    };
    this.iron = mesh(box, zoned(new THREE.MeshLambertMaterial({ color: 0x2c2e30 }), 'lamp-iron'), MAX_NEAR * IRON_PER_LAMP);
    this.lanternMat = zoned(new THREE.MeshBasicMaterial({ color: 0xffffff }), 'lamp-lantern') as THREE.MeshBasicMaterial;
    this.lantern = mesh(box, this.lanternMat, MAX_NEAR * LANTERN_PER_LAMP);
    this.lantern.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(MAX_NEAR * LANTERN_PER_LAMP * 3), 3);
    this.lantern.instanceColor.setUsage(THREE.DynamicDrawUsage);

    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    pg.setAttribute('color', new THREE.BufferAttribute(col, 3));
    this.pointsMat = new THREE.ShaderMaterial({
      uniforms: { uScale: { value: 1000 }, uNear: { value: this.radius * this.C }, uNight: { value: 0 } },
      vertexShader: POINTS_VERT, fragmentShader: POINTS_FRAG,
      blending: THREE.AdditiveBlending, depthWrite: false, transparent: true,
    });
    this.points = new THREE.Points(pg, this.pointsMat);
    this.points.frustumCulled = false;
    this.points.visible = false;
    this.group.add(this.iron, this.lantern, this.points);
  }

  static async load(meta: Meta, U: VoxelUniforms) {
    return new Lamps(await fetchGzip(dataUrl('lamps.bin')), meta, U);
  }

  // world position of lamp i's (first) lantern
  private lanternAt(i: number): [number, number, number] {
    const v = this.data, o = i * REC, C = this.C;
    const x = v.getFloat32(o, true), y = v.getFloat32(o + 4, true), z = v.getUint16(o + 8, true);
    const h = v.getUint8(o + 10) / 10 * C, style = v.getUint8(o + 11), a = v.getUint8(o + 12) / 256 * Math.PI * 2;
    const out = v.getUint8(o + 15) & WALL ? BRACKET * C : style === MODERN ? (ARM + HEAD / 2) * C : 0;
    return [x + Math.cos(a) * out, z + h, y + Math.sin(a) * out];
  }

  // the radius drawn as geometry, m (lower on slow GPUs: main.ts)
  setRadius(r: number) { this.radius = r; this.pointsMat.uniforms.uNear.value = r * this.C; }

  update(camera: THREE.PerspectiveCamera, night: number, heightPx: number) {
    const p = camera.position, C = this.C;
    if (Math.hypot(p.x - this.at.x, p.z - this.at.y) > NEAR_STEP * C || this.builtRadius !== this.radius) this.build(p.x, p.z);
    if (night !== this.night) {
      this.night = night;
      this.lanternMat.color.copy(GLASS).lerp(new THREE.Color(3.35, 3.35, 3.35), night);
      this.pointsMat.uniforms.uNight.value = night;
      this.points.visible = night > 0.01;
    }
    this.pointsMat.uniforms.uScale.value = heightPx / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
  }

  private build(px: number, pz: number) {
    this.at.set(px, pz);
    this.builtRadius = this.radius;
    const C = this.C, R = (this.radius + NEAR_STEP) * C, cell = CELL * C, R2 = R * R;
    const near: number[] = [], dist: number[] = [];
    const c0 = Math.floor((px - R) / cell), c1 = Math.floor((px + R) / cell);
    const r0 = Math.floor((pz - R) / cell), r1 = Math.floor((pz + R) / cell);
    for (let r = Math.max(r0, 0); r <= r1; r++) for (let c = Math.max(c0, 0); c <= Math.min(c1, this.nx - 1); c++) {
      for (const i of this.cells.get(r * this.nx + c) ?? []) {
        const dx = this.data.getFloat32(i * REC, true) - px, dz = this.data.getFloat32(i * REC + 4, true) - pz, d2 = dx * dx + dz * dz;
        if (d2 < R2) { near.push(i); dist.push(d2); }
      }
    }
    let ids = near;
    if (near.length > MAX_NEAR) ids = [...near.keys()].sort((a, b) => dist[a] - dist[b]).slice(0, MAX_NEAR).map((k) => near[k]);
    let ni = 0, nl = 0;
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), t = new THREE.Vector3(), s = new THREE.Vector3();
    const iron = (x: number, y: number, z: number, w: number, h: number, l: number, rot: number) => {
      this.iron.setMatrixAt(ni++, m.compose(t.set(x, y, z), q.setFromAxisAngle(up, rot), s.set(l, h, w)));
    };
    const lantern = (x: number, y: number, z: number, w: number, h: number, l: number, rot: number, c: THREE.Color) => {
      this.lantern.setMatrixAt(nl, m.compose(t.set(x, y, z), q.setFromAxisAngle(up, rot), s.set(l, h, w)));
      this.lantern.setColorAt(nl++, c);
    };
    const v = this.data;
    for (const i of ids) {
      const o = i * REC, x = v.getFloat32(o, true), y = v.getFloat32(o + 4, true), z = v.getUint16(o + 8, true);
      const h = v.getUint8(o + 10) / 10 * C, style = v.getUint8(o + 11), a = v.getUint8(o + 12) / 256 * Math.PI * 2;
      const arms = v.getUint8(o + 13), c = LIGHT[Math.min(v.getUint8(o + 14), 2)], wall = v.getUint8(o + 15) & WALL;
      const dx = Math.cos(a), dz = Math.sin(a), rot = -a; // a box's local x along the heading
      const [lw, lh] = LANTERN[style], sw = SHAFT[style] * C;
      if (wall) { // a bracket out of the facade, the lantern hanging from its end
        const r = BRACKET * C;
        iron(x + dx * r / 2, z + h + lh * C / 2 + 0.05 * C, y + dz * r / 2, 0.06 * C, 0.06 * C, r, rot);
        if (style === MODERN) lantern(x + dx * r, z + h, y + dz * r, lw * C, lh * C, HEAD * C, rot, c);
        else lantern(x + dx * r, z + h, y + dz * r, lw * C, lh * C, lw * C, rot, c);
        continue;
      }
      iron(x, z + 0.3 * C, y, sw * 2.2, 0.6 * C, sw * 2.2, rot); // the base
      if (style === MODERN) { // a mast and its arm(s), the luminaire under the arm's end
        iron(x, z + h / 2, y, sw, h, sw, rot);
        for (const side of arms > 1 ? [1, -1] : [1]) {
          const ax = dx * side, az = dz * side;
          iron(x + ax * ARM * C / 2, z + h, y + az * ARM * C / 2, 0.08 * C, 0.08 * C, ARM * C, rot);
          lantern(x + ax * (ARM + HEAD / 2) * C, z + h - 0.08 * C, y + az * (ARM + HEAD / 2) * C, lw * C, lh * C, HEAD * C, rot, c);
        }
        continue;
      }
      // a column with the lantern on top (two, on a crosspiece, for a two-arm post)
      iron(x, z + (h - lh * C / 2) / 2, y, sw, h - lh * C / 2, sw, rot);
      if (arms > 1) {
        iron(x, z + h - lh * C / 2, y, 0.08 * C, 0.08 * C, 1.0 * C, rot);
        for (const side of [1, -1]) lantern(x + dx * side * 0.5 * C, z + h, y + dz * side * 0.5 * C, lw * C, lh * C, lw * C, rot, c);
      } else {
        lantern(x, z + h, y, lw * C, lh * C, lw * C, rot, c);
        iron(x, z + h + lh * C / 2 + 0.06 * C, y, 0.12 * C, 0.12 * C, (lw + 0.1) * C, rot); // the lantern's cap
      }
    }
    this.iron.count = ni;
    this.lantern.count = nl;
    this.iron.instanceMatrix.clearUpdateRanges();
    this.iron.instanceMatrix.addUpdateRange(0, ni * 16);
    this.iron.instanceMatrix.needsUpdate = true;
    this.lantern.instanceMatrix.clearUpdateRanges();
    this.lantern.instanceMatrix.addUpdateRange(0, nl * 16);
    this.lantern.instanceMatrix.needsUpdate = true;
    this.lantern.instanceColor!.clearUpdateRanges();
    this.lantern.instanceColor!.addUpdateRange(0, nl * 3);
    this.lantern.instanceColor!.needsUpdate = true;
  }
}
