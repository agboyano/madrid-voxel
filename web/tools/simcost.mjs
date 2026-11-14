// What the street life costs (docs/sim-evaluation-plan.md, phase 0): per view and hour, the simulation on and off in
// A-B-B-A order in one page (window.__three.setLife), each sample 8 s after 2 s of warm-up. Reports the frame interval
// (mean, median, p95, p99; the browser's frame times come in steps of 16.7 ms, so the mean, 1 / fps, is the figure to
// compare), the main thread's time per frame and, with the simulation on, its logic and drawing time as main.ts logs
// them (?perf=sim), the steps per frame, the agents, and the instance bytes flagged for upload per frame against those
// in use. --cpu=N throttles the CPU N times (Chrome's Emulation.setCPUThrottlingRate), a stand-in for a weaker device's
// CPU; the GPU stays this machine's.
// usage: node tools/simcost.mjs [views, default street,sol,cibeles,overview] [hours, default 17,3] [query] [--cpu=4] [--out=file.json]
//        (dev server on :5173; $CHROMIUM picks the browser)
import fs from 'node:fs';
import { launch, seedRandom } from './launch.mjs';
const args = process.argv.slice(2), flag = (k) => args.find((a) => a.startsWith(`--${k}=`))?.split('=')[1];
const [views = 'street,sol,cibeles,overview', hours = '17,3', query = 'level=0.3'] = args.filter((a) => !a.startsWith('--'));
const cpu = +(flag('cpu') ?? 1), out = flag('out'), WARM = 2000, SAMPLE = 8000;
const browser = await launch();
const rows = [];
for (const view of views.split(',')) for (const hour of hours.split(',')) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.log('pageerror', e.message));
  await seedRandom(page); // the same agents every run
  await page.goto(`http://localhost:5173/?view=${view}&date=06-21&hour=${hour}&weather=clear&perf=sim${query ? `&${query}` : ''}`);
  await page.waitForFunction(() => window.__ready && window.__life && !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 500 });
  await page.waitForFunction(() => { const s = window.__streamer, c = window.__three.city(); return s.inflight === 0 && s.queue.length === 0 && c.settled; }, null, { timeout: 900000, polling: 500 });
  await page.waitForTimeout(30000); // the population fills toward its target
  if (cpu > 1) { const cdp = await page.context().newCDPSession(page); await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpu }); }
  const sample = (on) => page.evaluate(async ([on, WARM, SAMPLE]) => {
    const T = window.__three, L = window.__life, log = T.simLog();
    T.setLife(on);
    await new Promise((r) => setTimeout(r, WARM));
    const attrs = []; L.group.traverse((o) => { if (o.isInstancedMesh) { attrs.push([o, o.instanceMatrix, 64]); if (o.instanceColor) attrs.push([o, o.instanceColor, 12]); } });
    // bytes sent: the update ranges flagged (three sends only those), or the whole buffer when none was set
    const ranged = attrs.map(() => 0);
    attrs.forEach(([, a], i) => { const f = a.addUpdateRange.bind(a); a.addUpdateRange = (start, count) => { ranged[i] += count * 4; return f(start, count); }; });
    let v0 = attrs.map(([, a]) => a.version), flagged = 0, used = 0, n = 0, run = true;
    const tick = () => { // after the app's own callback each frame: what it flagged, and what it uses
      attrs.forEach(([m, a, b], i) => {
        if (a.version !== v0[i]) { flagged += ranged[i] || a.array.byteLength; used += m.count * b; v0[i] = a.version; }
        ranged[i] = 0;
      });
      n++; if (run) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    const t0 = performance.now();
    await new Promise((r) => setTimeout(r, SAMPLE));
    run = false;
    const f = log.filter((x) => x.t >= t0), iv = f.slice(1).map((x, i) => x.t - f[i].t).sort((a, b) => a - b);
    const q = (p) => iv[Math.min(iv.length - 1, Math.floor(iv.length * p))], mean = (k) => f.reduce((a, x) => a + x[k], 0) / f.length;
    return { frames: f.length, interval: iv.reduce((a, x) => a + x, 0) / iv.length, median: q(0.5), p95: q(0.95), p99: q(0.99), main: mean('main'), step: mean('step'), render: mean('render'), steps: mean('steps'),
      flaggedKB: flagged / n / 1024, usedKB: used / n / 1024, cars: L.cars.length, people: L.people.length, riders: L.riders.length };
  }, [on, WARM, SAMPLE]);
  const r = { A1: await sample(true), B1: await sample(false), B2: await sample(false), A2: await sample(true) };
  await page.close();
  const avg = (k, a, b) => (r[a][k] + r[b][k]) / 2, on = (k) => avg(k, 'A1', 'A2'), off = (k) => avg(k, 'B1', 'B2');
  const row = { view, hour, cpu, query, ...r };
  rows.push(row);
  const f1 = (x) => x.toFixed(1);
  console.log(`${view.padEnd(9)} ${String(hour).padStart(2)}:00 cpu×${cpu} | agents ${r.A2.cars}/${r.A2.people}/${r.A2.riders} | interval mean ${f1(on('interval'))} vs ${f1(off('interval'))} ms (${f1(100 * (1 - off('interval') / on('interval')))} %), median ${f1(on('median'))} vs ${f1(off('median'))}, p95 ${f1(on('p95'))} vs ${f1(off('p95'))}, p99 ${f1(on('p99'))} vs ${f1(off('p99'))}`
    + ` | main ${f1(on('main'))} vs ${f1(off('main'))} ms | logic ${f1(on('step'))} ms (${on('steps').toFixed(2)} steps), drawing ${f1(on('render'))} ms | flagged ${on('flaggedKB').toFixed(0)} KB, used ${on('usedKB').toFixed(0)} KB per frame`);
}
if (out) fs.writeFileSync(out, JSON.stringify(rows, null, 1));
await browser.close();
