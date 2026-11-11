import { clamp } from '../util';

// One set of axes, -1..1, from the keys, the on-screen stick (touch.ts) and a gamepad (the browser's "standard" mapping:
// Xbox, PlayStation and most others). nav.ts reads them every frame and does not care which one moved.
//   move    forward / back      W/S, arrows; stick; left stick
//   strafe  sideways            stick; left stick
//   turn    yaw, right > 0      A/D, arrows; right stick
//   pitch   nose up > 0         Q/E; right stick
//   rise    up / down (air)     RT / LT
// Gamepad buttons fire once per press: A (street, jump), B (back up), LB / RB (an hour back / on).
export type Action = 'f' | 'b' | 'tl' | 'tr' | 'tu' | 'td';
export type Press = 'a' | 'b' | 'hourBack' | 'hourOn';
export const KEYMAP: Record<string, Action> = {
  KeyW: 'f', KeyS: 'b', KeyA: 'tl', KeyD: 'tr', KeyQ: 'tu', KeyE: 'td',
  ArrowUp: 'f', ArrowDown: 'b', ArrowLeft: 'tl', ArrowRight: 'tr',
};
const BUTTONS: [number, Press][] = [[0, 'a'], [1, 'b'], [4, 'hourBack'], [5, 'hourOn']];
const DEAD = 0.15; // sticks rest a little off centre
// past the dead zone, squared: fine near the centre, full speed at the rim
const shape = (v: number) => { const a = Math.abs(v); return a < DEAD ? 0 : Math.sign(v) * ((a - DEAD) / (1 - DEAD)) ** 2; };

export class Input {
  readonly keys = new Set<Action>();
  shift = false;
  readonly stick = { x: 0, y: 0 }; // the on-screen stick, y down
  pad = false;
  onPress: (p: Press) => void = () => {};
  onPad: (on: boolean) => void = () => {};
  private ax = [0, 0, 0, 0];
  private lt = 0;
  private rt = 0;
  private readonly held = new Set<number>();

  constructor() {
    addEventListener('gamepadconnected', () => this.poll());
    addEventListener('gamepaddisconnected', () => this.poll());
  }

  private key(pos: Action, neg: Action) { return (this.keys.has(pos) ? 1 : 0) - (this.keys.has(neg) ? 1 : 0); }

  // once a frame: the first connected gamepad, preferring one in the standard layout
  poll() {
    const pads = [...(navigator.getGamepads?.() ?? [])].filter((g): g is Gamepad => !!g?.connected);
    const gp = pads.find((g) => g.mapping === 'standard') ?? pads[0] ?? null;
    if (!!gp !== this.pad) { this.pad = !!gp; this.onPad(this.pad); }
    if (!gp) { this.ax = [0, 0, 0, 0]; this.lt = this.rt = 0; this.held.clear(); return; }
    this.ax = [0, 1, 2, 3].map((i) => shape(gp.axes[i] ?? 0));
    this.lt = gp.buttons[6]?.value ?? 0;
    this.rt = gp.buttons[7]?.value ?? 0;
    for (const [i, p] of BUTTONS) {
      const down = !!gp.buttons[i]?.pressed;
      if (down && !this.held.has(i)) this.onPress(p);
      if (down) this.held.add(i); else this.held.delete(i);
    }
  }

  get move() { return clamp(this.key('f', 'b') - this.stick.y - this.ax[1], -1, 1); }
  get strafe() { return clamp(this.stick.x + this.ax[0], -1, 1); }
  get turn() { return clamp(this.key('tr', 'tl') + this.ax[2], -1, 1); }
  get pitch() { return clamp(this.key('tu', 'td') - this.ax[3], -1, 1); }
  get rise() { return this.rt - this.lt; }
  // faster on foot: Shift, or the right trigger
  get fast() { return this.shift || this.rt > 0.5; }
  // the feet asked to move (keys of any kind, or a stick pushed): what makes you take over the person you follow
  get walking() { return this.keys.size > 0 || Math.abs(this.move) > 0.2 || Math.abs(this.strafe) > 0.2; }
}
