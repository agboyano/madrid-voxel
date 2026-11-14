# N8AO: what the screen-space occlusion pass costs, and whether to grade it

The question: how much the N8AO pass costs in this viewer, whether a cheaper setting loses nothing visible, and whether it should be graded by device, by camera distance, or both. No default was changed; the measurements use evaluation-only URL switches.

It also answers the open point of `docs/renderer-evaluation-plan.md` (technique 3, stage B): can N8AO stand in for the per-vertex occlusion that `?ao=merge` removes?

**Tags.**

- **[M]** measured here; raw output in `data/baseline/n8_*.json`, `n8_*.log` and `n8_imagediff.txt` (not versioned).
- **[R]** read in code or documentation, with the file cited.
- **[A]** assumed.

## Decision rule, fixed before measuring

- **Time:** a change is worth making if it saves at least **5 % of the frame** on the slowest device measured.
- **Image:** a cheaper setting counts as having no visible loss if the mean luminance difference is under **3/255** and under **1 %** of pixels differ by more than 16/255. These are the same thresholds as technique 3.

## 1. Is half resolution on? With what settings?

Yes [R].

| Setting | Value | Where |
| --- | --- | --- |
| n8ao version | 2.0.1 (`N8AOPostPass`, pmndrs/postprocessing 6.39) | `web/package.json`, `web/node_modules/n8ao/package.json` |
| `halfRes` | `true` | `web/src/post.ts:47` |
| `depthAwareUpsampling` | `true` | same |
| `aoRadius`, `distanceFalloff`, `intensity` | 6 (world metres), 1.5, 2.2; under cloud up to 9 and 3.4 | `web/src/post.ts:47`, `web/src/daylight.ts:142` |
| Quality mode | none set, so the default `Medium`: 16 AO samples, 8 denoise samples, denoise radius 12 | n8ao `README.md` quality table; `aoSamples: 16` default in `dist/N8AO.js` |
| `transparencyAware` | automatic; the pass does not re-render the scene here (no geometry in its share) | [M] `web/tools/passes.mjs` |
| Device gating | off below render level 0.4 (`LIGHT_POST`), together with the depth blur; the level also lowers the pixel ratio (`pixelsAt`) | `web/src/main.ts:44-66`, `:398`; `web/src/post.ts` `setLight` |

So half resolution is the baseline, not a pending improvement. The dtla-voxel figure of about 1 ms (GTX 1080 Ti) does not hold here: see below.

## Method

- **Machine:** Intel UHD 620 (KBL GT2), Mesa driver, Chromium 155.0.8059.84 headless, ANGLE on Vulkan (`web/tools/launch.mjs`). It is the only GPU available, and it is the weak device. There is no desktop with a dedicated GPU and no real phone.
- **Timing:** `web/tools/passes.mjs` wraps each composer pass in its own `EXT_disjoint_timer_query_webgl2` query, one at a time, so pass times are exclusive. CPU time is the `performance.now()` around `composer.render`, reported apart, since CPU and GPU overlap. The tool owns the frame loop while it measures.
  - Camera still, city loaded and settled, 4 warm-up frames, 12 measured frames per case (frames flagged disjoint are dropped).
  - Mean and p95 per case. Level 0.5 was run twice, in reverse order the second time, and the two means are averaged.
- **Variants** (URL, evaluation only; `web/src/post.ts` `AOOptions`, `web/src/main.ts`):
  - `?n8=on|off` forces the pass on or off whatever the level;
  - `?n8q=` sets the quality mode;
  - `?n8full=1` uses full resolution;
  - `?n8up=0` turns off depth-aware upsampling.
- **Image:** `scripts/screenshot.py` at 1600 × 1000, 15 June 13:00, clear and cloudy, six views. The pedestrians move between captures and add a little noise to every pair.
- **Views and camera distance to the focus:** `street` 97 m, `sol` 251 m, `prado` 425 m, `cibeles` 485 m, `top` 832 m, `overview` 5.9 km (the viewer holds the camera nearer than `meta.json`). Three extra cameras sit on the overview's line at 1.5, 2.5 and 4 km.

## 2. What share of the frame N8AO costs

GPU time of the N8AO pass and of the whole frame, mean in ms [M]:

| Device, canvas | View | N8AO pass | Frame | Share | Frame saved with it off |
| --- | --- | --- | --- | --- | --- |
| Laptop, level 1, 1600 × 1000 at 1 | street | 15.2 | 112.1 | 14 % | 4.3 (noisy, one run) |
| | prado | 18.5 | 107.3 | 17 % | 21.0 |
| | overview | 15.1 | 288.1 | 5 % | 16.8 |
| Laptop, level 0.5, 1280 × 800 at 0.8 | street | 11.1 | 52.8 | 21 % | 14.6 |
| | sol | 11.1 | 54.0 | 21 % | 12.0 |
| | prado | 12.1 | 91.1 | 13 % | 16.2 |
| | overview | 10.3 | 94.7 | 11 % | 15.0 |
| Laptop, level 0.3 forced on, 1024 × 640 at 0.64 (off by default) | street | 6.3 | 24.9 | 25 % | (+5.5 against today) |
| | sol | 6.7 | 32.2 | 21 % | (+6.6) |
| | prado | 6.8 | 49.4 | 14 % | (+1.4) |
| | overview | 6.1 | 57.8 | 10 % | (+4.6) |
| Phone screen emulated, level 0.5, 624 × 1350 at 1.6 | sol | 8.3 | 33.1 | 25 % | 8.5 |
| | prado | 8.6 | 45.2 | 19 % | 8.6 |
| | overview | 8.1 | 54.2 | 15 % | 8.7 |
| Real phone | — | not measured | | | |
| Desktop with dedicated GPU | — | not measured | | | |

- **The pass scales with pixels, not with the scene.** It is 15–18 ms at 1.6 Mpx, 10–12 ms at 1.0 Mpx and about 6 ms at 0.66 Mpx, whatever the view.
- **On this GPU it is 10–25 % of the frame** at the levels the laptop runs at, and at least 5 % everywhere.
- **The frame saved with it off is a little larger than the pass itself** (12–16 ms against 10–12 ms at level 0.5). The pass needs the scene pass to keep depth and normals for it.
- **The emulated phone gives only the screen size and density:** the GPU is still the laptop's [R] `scripts/profile.py:52-58`.
- **The p95 stays within 5 % of the mean in every case** (in the logs).

## 3. Cheaper settings

Laptop, level 0.5. Savings in the N8AO pass in ms, mean of two runs [M]; image difference against the current setting (mean |ΔL|/255, share of pixels over 16/255) [M]:

| Variant | Pass saved, street / sol / prado / overview | Share of frame | Image, worst of 12 view × weather pairs |
| --- | --- | --- | --- |
| `Performance` (8 AO samples, 4 denoise) | 2.3 / 1.9 / 2.3 / 1.6 | 2–4 % | 2.5, 1.6 % (street, cloudy); all others ≤ 2.3 and ≤ 0.7 % |
| `Low` (16 AO samples, 4 denoise) | 1.0 / 0.7 / 1.6 / 0.1 | 0–2 % | 1.8, 1.4 % (street) |
| No depth-aware upsampling | 2.3 / 1.9 / 2.4 / 1.4 | 1–4 % | 2.4, 1.9 % (street, clear) |
| Full resolution | costs 9.5–11.3 more | — | not captured (dearer) |

- **No visible loss away from the street.** `Performance` and no-upsampling pass the image rule in every view except `street`, where 1.5–1.9 % of pixels move by more than 16/255. Those are the edges of near objects: the half-resolution AO without depth-aware upsampling bleeds across them [A, from n8ao's `README.md` warning].
- **Below the bar.** Neither saves 5 % of the frame on its own, so by the rule neither is worth adopting.
- **Not measured: both together.** `Performance` plus no upsampling would be about 4 ms (up to 8 % near the ground) if the savings added up [A]; that is the one combination worth one more run.

## 4. By camera distance

What N8AO adds to the image: the current setting against `?n8=off`, level 0.5 [M]:

| Camera distance | View | Clear | Cloudy |
| --- | --- | --- | --- |
| 97 m | street | 6.3 | 12.9 |
| 251 m | sol | 10.4 | 18.7 |
| 425 m | prado | 8.7 | 19.7 |
| 485 m | cibeles | 7.2 | 17.5 |
| 832 m | top | 7.9 | 15.5 |
| 1.5 km | overview line | 7.1 | 15.1 |
| 2.5 km | overview line | 4.4 | 10.7 |
| 4 km | overview line | 2.1 | 6.1 |
| 5.9 km | overview | 0.7 | 3.4 |

- **N8AO is not a fine contact term here: it is a large share of the image's tone.** Turning it off lightens the city by 6–20/255. The effect is largest under cloud, where `daylight.ts` raises its intensity and radius.
- **It fades with distance, because its radius is in world metres.** 6 m covers about 15 pixels at 830 m and about 2 at 6 km [A, from the 28° field of view]. It stays clearly visible up to about 2.5 km and drops under the 3/255 threshold only near 6 km.
- **Recommendation: fade it out between 4 and 6 km camera distance, then turn it off.** It saves 10 ms at level 0.5 (11 % of the overview frame) and 15 ms at level 1 (5 %). Both clear the 5 % bar, and the image cost is under 3.4/255.
  - It only acts in the outermost zoom range, which is also where the adapted level is lowest and the frame slowest.
  - A fade rather than a cut avoids a jump in tone while zooming.
  - Cost: about half a day; the intensity is already set per frame from the weather.

## 5. Tied to the adaptive quality

It already is: below level 0.4 the pass is off [R] `web/src/main.ts:48`, `:398`. The measurements show what that costs:

- **Keeping it on at level 0.3 would add 1.4–6.6 ms** (5–28 % of the frame), against the 5 % bar the other way. The current tie is right on time grounds.
- **But the switch is not neutral.** When the level crosses 0.4 the city changes tone by 6–20/255 outside the overview (the table above: the level 0.3 pairs `cur` against `on` give 5.4–19.5/255). A visitor whose device settles near 0.4 sees the city lighten and darken as the level steps. Slow devices always see a lighter, flatter city than the reference.
- **A cheaper fix than moving the threshold:** when N8AO is off, darken the ambient and environment light by the mean it would have removed. That is a uniform, about one per weather, already in `daylight.ts`. It costs nothing per pixel. Not measured: it would not restore the contact darkening, only the overall tone [A].

## 6. Technique 3: can N8AO replace the per-vertex occlusion?

At level 0.3, `?ao=merge` with N8AO forced on, against the per-vertex occlusion with N8AO forced on, the same quality on both sides [M]:

| View | Clear | Cloudy | Frame against today (per-vertex AO, N8AO off) |
| --- | --- | --- | --- |
| street | 1.7–2.1 | 2.7–2.9 | +3.5 ms (`Performance`) |
| sol | 1.4 | 2.0 | +3.4 ms |
| prado | 1.7–1.8 | 2.9 | −2.3 ms |
| cibeles | 2.1–2.2 | 3.3–3.4 | — |
| top | 3.0 | 4.0 | — |
| overview | 4.0 | 5.7 | +0.2 ms |

- **Near and middle views pass.** With N8AO on, the mesh without per-vertex occlusion looks the same.
- **Far views fail, and for the reason found in section 4:** at that distance N8AO has faded, so the per-vertex occlusion is the only darkening left. Removing it costs 4.0–5.7/255, the same as without N8AO in stage B.
- **N8AO also costs as much as the mesh saves**, or more at street level.
- **So the first follow-up of technique 3 (N8AO in place of per-vertex occlusion) is dropped.** What would still work is a far-field term the mesh does not carry: per-fragment occlusion (option b), or a cheap darkening of gaps from the height data. Neither is designed.

## Recommendation

| Option | Gain on the laptop | Image | Cost | Verdict |
| --- | --- | --- | --- | --- |
| Leave everything as it is | — | — | — | Default if nothing below is done |
| Fade N8AO out from 4 to 6 km camera distance | 10 ms at level 0.5, 15 ms at level 1 in the overview (5–11 %) | ≤ 3.4/255 | ½ day | **Do it** |
| Match the tone when N8AO is off below level 0.4 | none in time; removes a 6–20/255 jump | to be measured | ½–1 day | **Worth a prototype** |
| `Performance` or no upsampling, alone | 1.4–2.4 ms (2–4 %) | passes away from the street | minutes | Below the bar: no |
| Both together | about 4 ms, up to 8 % near the ground [A] | not measured | minutes plus one run | Measure before deciding |
| Keep N8AO on below level 0.4 | costs 1.4–6.6 ms | darker, closer to the reference | — | No |
| By device | already graded by the level | — | — | Nothing to add without a real phone or a dedicated GPU |

So the answer is: **grade it by distance, keep the device grading as it is, and fix the tone jump the device grading causes.**

Not measured, and left empty above: a real phone, a desktop with a dedicated GPU, `Performance` plus no upsampling together, and the tone-matching fix.

## Adopted (2026-11-14)

Two changes to the defaults (`DECISIONS.md`, 2026-11-14):

- **Fade with camera distance** (`web/src/post.ts` `AO_FADE`, `setDistance`). The intensity falls from full at 3.5 km to zero at 5.5 km, and the pass is skipped beyond that. A first try at 4–6 km left the overview, at 5.93 km, at 3 % intensity, and a pass at almost no intensity still costs all of it. `?n8fade=0` turns the fade off.
  - **Time** (level 0.5, A-B-B-A, `data/baseline/n8fade_*.json`): overview 98.2 → 88.1 ms (−10 %); `top` unchanged (61.5 ms, under 3.5 km).
  - **Image** (overview at level 0.5, fade against no fade): 0.7/255 clear, 3.4/255 cloudy with 0.7 % of pixels over 16. That is just over the 3/255 mean in the cloudy case, and under the pixel rule.
- **Tone kept when the level turns N8AO off** (`web/src/daylight.ts` `aoTone`, `aoOff`). Below level 0.4 the sky's light and the environment are dimmed by 0.7 in clear weather and 0.75 overcast, interpolated by cloud. The factors were chosen from a sweep (0.85 to 0.4) against N8AO forced on. `?aotone=clear,cloudy` overrides them.
  - **Result** at level 0.3, against N8AO on (mean signed / mean absolute ΔL):

    | View | Clear, before → after | Cloudy, before → after |
    | --- | --- | --- |
    | street | +5.1 / 5.4 → −2.4 / 6.1 | +11.8 / 12.6 → −3.2 / 10.6 |
    | sol | +10.3 / 10.3 → +5.6 / 7.4 | +18.6 / 18.6 → +2.5 / 12.5 |
    | prado | +8.5 / 8.6 → +3.2 / 6.3 | +19.5 / 19.5 → +5.2 / 10.4 |
    | cibeles | +6.2 / 6.5 → −0.2 / 5.3 | +15.7 / 15.8 → +0.4 / 9.5 |
    | top | +7.3 / 7.5 → +3.4 / 5.4 | +14.8 / 15.0 → +1.0 / 8.2 |

  - The step in overall tone at level 0.4 shrinks from 5–20/255 to 0–6/255. The absolute difference falls by a quarter to a half: what remains is the contact darkening, which a uniform factor cannot give. Street level in clear weather comes out slightly darker than the reference.
  - See `docs/img/n8ao-tone-prado-cloudy-l03-n8on.png` (N8AO on), `-before.png` (level 0.3 until now) and `n8ao-tone-prado-cloudy-l03.png` (level 0.3 now).
- **Not adopted:** cheaper quality modes and no upsampling (under the 5 % bar).
