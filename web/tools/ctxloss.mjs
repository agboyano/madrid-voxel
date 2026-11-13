// Loses the WebGL context (as a phone does with a tab put away) and restores it: the city must come back, shadows and
// all. Writes <outdir>/<name>-0.png before and <name>-1.png 8 s after the restore, and prints what the renderer draws.
// usage: node tools/ctxloss.mjs [outdir] [name]   (dev server on :5173; $CHROMIUM picks the browser)
import { chromium } from 'playwright-core';
const [dir = '/tmp', name = 'ctx'] = process.argv.slice(2);
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM || '/usr/bin/chromium', args: ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
const errs = []; page.on('pageerror', (e) => errs.push(e.message)); page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.text().slice(0, 200)); });
await page.goto('http://localhost:5173/?view=sol&level=0.3&hour=12&ui=0');
await page.waitForFunction(() => window.__ready === true && !document.body.classList.contains('loading'), null, { timeout: 180000 });
await page.waitForFunction(() => window.__streamer.inflight === 0 && window.__streamer.queue.length === 0, null, { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(2000);
await page.screenshot({ path: `${dir}/${name}-0.png` });
await page.evaluate(() => { const gl = window.__three.renderer.getContext(); window.__lc = gl.getExtension('WEBGL_lose_context'); window.__lc.loseContext(); });
await page.waitForTimeout(1500);
await page.evaluate(() => window.__lc.restoreContext());
await page.waitForTimeout(8000);
const info = await page.evaluate(() => ({ lost: window.__three.renderer.getContext().isContextLost(), tris: window.__three.renderer.info.render.triangles, geos: window.__three.renderer.info.memory.geometries }));
await page.screenshot({ path: `${dir}/${name}-1.png` });
console.log(JSON.stringify(info), 'errors', errs.slice(0, 8)); await browser.close();
