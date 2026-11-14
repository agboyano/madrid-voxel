import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

export const MAX_CARS = 1400, MAX_PEOPLE = 4000, MAX_TRAM_SECTIONS = 240, MAX_BIKES = 1200;

function box(w: number, h: number, l: number, x: number, y: number, z: number, hex?: number) {
  const g = new THREE.BoxGeometry(w, h, l).translate(x, y + h / 2, z);
  if (hex === undefined) return g;
  const c = new THREE.Color(hex), a = new Float32Array(g.attributes.position.count * 3);
  for (let i = 0; i < a.length; i += 3) a.set([c.r, c.g, c.b], i);
  g.setAttribute('color', new THREE.BufferAttribute(a, 3));
  return g;
}
const merge = (...gs: THREE.BufferGeometry[]) => mergeGeometries(gs);
const std = (o: THREE.MeshStandardMaterialParameters) => new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.25, ...o });

function instanced(geo: THREE.BufferGeometry, mat: THREE.Material, n: number, { shadow = false, color = false } = {}) {
  const m = new THREE.InstancedMesh(geo, mat, n);
  m.castShadow = shadow;
  m.receiveShadow = shadow;
  m.frustumCulled = false;
  if (color) m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3);
  return m;
}

// instanced meshes for every car, tram section, person and signal head; the simulation writes their matrices
export class LifeMeshes {
  readonly group = new THREE.Group();
  readonly body: THREE.InstancedMesh;
  readonly dark: THREE.InstancedMesh;
  readonly head: THREE.InstancedMesh;
  readonly tail: THREE.InstancedMesh;
  readonly tram: THREE.InstancedMesh;
  readonly tramWin: THREE.InstancedMesh;
  readonly legs: THREE.InstancedMesh;
  readonly torso: THREE.InstancedMesh;
  readonly pole: THREE.InstancedMesh;
  readonly bike: THREE.InstancedMesh;
  readonly lamp: THREE.InstancedMesh;
  readonly headMat = new THREE.MeshBasicMaterial({ color: 0xfff3dd });
  readonly tramWinMat = std({ color: 0x26323d, roughness: 0.15, metalness: 0.4, emissive: new THREE.Color(1.0, 0.82, 0.55), emissiveIntensity: 0 });

  constructor(scene: THREE.Scene, heads: [number, number, number, number, ...number[]][], tramSection: number) {
    const C = MAX_CARS, wheel = (x: number, z: number) => box(0.3, 0.6, 0.7, x, 0, z, 0x161616);
    this.body = instanced(merge(box(1.8, 0.75, 4.4, 0, 0.3, 0), box(1.62, 0.62, 2.3, 0, 1.05, -0.25)), std({ color: 0xffffff }), C, { shadow: true, color: true });
    this.dark = instanced(merge(box(1.66, 0.5, 2.2, 0, 1.1, -0.25, 0x1d2329), wheel(-0.8, 1.3), wheel(0.8, 1.3), wheel(-0.8, -1.35), wheel(0.8, -1.35)),
      std({ vertexColors: true, roughness: 0.15, metalness: 0.5 }), C, { shadow: true });
    this.head = instanced(merge(box(0.4, 0.2, 0.1, -0.6, 0.65, 2.2), box(0.4, 0.2, 0.1, 0.6, 0.65, 2.2)), this.headMat, C);
    this.tail = instanced(merge(box(0.4, 0.2, 0.1, -0.6, 0.7, -2.2), box(0.4, 0.2, 0.1, 0.6, 0.7, -2.2)), new THREE.MeshBasicMaterial({ color: 0xffffff }), C, { color: true });
    const L = tramSection; // default livery (Warsaw's: yellow body, red skirt, light roof gear); no trams in central Madrid
    this.tram = instanced(merge(box(2.4, 0.9, L, 0, 0.15, 0, 0xc8322b), box(2.4, 1.9, L, 0, 1.05, 0, 0xf2c230), box(2.0, 0.35, L - 0.8, 0, 2.95, 0, 0xd9d6cf)),
      std({ vertexColors: true, roughness: 0.45, metalness: 0.1 }), MAX_TRAM_SECTIONS, { shadow: true });
    this.tramWin = instanced(box(2.46, 0.85, L - 1.2, 0, 1.6, 0), this.tramWinMat, MAX_TRAM_SECTIONS);
    const P = MAX_PEOPLE + MAX_BIKES;
    this.legs = instanced(merge(box(0.18, 0.85, 0.22, -0.1, 0, 0, 0x2b3240), box(0.18, 0.85, 0.22, 0.1, 0, 0, 0x2b3240),
      box(0.3, 0.3, 0.3, 0, 1.45, 0, 0xe0b48f), box(0.32, 0.1, 0.32, 0, 1.72, 0, 0x3a2a20)), std({ vertexColors: true, roughness: 0.9, metalness: 0 }), P);
    this.torso = instanced(box(0.46, 0.62, 0.3, 0, 0.85, 0), std({ color: 0xffffff, roughness: 0.9, metalness: 0 }), P, { color: true });
    this.legs.castShadow = this.torso.castShadow = true;
    const wheelB = (z: number) => box(0.07, 0.68, 0.68, 0, 0, z, 0x1a1a1a);
    this.bike = instanced(merge(wheelB(-0.55), wheelB(0.55), box(0.06, 0.07, 1.05, 0, 0.62, 0, 0x8c8f93), box(0.06, 0.5, 0.06, 0, 0.3, -0.18, 0x8c8f93),
      box(0.5, 0.05, 0.05, 0, 1.0, 0.5, 0x2b2b2b)), std({ vertexColors: true, roughness: 0.5, metalness: 0.4 }), MAX_BIKES, { shadow: true });
    const H = Math.max(1, heads.length);
    this.pole = instanced(merge(box(0.18, 3.3, 0.18, 0, 0, 0, 0x3a3e42), box(0.42, 1.25, 0.36, 0, 3.0, 0, 0x202225)), std({ vertexColors: true, roughness: 0.6 }), H);
    this.pole.castShadow = true;
    this.lamp = instanced(new THREE.BoxGeometry(0.3, 0.3, 0.1), new THREE.MeshBasicMaterial({ color: 0xffffff }), H, { color: true });
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), one = new THREE.Vector3(1, 1, 1);
    heads.forEach(([x, y, z, rot], i) => this.pole.setMatrixAt(i, m.compose(new THREE.Vector3(x, z, y), q.setFromAxisAngle(up, rot + Math.PI), one)));
    this.pole.count = heads.length;
    this.group.add(this.body, this.dark, this.head, this.tail, this.legs, this.torso, this.bike, this.pole, this.lamp, this.tram, this.tramWin);
    scene.add(this.group);
  }
}

// What reaches the GPU each frame (docs/sim-evaluation-plan.md). ranges (C1): only the instances in use, where three
// would otherwise send each buffer's whole capacity, 1.35 MB a frame for 0.1-0.5 MB in use; ?uprange=0 sends it all.
// cache (C2): signal lamps written when their phase changes, and the colours that never change (car bodies, shirts)
// only when an instance slot gets a new agent; ?sigcache=0 writes them every frame. Both set once by main.ts
export const UPLOAD = { ranges: true, cache: true };

// flags instances [start, start + count) of a buffer for upload
export function flagRange(a: THREE.BufferAttribute, start: number, count: number) {
  if (!UPLOAD.ranges) { a.needsUpdate = true; return; }
  if (count <= 0) return;
  a.addUpdateRange(start * a.itemSize, count * a.itemSize);
  a.needsUpdate = true;
}

// n instances drawn, their matrices (and, unless kept, colours) sent; nothing is sent while there are none
export function setCount(n: number, ...meshes: THREE.InstancedMesh[]) {
  for (const m of meshes) setCountOf(m, n, true);
}
export function setCountOf(m: THREE.InstancedMesh, n: number, colour: boolean) {
  m.count = n;
  flagRange(m.instanceMatrix, 0, n);
  if (m.instanceColor && (colour || !UPLOAD.cache)) flagRange(m.instanceColor, 0, n);
}

// a colour that stays with its agent: written only when slot i holds an agent it did not hold last frame. Returns
// whether it wrote; the caller flags the slots written (Slots.flag)
export class Slots {
  private owner: unknown[] = [];
  private lo = Infinity;
  private hi = -1;
  set(m: THREE.InstancedMesh, i: number, who: unknown, col: THREE.Color) {
    if (UPLOAD.cache && this.owner[i] === who) return;
    this.owner[i] = who;
    m.setColorAt(i, col);
    if (i < this.lo) this.lo = i;
    if (i > this.hi) this.hi = i;
  }
  flag(m: THREE.InstancedMesh) {
    if (!m.instanceColor) return;
    if (!UPLOAD.cache) return; // setCountOf sent them all
    if (this.hi >= this.lo) flagRange(m.instanceColor, this.lo, this.hi - this.lo + 1);
    this.lo = Infinity; this.hi = -1;
  }
}
