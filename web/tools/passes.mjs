// Where one frame goes, pass by pass: the triangles, draw calls and GPU time (EXT_disjoint_timer_query_webgl2) of each
// composer pass, with the shadow maps split out of the scene pass (the sun's and the twin's, told apart by the daylight
// gate's onBeforeShadow), plus the CPU time of composer.render and what is loaded, by kind. Each view twice: as it
// stands (the sun's map is only redrawn on a change) and with the sun's map redrawn every frame.
// The common baseline of docs/renderer-evaluation-plan.md.
// usage: node tools/passes.mjs [views, e.g. "overview,prado,sol"] [query, e.g. "level=1&date=1-15"] [out.json] [WxH@dpr]
//        (dev server on :5173; $CHROMIUM picks the browser; without level= the viewer adapts it for 45 s first)
import fs from 'node:fs';
import { launch } from './launch.mjs';

const [views = 'overview,top,prado,cibeles,sol,street', query = 'level=1&date=6-15', out, vp = '1600x1000@1'] = process.argv.slice(2);
const [width, height, dpr] = vp.split(/[x@]/).map(Number); // a phone's viewport and density (e.g. 390x844@3) emulates its screen, not its GPU
const FRAMES = 12, WARM = 4;
const browser = await launch();
const rows = [];
for (const view of views.split(',')) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: dpr > 1, hasTouch: dpr > 1 });
  page.on('pageerror', (e) => console.log('pageerror', e.message));
  // the tool owns the frames while it measures: the viewer's loop waits
  await page.addInitScript(() => {
    const raf = window.requestAnimationFrame.bind(window); window.__raf = raf; window.__pause = false;
    window.requestAnimationFrame = (cb) => raf((t) => (window.__pause ? window.requestAnimationFrame(cb) : cb(t)));
  });
  await page.goto(`http://localhost:5173/?view=${view}&hour=11&${query}`);
  await page.waitForFunction(() => window.__ready && !document.body.classList.contains('loading'), null, { timeout: 900000, polling: 500 });
  if (!/(^|&)level=/.test(query)) await page.waitForTimeout(45000); // the level adapts
  await page.waitForFunction(() => { const s = window.__streamer, c = window.__three.city(); return s.inflight === 0 && s.queue.length === 0 && c.settled; },
    null, { timeout: 900000, polling: 500 });
  await page.waitForTimeout(3000);
  const m = await page.evaluate(async ({ FRAMES, WARM }) => {
    const T = window.__three, r = T.renderer, gl = r.getContext(), ext = gl.getExtension('EXT_disjoint_timer_query_webgl2');
    const d = T.daylight, composer = T.post.composer;
    let label = null, q = null, tris0 = 0, calls0 = 0, acc = {}, pending = [];
    // one timer query at a time: switching label ends the running one, so each label gets its own share, exclusive
    const sw = (next) => {
      const t = r.info.render.triangles, c = r.info.render.calls;
      if (label) {
        const a = acc[label] ??= { tris: 0, calls: 0 };
        a.tris += t - tris0; a.calls += c - calls0;
        gl.endQuery(ext.TIME_ELAPSED_EXT); pending.push([label, q]);
      }
      label = next; tris0 = t; calls0 = c;
      if (next) { q = gl.createQuery(); gl.beginQuery(ext.TIME_ELAPSED_EXT, q); }
    };
    const undo = [];
    const NAMES = ['scene', 'n8ao', 'bloom', 'tilt-shift', 'tone+smaa']; // the order of web/src/post.ts
    composer.passes.forEach((p, i) => {
      const name = composer.passes.length === NAMES.length ? NAMES[i] : `${i}:${p.name || p.constructor.name}`, o = p.render;
      p.render = function (...a) { sw(name); const v = o.apply(this, a); sw(null); return v; };
      undo.push(() => { p.render = o; });
    });
    const sm = r.shadowMap, osr = sm.render;
    sm.render = function (...a) { const prev = label; sw('shadow'); const v = osr.apply(this, a); sw(prev); return v; };
    const g = d.gate, obs = g.onBeforeShadow;
    g.onBeforeShadow = function (rr, o, cam, scam, ...rest) {
      if (label?.startsWith('shadow')) sw(scam === d.sun.shadow.camera ? 'shadow:sun' : 'shadow:twin');
      return obs.call(this, rr, o, cam, scam, ...rest);
    };
    undo.push(() => { sm.render = osr; g.onBeforeShadow = obs; });
    window.__pause = true;
    await new Promise((res) => setTimeout(res, 100));
    const frame = async (redraw) => {
      acc = {}; pending = [];
      if (redraw) d.redrawShadow();
      r.info.reset();
      const c0 = performance.now();
      composer.render();
      const cpu = performance.now() - c0;
      sw(null);
      await new Promise((res) => window.__raf(res));
      const gpu = {};
      for (const [k, qq] of pending) {
        for (let n = 0; n < 200 && !gl.getQueryParameter(qq, gl.QUERY_RESULT_AVAILABLE); n++) await new Promise((res) => setTimeout(res, 5));
        gpu[k] = (gpu[k] ?? 0) + gl.getQueryParameter(qq, gl.QUERY_RESULT) / 1e6;
        gl.deleteQuery(qq);
      }
      const disjoint = gl.getParameter(ext.GPU_DISJOINT_EXT);
      return { cpu, disjoint, parts: Object.fromEntries(Object.entries(acc).map(([k, a]) => [k, { ...a, gpu: gpu[k] ?? 0 }])) };
    };
    const run = async (redraw) => {
      const fs = [];
      for (let i = 0; i < WARM; i++) await frame(redraw);
      for (let i = 0; fs.length < FRAMES && i < FRAMES * 3; i++) { const f = await frame(redraw); if (!f.disjoint) fs.push(f); }
      const med = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
      const p95 = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.ceil(s.length * 0.95) - 1)]; };
      const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
      const keys = [...new Set(fs.flatMap((f) => Object.keys(f.parts)))];
      const parts = Object.fromEntries(keys.map((k) => [k, {
        gpu: +med(fs.map((f) => f.parts[k]?.gpu ?? 0)).toFixed(2),
        gpuMean: +mean(fs.map((f) => f.parts[k]?.gpu ?? 0)).toFixed(2),
        gpuP95: +p95(fs.map((f) => f.parts[k]?.gpu ?? 0)).toFixed(2),
        Mtris: +(med(fs.map((f) => f.parts[k]?.tris ?? 0)) / 1e6).toFixed(2),
        calls: med(fs.map((f) => f.parts[k]?.calls ?? 0)),
      }]));
      const totals = fs.map((f) => Object.values(f.parts).reduce((s, p) => s + p.gpu, 0));
      return { frames: fs.length, cpu: +med(fs.map((f) => f.cpu)).toFixed(2), gpu: +med(totals).toFixed(2), gpuMean: +mean(totals).toFixed(2),
        gpuP95: +p95(totals).toFixed(2), parts };
    };
    // what is loaded and shown, by kind (triangles)
    const tri = (o) => {
      const gm = o.geometry, n = Math.min(gm.drawRange.count, gm.index ? gm.index.count : gm.attributes.position.count) / 3;
      return n * (o.isInstancedMesh ? o.count : 1);
    };
    const kinds = {};
    for (const n of window.__streamer.nodes.values()) {
      if (n.mesh?.visible) { const k = n.s === 8 ? 'clay' : n.foliage ? 'foliage' : 'buildings'; kinds[k] = (kinds[k] ?? 0) + tri(n.mesh); }
      if (n.extra?.visible) kinds.trunks = (kinds.trunks ?? 0) + tri(n.extra);
    }
    let life = 0; window.__life?.group.traverse((o) => { if (o.isMesh && o.visible) life += tri(o); });
    kinds.life = life;
    const out = {
      level: +T.level().toFixed(3), canvas: [r.domElement.width, r.domElement.height], pixelRatio: r.getPixelRatio(),
      gpuName: (() => { const e = gl.getExtension('WEBGL_debug_renderer_info'); return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : null; })(), budgetM: Number.isFinite(T.budget()) ? +(T.budget() / 1e6).toFixed(2) : 'whole',
      shownMtris: Object.fromEntries(Object.entries(kinds).map(([k, v]) => [k, +(v / 1e6).toFixed(2)])),
      gpuMemMB: { geometries: r.info.memory.geometries, textures: r.info.memory.textures },
      heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
      asIs: await run(false),
      sunRedraw: await run(true),
    };
    undo.forEach((u) => u());
    window.__pause = false;
    return out;
  }, { FRAMES, WARM });
  rows.push({ view, query, ...m });
  console.log(`\n== ${view} (${query}) canvas ${m.canvas.join('x')} at ${m.pixelRatio}, level ${m.level}, budget ${m.budgetM} M; shown M tris`, JSON.stringify(m.shownMtris), `heap ${m.heapMB} MB`);
  for (const mode of ['asIs', 'sunRedraw']) {
    const x = m[mode];
    console.log(`  ${mode.padEnd(9)} cpu ${x.cpu} ms, gpu ${x.gpu} ms (mean ${x.gpuMean}, p95 ${x.gpuP95}; ${x.frames} frames)`);
    for (const [k, p] of Object.entries(x.parts)) console.log(`    ${k.padEnd(28)} gpu ${String(p.gpu).padStart(7)} ms  ${String(p.Mtris).padStart(6)} M tris  ${String(p.calls).padStart(5)} calls`);
  }
  await page.close();
}
await browser.close();
if (out) { fs.writeFileSync(out, JSON.stringify({ when: new Date().toISOString(), rows }, null, 1)); console.log('->', out); }
