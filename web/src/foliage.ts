import * as THREE from 'three';
import type { Meta } from './types';
import { dataTexture, dataUrl, fetchGzip, fetchJson } from './util';
import type { VoxelUniforms } from './voxelMaterial';

interface Phase { day: number; sd: number; n: number }
interface Class { species: string; leaf: Phase | null; colour: Phase | null; fall: Phase | null; autumn?: string; base?: [number, number, number] }
interface Phenology { classes: Record<string, Class>; city: { leaf: number; colour: number; fall: number }; grass: [number, number, number][]; grass_dry?: [number, number, number][]; leaf: [number, number, number] }

export const FOLIAGE_CLASSES = 24; // class ids in foliage.bin (scripts/phenology.py CLASSES), with room to grow

export async function loadFoliage(meta: Meta, U: VoxelUniforms) {
  const [ph, buf] = await Promise.all([fetchJson<Phenology>(dataUrl('phenology.json')), fetchGzip(dataUrl('foliage.bin'))]);
  const w = meta.W >> 1, h = meta.D >> 1, a = new Uint8Array(buf), rg = new Uint8Array(w * h * 2);
  for (let i = 0; i < w * h; i++) { rg[2 * i] = a[i]; rg[2 * i + 1] = a[w * h + i]; }
  const tex = dataTexture(rg, w, h, THREE.RGFormat);
  tex.magFilter = tex.minFilter = THREE.NearestFilter;
  U.uFolMap.value = tex;
  for (const [k, c] of Object.entries(ph.classes)) {
    const i = +k;
    if (c.leaf && c.colour && c.fall) U.uFolDate.value[i].set(c.leaf.day, c.colour.day, c.fall.day, (c.leaf.sd + c.colour.sd + c.fall.sd) / 3);
    else U.uFolDate.value[i].set(-1, 0, 0, 0);
    if (c.autumn) U.uFolCol.value[i].set(c.autumn).convertSRGBToLinear();
    if (c.base) U.uFolBase.value[i].setRGB(...c.base);
  }
  ph.grass.forEach((t, m) => U.uGrass.value[m].setRGB(...t));
  (ph.grass_dry ?? ph.grass).forEach((t, m) => U.uGrassDry.value[m].setRGB(...t));
  U.uLeaf.value.setRGB(...ph.leaf);
  U.uFolOn.value = 1;
  return ph.city;
}
