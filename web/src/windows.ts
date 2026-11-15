import * as THREE from 'three';
import type { Meta } from './types';
import { dataTexture, dataUrl, fetchGzip, fetchJson, isWeekend } from './util';
import type { VoxelUniforms } from './voxelMaterial';

interface WinType { med: { weekday: number[]; weekend: number[] }; shape: number[]; floors: number; colour: [number, number, number] }
// med: the share of lit windows per clock hour from 0:00 (scripts/window_stats.py)
interface WinStats { types: Record<string, WinType> }

// building kinds in windows.bin (scripts/windows.py) and the measured type each one follows (scripts/window_stats.py)
const KIND_MODEL = ['residential', 'residential', 'office', 'hotel', 'office', 'public', 'religious', 'public'];

export async function loadWindows(meta: Meta, U: VoxelUniforms) {
  const [stats, buf] = await Promise.all([fetchJson<WinStats>(dataUrl('windows.json')), fetchGzip(dataUrl('windows.bin'))]);
  const tex = dataTexture(new Uint8Array(buf), meta.W, meta.D, THREE.RedFormat);
  tex.magFilter = tex.minFilter = THREE.NearestFilter;
  U.uWinMap.value = tex;
  KIND_MODEL.forEach((m, k) => {
    const t = stats.types[m];
    t.shape.forEach((q, i) => { U.uWinShape.value[k * 9 + i] = q; });
    U.uWinFloors.value[k] = t.floors;
    U.uWinCol.value[k].set(...t.colour);
  });
  return (hour: number, day: number) => setWindows(U, stats, hour, day);
}

function setWindows(U: VoxelUniforms, stats: WinStats, hour: number, day: number) {
  const weekend = isWeekend(day);
  // each hour's value stands for the middle of that hour; in between, a straight line
  const x = ((hour % 24) + 24) % 24 - 0.5, i = Math.floor(x), f = x - i;
  KIND_MODEL.forEach((m, k) => {
    const med = stats.types[m].med[weekend ? 'weekend' : 'weekday'];
    U.uWinMed.value[k] = med[(i + 24) % 24] * (1 - f) + med[(i + 25) % 24] * f;
  });
}
