// Where the frame loop allocates: Chrome's sampling heap profiler over a few seconds of a still view and of walking,
// with the bytes per second of each function (garbage collected or not), so the top garbage makers stand out.
// usage: node tools/allocs.mjs [level] [seconds]   (dev server on :5173; $CHROMIUM picks the browser)
import { chromium } from 'playwright-core';
const [level = '0.3', seconds = '6'] = process.argv.slice(2);
const browser = await chromium.launch({
  headless: true, executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
  args: ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist'],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(`http://localhost:5173/?view=granvia&hour=12&level=${level}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 180000 });
await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 300000 });
await page.waitForFunction(() => window.__streamer.inflight === 0 && window.__streamer.queue.length === 0, null, { timeout: 60000 })
  .catch(() => console.log('streamer still busy, going on'));
await page.waitForTimeout(2000);
const cdp = await page.context().newCDPSession(page);
await cdp.send('HeapProfiler.enable');

async function sample(name, act) {
  await cdp.send('HeapProfiler.startSampling', { samplingInterval: 1024, includeObjectsCollectedByMajorGC: true, includeObjectsCollectedByMinorGC: true });
  await page.evaluate(() => { window.__frames = 0; if (!window.__counting) { window.__counting = true; const f = () => { window.__frames++; requestAnimationFrame(f); }; requestAnimationFrame(f); } });
  await act();
  const { profile } = await cdp.send('HeapProfiler.stopSampling');
  const frames = await page.evaluate(() => window.__frames);
  const by = new Map();
  let total = 0;
  const walk = (n) => {
    const self = n.selfSize;
    if (self) {
      const f = n.callFrame, file = f.url.replace(/^.*\/(src|node_modules\/\.vite\/deps)\//, '$1/').replace(/\?.*$/, '');
      const k = `${f.functionName || '(anonymous)'} ${file}:${f.lineNumber + 1}`;
      by.set(k, (by.get(k) ?? 0) + self);
      total += self;
    }
    n.children.forEach(walk);
  };
  walk(profile.head);
  const s = +seconds;
  console.log(`\n${name}: ${(total / s / 1e6).toFixed(2)} MB/s over ${frames} frames (${(total / Math.max(frames, 1) / 1e3).toFixed(1)} kB/frame)`);
  for (const [k, v] of [...by].sort((a, b) => b[1] - a[1]).slice(0, 15)) console.log(`  ${(v / s / 1e3).toFixed(0).padStart(7)} kB/s  ${k}`);
}

await sample('still view', () => page.waitForTimeout(+seconds * 1000));
await page.evaluate(() => window.__three.nav.setWalk());
await page.waitForFunction(() => window.__three.nav.mode === 'walk', null, { timeout: 60000 });
await page.waitForTimeout(1500);
await sample('walking', async () => { await page.keyboard.down('w'); await page.waitForTimeout(+seconds * 1000); await page.keyboard.up('w'); });
await browser.close();
