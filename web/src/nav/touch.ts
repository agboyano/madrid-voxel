import type { Rect } from '../hud';
import { el } from '../util';
import type { Mode, Nav, Ride } from './nav';

const HINT_KEY = 'madrid-voxel.touch-hints';
const HINTS: Partial<Record<Mode, string>> = {
  orbit: 'Drag to move · pinch to zoom · two fingers to turn · tap a person to follow',
  walk: 'Stick to walk · drag to look · tap the street to go there',
};

// On a touch screen (pointer: coarse): a stick bottom left to walk forward, back and sideways while the other thumb
// still drags to look, and buttons bottom right for what has no gesture -- down to the street, jump, back up. The
// first time in each mode, a line of gesture help that fades away.
export class TouchControls {
  rects: Rect[] = [];
  private readonly box = el('div', '');
  private readonly hint = el('div', '');
  private readonly seen = new Set<string>();
  private hintT = 0;

  constructor(private readonly nav: Nav) {
    const box = this.box;
    box.id = 'touch';
    box.innerHTML = `<div class="stick"><i></i></div><div class="btns">
      <button data-a="walk">Walk here</button><button data-a="jump">Jump</button><button data-a="up">Fly up</button></div>`;
    this.hint.id = 'touch-hint';
    try { for (const m of JSON.parse(localStorage.getItem(HINT_KEY) ?? '[]')) this.seen.add(m); } catch { /* private window */ }
    box.querySelectorAll<HTMLButtonElement>('button').forEach((b) => b.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      const a = b.dataset.a;
      if (a === 'walk') nav.land();
      else if (a === 'jump') nav.jump();
      else nav.flyUp();
    }));
    this.bindStick(box.querySelector<HTMLElement>('.stick')!);
    new ResizeObserver(() => this.measure()).observe(box);
    addEventListener('resize', () => this.measure());
    this.set(nav.mode, null);
  }

  // what the map labels keep clear of: the stick and the buttons on show
  private measure() {
    this.rects = [...this.box.querySelectorAll<HTMLElement>('.stick, button')].filter((n) => n.offsetParent).map((n) => {
      const r = n.getBoundingClientRect();
      return { x0: r.left - 6, x1: r.right + 6, y0: r.top - 6, y1: r.bottom + 6 };
    });
  }

  // the knob follows the thumb within the ring; its offset over the radius is the stick, -1..1 each way
  private bindStick(ring: HTMLElement) {
    const knob = ring.querySelector('i')!, stick = this.nav.input.stick;
    let id: number | null = null;
    const at = (e: PointerEvent) => {
      const r = ring.getBoundingClientRect(), R = r.width / 2;
      let x = (e.clientX - r.left - R) / R, y = (e.clientY - r.top - R) / R;
      const L = Math.hypot(x, y);
      if (L > 1) { x /= L; y /= L; }
      stick.x = x; stick.y = y;
      knob.style.transform = `translate(${x * R * 0.6}px, ${y * R * 0.6}px)`;
    };
    const end = () => { id = null; stick.x = stick.y = 0; knob.style.transform = ''; ring.classList.remove('on'); };
    ring.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      id = e.pointerId;
      ring.setPointerCapture(id);
      ring.classList.add('on');
      at(e);
    });
    ring.addEventListener('pointermove', (e) => { if (e.pointerId === id) at(e); });
    ring.addEventListener('pointerup', (e) => { if (e.pointerId === id) end(); });
    ring.addEventListener('pointercancel', (e) => { if (e.pointerId === id) end(); });
  }

  set(mode: Mode, ride: Ride | null) {
    this.box.dataset.mode = mode;
    this.box.classList.toggle('person', ride?.kind === 'person');
    requestAnimationFrame(() => this.measure());
    this.showHint(mode);
  }

  private showHint(mode: Mode) {
    const text = HINTS[mode];
    if (!text || this.seen.has(mode)) return;
    this.seen.add(mode);
    try { localStorage.setItem(HINT_KEY, JSON.stringify([...this.seen])); } catch { /* private window */ }
    this.hint.textContent = text;
    this.hint.classList.add('on');
    clearTimeout(this.hintT);
    this.hintT = setTimeout(() => this.hint.classList.remove('on'), 6000);
  }
}
