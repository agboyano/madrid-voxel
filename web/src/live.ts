import { WEATHERS, type Weather } from './weather';

// The weather in Madrid now, from Open-Meteo's forecast API (CC BY 4.0), called from the browser: the site is static, so
// there is no server of its own to ask. Only the map's centre is sent. Any failure (offline, the service down or slow,
// an answer of another shape, a blocked request) gives null, and the viewer stays on the weather it already shows.
// The idea of a "live" weather on the live clock comes from portland-voxel (matt0x6F), commit 7c2c4e5, MIT.

export interface LiveWeather { w: Weather; said: string; at: number }

const URL_ = 'https://api.open-meteo.com/v1/forecast';
const TIMEOUT_MS = 5000;

// WMO weather codes (Open-Meteo's `weather_code`): [first, last, preset, words]. Anything not listed is clear sky
const CODES: [number, number, keyof typeof WEATHERS, string][] = [
  [0, 0, 'clear', 'clear sky'], [1, 1, 'clear', 'mainly clear'], [2, 2, 'clear', 'partly cloudy'], [3, 3, 'cloudy', 'overcast'],
  [45, 48, 'cloudy', 'fog'],
  [51, 55, 'rain', 'drizzle'], [56, 57, 'rain', 'freezing drizzle'],
  [61, 61, 'rain', 'light rain'], [63, 63, 'rain', 'rain'], [65, 65, 'rain', 'heavy rain'], [66, 67, 'rain', 'freezing rain'],
  [71, 71, 'snow', 'light snow'], [73, 73, 'snow', 'snowing'], [75, 75, 'snow', 'heavy snow'], [77, 77, 'snow', 'snow grains'],
  [80, 82, 'rain', 'showers'], [85, 86, 'snow', 'snow showers'],
  [95, 95, 'rain', 'thunderstorm'], [96, 99, 'rain', 'thunderstorm, hail'],
];
// cloud cover (%) from which a sky the code calls clear or partly cloudy is drawn overcast
const CLOUDY_FROM = 70;
// snow lying on the ground (m) from which roofs and streets are drawn white
const COVER_FROM = 0.01;

export function toWeather(code: number, cloudCover: number, snowDepth: number | null, temp: number): Omit<LiveWeather, 'at'> {
  const [, , kind0, words] = CODES.find(([a, b]) => code >= a && code <= b) ?? [0, 0, 'clear', 'clear sky'];
  const kind = kind0 === 'clear' && cloudCover >= CLOUDY_FROM ? 'cloudy' : kind0;
  const w = { ...WEATHERS[kind] };
  if (snowDepth !== null && snowDepth > COVER_FROM) w.cover = 1;
  return { w, said: `${words}, ${Math.round(temp)}°C` };
}

const num = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);

export async function fetchLiveWeather(lon: number, lat: number): Promise<LiveWeather | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const q = new URLSearchParams({ latitude: lat.toFixed(4), longitude: lon.toFixed(4), current: 'temperature_2m,weather_code,cloud_cover,snow_depth' });
    const res = await fetch(`${URL_}?${q}`, { signal: ctl.signal });
    if (!res.ok) return null;
    const c = ((await res.json()) as { current?: Record<string, unknown> })?.current;
    if (!c || !num(c.weather_code) || !num(c.cloud_cover) || !num(c.temperature_2m)) return null;
    return { ...toWeather(c.weather_code, c.cloud_cover, num(c.snow_depth) ? c.snow_depth : null, c.temperature_2m), at: Date.now() };
  } catch (e) {
    console.debug('live weather unavailable:', e);
    return null;
  } finally {
    clearTimeout(timer);
  }
}
