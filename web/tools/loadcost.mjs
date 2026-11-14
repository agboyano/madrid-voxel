// Where loading time and memory go, per page variant: time until loading is done, meshes and triangles drawn, GPU
// geometry, column data kept on the CPU, JS heap, Chrome RSS, frame time.
// usage: node tools/loadcost.mjs "query" ...
import { launch } from './launch.mjs';
import { execSync } from 'node:child_process';
const browser = await launch({ args: ['--enable-precise-memory-info'] });
const bcdp = await browser.newBrowserCDPSession();
const rss = async () => { let kb = 0; for (const p of (await bcdp.send('SystemInfo.getProcessInfo')).processInfo) { try { kb += +execSync(`ps -o rss= -p ${p.id}`).toString().trim(); } catch {} } return Math.round(kb / 1024); };
for (const q of process.argv.slice(2)) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const t0 = Date.now();
  await page.goto(`http://localhost:5173/?ui=0&${q}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 600000 });
  await page.waitForFunction(() => { const S = window.__streamer, c = document.querySelector('.caption');
    return c ? c.classList.contains('off') : (S.inflight === 0 && S.queue.length === 0); }, null, { timeout: 600000, polling: 100 });
  const done = (Date.now() - t0) / 1000;
  await page.waitForTimeout(3000);
  const r = await page.evaluate(() => new Promise((res) => {
    // what is drawn now: the streamer's meshes (the per-job fetch and mesh timings it once kept are gone)
    const S = window.__streamer;
    let geo = 0, data = 0, meshes = 0, tris = 0;
    S.group.traverse((o) => { if (!o.isMesh || !o.geometry) return; meshes++; const gm = o.geometry;
      // the mesher's own byte count, else the arrays (dropped once uploaded, so the count stands for them)
      if (o.userData.bytes) geo += o.userData.bytes; else for (const at of [...Object.values(gm.attributes), gm.index]) geo += at?.array?.byteLength ?? 0;
      if (gm.index) tris += gm.index.count / 3; });
    for (const n of S.nodes.values()) if (n.data) data += n.data.counts.byteLength + n.data.ground.byteLength + n.data.runs.byteLength + (n.data.off?.byteLength ?? 0);
    const ts = [], gl = window.__three.renderer.getContext(), px = new Uint8Array(4);
    const f = () => { gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); ts.push(performance.now()); if (ts.length < 60) requestAnimationFrame(f); else { const d = ts.slice(1).map((x, i) => x - ts[i]).sort((p, q) => p - q);
      res({ meshes, geoMB: Math.round(geo / 2 ** 20), dataMB: Math.round(data / 2 ** 20),
        heapMB: Math.round(performance.memory.usedJSHeapSize / 2 ** 20), tris: (tris / 1e6).toFixed(1), frame: d[d.length >> 1].toFixed(1) }); } };
    requestAnimationFrame(f); }));
  console.log(`${q || 'whole city'}: done ${done.toFixed(1)} s | ${r.meshes} meshes, ${r.tris} M tris, GPU geometry ${r.geoMB} MB, column data ${r.dataMB} MB, JS heap ${r.heapMB} MB, Chrome RSS ${await rss()} MB | frame ${r.frame} ms`);
  await page.close();
}
await browser.close();
