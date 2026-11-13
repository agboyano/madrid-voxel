const RAD = Math.PI / 180;
// the map's centre (meta.json lonlat), set at boot; Puerta del Sol until then
let LAT = 40.4169 * RAD, LON = -3.7033;
export function setSite(lon: number, lat: number) { LAT = lat * RAD; LON = lon; }

// the calendar date in Madrid, whatever the visitor's time zone (adapted from dtla-voxel cf1c7e1)
const madridCalendar = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Madrid', year: 'numeric', month: 'numeric', day: 'numeric' });
export function madridDate(now = new Date()) {
  const p = Object.fromEntries(madridCalendar.formatToParts(now).map((x) => [x.type, x.value]));
  return new Date(+p.year, +p.month - 1, +p.day);
}
export const SOLAR_YEAR = madridDate().getFullYear();
export const daysInYear = (year = SOLAR_YEAR) => (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 864e5;

const lastSunday = (year: number, month: number) => { const d = new Date(Date.UTC(year, month + 1, 0)); return d.getUTCDate() - d.getUTCDay(); };
export const dayOfYear = (d: Date) => Math.round((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - Date.UTC(d.getFullYear(), 0, 0)) / 864e5);
export const dateOf = (day: number, year = SOLAR_YEAR) => new Date(year, 0, day);

// CET, CEST from 02:00 on the last Sunday of March to 03:00 on the last Sunday of October (the repeated hour is CET)
export function utcOffset(day: number, year = SOLAR_YEAR, hour = 12) {
  const start = dayOfYear(new Date(year, 2, lastSunday(year, 2))), end = dayOfYear(new Date(year, 9, lastSunday(year, 9)));
  return (day > start || (day === start && hour >= 2)) && (day < end || (day === end && hour < 2)) ? 2 : 1;
}

// NOAA low-precision declination and equation of time; hour is Madrid clock time
export function sunAt(day: number, hour: number, year = SOLAR_YEAR) {
  const g = 2 * Math.PI / daysInYear(year) * (day - 1 + (hour - 12) / 24);
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g)
    - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const eot = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const solar = hour - utcOffset(day, year, hour) + LON / 15 + eot / 60;
  const H = (solar - 12) * 15 * RAD;
  const el = Math.asin(Math.sin(LAT) * Math.sin(decl) + Math.cos(LAT) * Math.cos(decl) * Math.cos(H));
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(LAT) - Math.tan(decl) * Math.cos(LAT)) + Math.PI;
  return { el, az };
}

// The scene's turn from true north: the grid's own rotation (meta.theta_deg) less the UTM meridian convergence at the
// map's centre, about -0.45° in Madrid (zone 30). Spherical formula, as dtla-voxel cf1c7e1; checked against pyproj.
export function trueNorthRotation(thetaDeg: number, [lon, lat]: [number, number], crs: string) {
  const zone = +(/^EPSG:(?:258|32[67])(\d{2})$/.exec(crs)?.[1] ?? 0);
  const convergence = zone >= 1 && zone <= 60 ? Math.atan(Math.tan((lon - (zone * 6 - 183)) * RAD) * Math.sin(lat * RAD)) : 0;
  return thetaDeg * RAD - convergence;
}

const elDeg = (day: number, h: number) => sunAt(day, h).el / RAD;

export function solarNoon(day: number) {
  let lo = 9, hi = 16;
  for (let i = 0; i < 30; i++) { const m = (lo + hi) / 2; if (elDeg(day, m + 1e-3) > elDeg(day, m)) lo = m; else hi = m; }
  return lo;
}

export function hourAt(day: number, deg: number, evening: boolean) {
  const noon = solarNoon(day);
  let lo = evening ? noon : noon - 12, hi = evening ? noon + 12 : noon;
  for (let i = 0; i < 30; i++) {
    const m = (lo + hi) / 2, above = elDeg(day, m) > deg;
    if (above === evening) lo = m; else hi = m;
  }
  return (lo + hi) / 2;
}

// Clear-sky transmittance of the direct beam at 610, 550, 465 nm: Rayleigh (Bucholtz), urban haze (Ångström β 0.05,
// α 1.3), ozone (Chappuis band); Kasten-Young air mass
const TAU = [0.191, 0.244, 0.339];
export const airMass = (elDeg: number) => { const h = Math.max(elDeg, -0.5); return 1 / (Math.sin(h * RAD) + 0.50572 * (h + 6.07995) ** -1.6364); };
export const beam = (elDeg: number) => TAU.map((t) => Math.exp(-airMass(elDeg) * t)) as [number, number, number];
