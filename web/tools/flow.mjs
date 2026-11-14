// Exits per minute, mean speed and cars stopped for 60 s or more, every 30 s. usage: node tools/flow.mjs [secs=240] [hour=17]
import { launch, seedRandom } from './launch.mjs';
const [secs = 240, hour = 17] = process.argv.slice(2);
const browser = await launch();
const page = await browser.newPage({ viewport: { width: 400, height: 300 } });
await seedRandom(page);
await page.goto(`http://localhost:5173/?hour=${hour}&ui=0`);
await page.waitForFunction(() => window.__ready === true && window.__life, null, { timeout: 120000 });
await page.evaluate(() => {
  const L = window.__life; L.exits = 0;
  const orig = L.step.bind(L);
  L.step = function (dt, dens) { const before = new Set(L.cars); orig(dt, dens); for (const c of before) if (!L.cars.includes(c)) L.exits++; };
  setInterval(() => { for (const c of L.cars) c.stuckT = c.v < 0.3 ? (c.stuckT || 0) + 1 : 0; }, 1000);
});
let lastExit = 0;
for (let t = 30; t <= +secs; t += 30) {
  await page.waitForTimeout(30000);
  const r = await page.evaluate(() => { const L = window.__life, v = L.cars.map((c) => c.v); return { t: Math.round(L.t), cars: L.cars.length, meanV: +(v.reduce((a, b) => a + b, 0) / v.length).toFixed(2), stuck60: L.cars.filter((c) => c.stuckT > 60).length, exits: L.exits }; });
  console.log(JSON.stringify({ ...r, exitsPerMin: (r.exits - lastExit) * 2 })); lastExit = r.exits;
}
await browser.close();
