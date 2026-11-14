// Cost of a page variant: time to ready, process RSS (all Chrome processes), streamed triangles, and
// GPU-synced frame time at Home. usage: node tools/costall.mjs "query" ...
import { launch } from './launch.mjs';
import { execSync } from 'node:child_process';
const browser = await launch();
const bcdp = await browser.newBrowserCDPSession();
const rss = async () => { let kb = 0; for (const p of (await bcdp.send('SystemInfo.getProcessInfo')).processInfo) { try { kb += +execSync(`ps -o rss= -p ${p.id}`).toString().trim(); } catch {} } return Math.round(kb / 1024); };
for (const q of process.argv.slice(2)) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const t0 = Date.now();
  await page.goto(`http://localhost:5173/?ui=0&${q}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 600000 });
  const ready = (Date.now() - t0) / 1000;
  await page.waitForTimeout(8000);
  const fr = await page.evaluate(() => new Promise((res) => { const ts = [], gl = window.__three.renderer.getContext(), px = new Uint8Array(4);
    const f = () => { gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); ts.push(performance.now()); if (ts.length < 90) requestAnimationFrame(f); else { const d = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b); res(d[d.length >> 1].toFixed(1)); } }; requestAnimationFrame(f); }));
  console.log(`${q || 'today'}: ready after ${ready.toFixed(1)} s, ${(await page.evaluate(() => { let n = 0; window.__streamer.group.traverse((o) => { if (o.isMesh && o.visible && o.geometry?.index) n += o.geometry.index.count / 3; }); return n; }) / 1e6).toFixed(1)} M tris drawn, frame ${fr} ms, Chrome RSS ${await rss()} MB`);
  await page.close();
}
await browser.close();
