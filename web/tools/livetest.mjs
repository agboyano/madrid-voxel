// Live weather (src/live.ts) and its fallback: the viewer with Open-Meteo answering, failing in each way it can, or
// as it really is. Each case prints the weather shown, whether the menu offers "live", and any page errors; failures
// must leave the weather the viewer would show without it. usage: node tools/livetest.mjs [base url] [cases]
import { launch } from './launch.mjs';

const [base = 'http://localhost:5173', only] = process.argv.slice(2);
const RAIN = { current: { weather_code: 63, cloud_cover: 100, temperature_2m: 12.3, snow_depth: 0 } };
const CASES = {
  ok: { route: (r) => r.fulfill({ json: RAIN }), expect: 'live' },
  abort: { route: (r) => r.abort(), expect: 'typical' },
  http500: { route: (r) => r.fulfill({ status: 500, body: 'down' }), expect: 'typical' },
  garbage: { route: (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '<html>nope' }), expect: 'typical' },
  shape: { route: (r) => r.fulfill({ json: { current: { weather_code: 'rain' } } }), expect: 'typical' },
  slow: { route: async (r) => { await new Promise((ok) => setTimeout(ok, 10000)); await r.fulfill({ json: RAIN }).catch(() => {}); }, expect: 'typical', wait: 12000 },
  picked: { route: (r) => r.fulfill({ json: RAIN }), q: '&weather=clear', expect: 'clear' },
  otherday: { route: (r) => r.fulfill({ json: RAIN }), q: '&date=01-15', expect: 'typical' },
  off: { route: (r) => r.fulfill({ json: RAIN }), q: '&live=0', expect: 'typical' },
  real: { expect: null },
};

const browser = await launch();
let failed = 0;
for (const [name, c] of Object.entries(CASES)) {
  if (only && !only.split(',').includes(name)) continue;
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  // (the browser's own line for a failed request is not the page's error: it is what the failing cases cause)
  page.on('console', (m) => { if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) errs.push(m.text()); });
  let asked = 0;
  if (c.route) await page.route('**/api.open-meteo.com/**', (r) => { asked++; return c.route(r); });
  else page.on('request', (r) => { if (r.url().includes('api.open-meteo.com')) asked++; });
  await page.goto(`${base}/?hour=14${c.q ?? ''}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 300000 });
  await page.waitForTimeout(c.wait ?? 3000);
  const r = await page.evaluate(() => ({
    on: document.querySelector('#bar .sky button.on')?.dataset.v,
    said: document.querySelector('#bar .sky .val')?.textContent,
    offered: !document.querySelector('#bar .sky button[data-v="live"]').disabled,
    w: window.__three.daylight.weather,
  }));
  const ok = (c.expect === null || r.on === c.expect) && (r.offered === (r.on === 'live' || (c.expect === 'clear'))) && !errs.length;
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name.padEnd(8)} asked ${asked}  shown ${r.on} (${r.said})  live offered ${r.offered}  ${JSON.stringify(r.w)}${errs.length ? `  errors: ${errs.join(' | ')}` : ''}`);
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
