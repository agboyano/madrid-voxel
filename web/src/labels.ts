import * as THREE from 'three';
import type { Rect } from './hud';
import type { Facts, Label } from './types';
import { $, el } from './util';
import type { World } from './world';

interface Pin {
  el: HTMLElement;
  txt: HTMLElement;
  p: THREE.Vector3;
  base: THREE.Vector3;
  R: number;
  occluded: boolean;
  w: number;
  h: number;
  far: number;
  level: number;
  dims: [number, number][];
  shift: number;
  on: boolean;
  side: 'r' | 'l' | 's';
  since: number;
  at: number; // where the label was last moved to, in tenths of a pixel (x * 1e5 + y)
}
export interface Placed extends Facts { x: number; y: number; z: number }

const details = (f: Facts) => [f.en && f.kind, f.height && `${f.height} m`, f.year, f.rebuilt && `rebuilt ${f.rebuilt}`, f.by, f.building && 'under construction'].filter(Boolean);
const levelAt = (d: number, far: number) => d < Math.max(250, Math.min(far * 0.3, 900)) ? 2 : 0;

const STEM = 20, TOP = 8, MAX = 12, SETTLE = 150;
const overlap = (r: Rect, q: Rect) => r.x0 < q.x1 + 6 && r.x1 + 6 > q.x0 && r.y0 < q.y1 + 2 && r.y1 + 2 > q.y0;
const setRect = (r: Rect, x0: number, x1: number, y0: number, y1: number) => { r.x0 = x0; r.x1 = x1; r.y0 = y0; r.y1 = y1; };
// major labels first, then the shown ones; the sort is stable, so the list order breaks ties
const rank = (p: Pin) => (p.far >= 9000 ? 0 : 2) + (p.on ? 0 : 1);
const byRank = (a: Pin, b: Pin) => rank(a) - rank(b);
// the sides to try: a shown label first where it is
const SIDES = { r: ['r', 'l', 's'], l: ['l', 'r', 's'], s: ['s', 'r', 'l'], new: ['r', 'l', 's'] } as const;

// Map pins: a dot on the roof, a hairline stem, the name above. Hidden when something else is in the way (a voxel
// ray) or when a more important label is there; the MAX most important ones in view, however far. The major ones
// first, then the shown ones keep their place before newcomers are fitted, and a newcomer fades in only after holding a free spot for SETTLE ms.
export class Labels {
  gate: (x: number, z: number) => boolean = () => true;
  private readonly host = $('#labels');
  private readonly pins: Pin[] = [];
  private picked: Pin | null = null;
  private frame = 0;
  // reused every frame, so placing labels allocates only for what gets placed
  private readonly order: Pin[] = [];
  private readonly placed: Rect[] = [];
  private readonly rects = { r: { x0: 0, x1: 0, y0: 0, y1: 0 }, l: { x0: 0, x1: 0, y0: 0, y1: 0 }, s: { x0: 0, x1: 0, y0: 0, y1: 0 } };

  constructor(labels: Label[], onClick: (l: Label) => void) {
    labels.forEach((l) => {
      const pin = this.add(`label${(l.far ?? 0) >= 9000 ? ' major' : ''}`, l,
        new THREE.Vector3(l.x + 0.5, l.z + 1, l.y + 0.5), new THREE.Vector3(l.x + 0.5, (l.g ?? 0) + 2, l.y + 0.5), (l.R ?? 30) + 6);
      pin.txt.addEventListener('click', () => {
        onClick(l);
      });
      this.pins.push(pin);
    });
    document.fonts?.ready.then(() => { for (const p of this.pins) p.dims = []; });
  }

  private add(cls: string, f: Facts, p: THREE.Vector3, base: THREE.Vector3, R: number): Pin {
    const facts = details(f).map((d) => `<span>${d}</span>`).join('');
    const e = el('div', cls, `<i class="dot"></i><i class="stem"></i><div class="txt"><b>${f.name}</b><span>${f.en ?? f.kind}</span>${facts ? `<p>${facts}</p>` : ''}</div>`, this.host);
    return { el: e, txt: $('.txt', e), p, base, R, occluded: false, w: 0, h: 0, far: f.far ?? 1300, level: -1, dims: [], shift: 0, on: false, side: 'r', since: -1, at: NaN };
  }

  // a temporary label on a searched place
  pin(p: Placed | null) {
    if (this.picked) { this.picked.el.remove(); this.pins.splice(this.pins.indexOf(this.picked), 1); this.picked = null; }
    if (!p) return;
    this.picked = this.add('label pick', { ...p, far: 1e9 }, new THREE.Vector3(p.x + 0.5, p.z + 1, p.y + 0.5), new THREE.Vector3(p.x + 0.5, p.z, p.y + 0.5), 40);
    this.pins.unshift(this.picked);
  }

  update(camera: THREE.Camera, world: World | null, bar: DOMRect, obstacles: Rect[]) {
    if (world) this.checkOcclusion(camera, world);
    const placed = this.placed, rects = this.rects, order = this.order;
    placed.length = 0;
    if (bar.width) placed.push({ x0: bar.left - 8, x1: bar.right, y0: bar.top, y1: bar.bottom + 8 });
    for (const o of obstacles) placed.push(o);
    const free = (r: Rect) => {
      if (r.x0 < 4 || r.x1 > innerWidth - 4 || r.y0 < 4 || r.y1 > innerHeight - 4) return false;
      for (const q of placed) if (overlap(r, q)) return false;
      return true;
    };
    const under = (x: number) => bar.width > 0 && x > bar.left - 8 && x - 4 < bar.right;
    const v = new THREE.Vector3(), now = performance.now();
    let shown = 0;
    order.length = 0;
    for (const p of this.pins) order.push(p);
    order.sort(byRank);
    for (const L of order) {
      v.copy(L.p).project(camera);
      const inFront = v.z < 1, d = camera.position.distanceTo(L.p);
      let x = (v.x * 0.5 + 0.5) * innerWidth, y = (-v.y * 0.5 + 0.5) * innerHeight;
      this.setLevel(L, levelAt(d, L.far));
      [L.w, L.h] = L.dims[L.level];
      let fits = false, side = L.side, pinned = false;
      if (shown < MAX && !L.occluded && inFront && x > -20 && x < innerWidth + 20 && this.gate(L.p.x, L.p.z)) {
        // the roof above the screen but the building in view: the label pinned to the top edge
        if (y < TOP + STEM + L.h && y > -innerHeight * 0.8) {
          v.copy(L.base).project(camera);
          if (v.z < 1 && (-v.y * 0.5 + 0.5) * innerHeight > TOP + STEM + L.h + 30) {
            y = TOP + L.h + 4; pinned = true;
            if (under(x)) y = Math.max(y, bar.bottom + 20 + L.h);
          }
        }
        if (under(x) && y - STEM - L.h < bar.bottom + 12 && y > bar.top) { y = Math.max(y, bar.bottom + 20 + L.h); pinned = true; }
        if (y <= innerHeight + 4) {
          const st = pinned ? 4 : STEM, y0 = y - st - L.h, y1 = y + 4;
          const sx = Math.min(Math.max(x - L.w / 2, 4), innerWidth - L.w - 4);
          setRect(rects.r, x - 4, x + L.w, y0, y1);
          setRect(rects.l, x - L.w, x + 4, y0, y1);
          setRect(rects.s, sx, sx + L.w, y0, y1);
          for (const k of SIDES[L.on ? L.side : 'new']) {
            if ((k !== 's' || L.w < innerWidth - 8) && free(rects[k])) {
              fits = true; side = k; placed.push({ ...rects[k] }); if (k === 's') L.shift = sx - x;
              break;
            }
          }
        }
      }
      if (fits) { shown++; if (L.since < 0) L.since = now; } else L.since = -1;
      const vis = fits && (L.on || now - L.since >= SETTLE);
      if (vis) { L.side = side; L.el.classList.toggle('left', side === 'l'); L.el.classList.toggle('pinned', pinned); L.txt.style.left = side === 's' ? `${L.shift.toFixed(0)}px` : ''; }
      L.on = vis;
      L.el.classList.toggle('off', !vis);
      if (inFront) { // unchanged for a still view: no style write, no restyle
        const at = Math.round(x * 10) * 1e5 + Math.round(y * 10);
        if (at !== L.at) { L.at = at; L.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`; }
      }
    }
  }

  private setLevel(L: Pin, level: number) {
    if (L.level === level && L.dims[level]) return;
    L.level = level;
    L.el.classList.toggle('near', level === 2);
    L.dims[level] ??= [L.txt.offsetWidth || 160, L.txt.offsetHeight || 30];
  }

  // a few labels per frame: hidden by something other than the labelled building itself
  private checkOcclusion(camera: THREE.Camera, world: World) {
    const dir = new THREE.Vector3();
    for (let k = 0; k < 4 && this.pins.length; k++) {
      const L = this.pins[this.frame++ % this.pins.length];
      dir.subVectors(L.p, camera.position);
      const dist = dir.length();
      dir.divideScalar(dist);
      const t = world.raycast(camera.position, dir, dist);
      const hx = camera.position.x + dir.x * t - L.p.x, hz = camera.position.z + dir.z * t - L.p.z;
      L.occluded = t < dist - 3 && hx * hx + hz * hz > L.R * L.R;
    }
  }
}
