# Evaluation plan: three dtla-voxel techniques for the madrid-voxel renderer

## Context

The question is whether three techniques from [dtla-voxel](https://github.com/sigman78/dtla-voxel) are worth bringing to this viewer:

- adaptive levels of detail;
- coarser shadow geometry;
- ambient occlusion taken out of the mesher's merge key.

This document is a plan, not an implementation. It decides what to measure, how, and what result accepts or rejects each technique. No code was changed and no new measurements were taken to write it. The figures for this project come from `NOTES.md` and from the trunk measurements of 2026-11-13.

**Every claim carries a tag:**

- **[V]** verified by reading the code or the data (the file is cited);
- **[D]** stated in dtla-voxel's documentation;
- **[N]** stated in this project's notes or decisions, or a measurement already recorded here;
- **[S]** an assumption.

Paths prefixed `dtla:` are in dtla-voxel; the others are in this repository. The dtla-voxel clone is complete (38 commits, HEAD `90bc1a6`, 2026-11-06) [V].

**Summary of the conclusion**

| Technique | Verdict |
| --- | --- |
| 3. AO out of the merge key | Run the offline count now (half a day). Implement only if it passes the criterion. |
| 2. Coarser shadows | Measure how often the shadow map is redrawn now. The experiment can use the existing 8 m clay, without waiting for technique 1. |
| 1. Adaptive levels | Evaluate later, in stages. It has been turned down twice here, and dtla-voxel's evidence is not enough to reopen it without a measurement of our own. |

**Status (2026-11-14):** technique 3 option a dropped, a far-field occlusion term still open; technique 2 closed after three cheaper fixes to the redraws, its experiment not worth running; technique 1 not started. Results in the dated sections at the end.

---

## Preliminary: this renderer in one page

**Geometry and meshing**

- Tiles are 128 × 128 columns of runs (z0, length, palette) at two levels, 1 m and 8 m ("clay"). Foliage at 1 m is a separate tile set [V] `scripts/tiles.py:23-24`, `:82-128`.
- There are no 2 m or 4 m levels, and no `detail` block of thin voxels as in dtla-voxel [V] `scripts/tiles.py:24`.
- Greedy meshing runs in a worker pool. The merge key is `(((ang·4096 + palette)·256 + ao)·256 + ground)·16384 + building + 1` [V] `web/src/mesher.worker.ts:169`. dtla-voxel's key has no building id [V] `dtla:web/src/mesher.worker.ts:267`.
- A vertex is 12 bytes (14 with the building id), 4 vertices per quad, and one index buffer is shared by every tile [V] `web/src/mesher.worker.ts:72-92`, `web/src/stream.ts:225-256`.
- Trunks and limbs are instanced boxes, one mesh per foliage tile [V] `web/src/trunks.ts`.

**What gets drawn**

- A triangle budget is spent by city block. Each block is wholly real (1 m) or wholly clay (8 m), chosen by distance to the focus and visibility, with 1.1× hysteresis [V] `web/src/city.ts:70-95`.
- The budget comes from a 0–1 level that adapts to the frame rate. It steps down when the median drops below 27 fps and up when the slowest tenth is above 30 fps [V] `web/src/main.ts:381-420`.
- With clay in use, all 15 8 m tiles of the map are loaded and drawn. Each material discards per fragment what is not its own [V] `web/src/city.ts:117-133`, `web/src/voxelMaterial.ts:387-391`.
- There is no screen-size selection. "Ordering by projected size alone" was rejected [N] `DECISIONS.md:372`.

**Shadows**

- There are two directional lights, without cascades [V] `web/src/daylight.ts:47-84`, `web/src/main.ts:67`.
  - The sun's map (4096², 2048² on phones) is redrawn only when something changes.
  - A "twin" map is redrawn every frame, but holds only what moves (cars, people).
- The sun's map is fitted around the focus, not the whole city, and its frame is quantised [V] `web/src/daylight.ts:165-202`.
- It is redrawn when its fit changes, when the hour or day changes, and when the set of visible tiles changes (at most every 300 ms) [V] `web/src/main.ts:356-379`.
- There is no separate shadow level of detail: shadows come from exactly what is shown [V] `web/src/stream.ts:240`, `web/src/city.ts:128`, `:201`.

**Ambient occlusion**

- Per vertex: 2 bits per corner, computed by the mesher. It darkens albedo and indirect light [V] `web/src/mesher.worker.ts:213-221`, `web/src/voxelMaterial.ts:385`, `:455`, `:463-465`.
- On top of it, screen-space N8AO at half resolution, which is off below level 0.4 [V] `web/src/post.ts:45-47`, `web/src/main.ts:48`.

**Measurement tools**

| Tool | What it measures | State here |
| --- | --- | --- |
| `scripts/profile.py` | fps, triangles and draw calls per view; no-shadow and no-post variants; `--phone` | Runs. Does not separate GPU from CPU [V] |
| `scripts/cost1m.py` | triangles and bytes of every 1 m tile, meshing the whole city (57 s) | Runs [V] |
| `web/tools/probe.mjs` | GPU time with `EXT_disjoint_timer_query_webgl2`, removing one part at a time | Does not launch: asks for Chrome and Metal [V] |
| `web/tools/redraws.mjs` | how often the sun's map is redrawn while loading, orbiting, zooming | Does not launch, same reason [V] |
| `web/tools/inventory.mjs` | triangles by kind (buildings, foliage, clay, traffic) | Does not launch, same reason [V] |
| `web/tools/uploads.mjs`, `allocs.mjs` | frame time and GPU uploads; allocations | Run [V] |
| `web/tools/abdiff.mjs` + `.py` | pixel difference between two servers at the same views | Does not launch without changes [V] |
| `web/tools/framerec.mjs` + `.py` | every frame of a zoom, finds abrupt picture changes | Does not launch without changes [V] |
| `web/tools/lodflip.mjs`, `lodfade.mjs` | jumps at level switches | Stale: use streamer fields that no longer exist [V] |
| `scripts/perf_stats.py` | real visitors' performance (PostHog) | Needs keys; not tried |

**Measurements already recorded** (all on the development laptop's Intel UHD 620, headless Chromium)

| View | Level | fps | Triangles per frame | Source |
| --- | --- | --- | --- | --- |
| overview | 1 | 3.2 | 47.4 M | 2026-11-13, 15 January, with trunks [N] `NOTES.md` "Trunks and limbs" |
| prado | 1 | 9.8 | 5.9 M | same |
| sol | 1 | 14.2 | 2.2 M | same |
| overview | 0.3 | 17.0 | 4.8 M | [N] `NOTES.md:1368-1372` |
| sol | 0.3 | 34.6 | — | same |
| overview (emulated phone) | own budget | 25.4 | 2.9 M | [N] `NOTES.md:1336-1340` |

- Post-processing is about half the frame on this GPU; shadows are 10–20 % [N] `NOTES.md:1331`.
- Frames that redraw the sun's map have a median of 83 ms, against 33 ms at rest [N] `NOTES.md:1593`.

**Not determined**

- **The overview's triangle count.** It draws 42–47 M triangles per frame, yet the whole city at 1 m is 18.7 M [N] (`cost1m.py`).
  - `renderer.info` adds up every pass.
  - It is not known how much is the main pass, how much the sun's map, and whether N8AO draws the scene again.
  - This must be resolved in the baseline, because it bounds what each technique can save.
- The clay's triangle count: not recorded.
- Whether `EXT_disjoint_timer_query_webgl2` is available with ANGLE on Vulkan and Mesa on this laptop.
- Whether foliage tiles, which have no depth material of their own, cast a full shadow from a bare tree [V] `web/src/city.ts:199` (read, not checked at runtime).
- What devices real visitors use.

---

## Common baseline (before any technique)

All three techniques share this phase. Without it no criterion below can be checked.

1. **Get the tools running** (half a day, no viewer change). Make `probe.mjs`, `redraws.mjs`, `inventory.mjs`, `abdiff.mjs` and `framerec.mjs` launch the system Chromium with `--use-angle=vulkan`, as `scripts/screenshot.py:39-42` already does [V].
2. **Separate GPU from CPU time.**
   - Preferred: timer queries per pass, as in `probe.mjs` and `dtla:web/tools/profile.mjs:108-151` [V].
   - If the extension is missing here: frame time with a 1-pixel readback to wait for the GPU, as `web/tools/gpu1m.mjs` does [V], plus the CPU time of `composer.render` from `performance.now()`.
   - Either way, CPU and GPU times overlap and must not be added [D] `dtla:docs/features/voxel-rendering-streaming.md:227`.
3. **Triangles per pass** in `overview`, `prado` and `sol`: main pass, sun map, twin map, N8AO. This resolves the first open question above.
4. **Fixed scenes** (from `meta.json`), each on two dates: 15 June (in leaf) and 15 January (bare limbs, the worst case for trunks).
   - Far: `overview`, `top`.
   - Middle, with trees: `prado`, `cibeles`.
   - Street level: `sol`, `street`.
5. **Two configurations of this viewer.** Comparing only against fixed 1 m would repeat dtla-voxel's bias.
   - Fixed level 1: the whole city at 1 m.
   - The adapted level: what the viewer settles at by itself on each device, which is what a visitor sees.
6. **Devices.**
   - Modest, real: this laptop (integrated UHD 620).
   - Phone: `profile.py --phone` only emulates the screen and pixel ratio, not the GPU [V] `scripts/profile.py:52-58`. At least one real phone opening the published site is needed, reading the counter in `web/src/perf.ts`.
   - Desktop with a dedicated GPU: it is not known whether one is available [S]. Without it, technique 1's mid-range hypothesis cannot be tested.
7. **Common protocol.**
   - Per view and configuration: 2 s warm-up, 3 repeats of 8 s, in A-B-B-A order to offset thermal drift (this laptop slows as it heats [S]).
   - Recorded: median and 95th percentile frame time, GPU time of the main pass, triangles and draw calls per pass, GPU memory and JS heap.

---

## Technique 1: adaptive levels of detail

### What dtla-voxel does

- **Levels.** Four levels (1, 2, 4, 8 m), one file per node and level. Levels 2 and 4 carry a `detail` block of thin 1 m voxels (spires, poles) [V] `dtla:scripts/tiles.py:28-29`, `:129-157`.
- **Selection.** [V] `dtla:web/src/performanceProfile.ts:9-17`, `dtla:web/src/tileSelection.ts:104-163`
  - Refines when a projected voxel exceeds 2 px and keeps the split down to 1.5 px.
  - Waits 400 ms before refining.
  - Always refines within 192 m.
  - Caps at 384 leaves and 128 MiB.
- **Atomic replacement.** Children are shown only once all siblings are ready [V] `dtla:web/src/city.ts:92-122`.
- **Popping.** Nothing is done about it (no fade or dither), and no tool measures it [V] (search of `dtla:web/src` and `dtla:web/tools`).
- **Data size.** The coarse levels add 71 % to level 1 plus foliage (5.60 MB over 7.93 MB on disk) [V] (`du` over `dtla:web/public/data/tiles`). This project's `PLAN.md:142` says "about +10 % data" [N]; that does not match the measurement.

### 1. Hypothesis

- **Where it helps:** far views (`overview`, `top`) on mid- and low-range devices. At 2 km a 1 m voxel is under a pixel [S], so almost everything would be drawn at 2–4 m.
- **Against fixed 1 m:** a large cut in triangles is expected, of the order of dtla-voxel's 22.5 → 6.1 ms [D] `dtla:docs/features/voxel-rendering-streaming.md:216-235`.
- **Against this viewer's adapted level, the comparison that matters:**
  - This viewer already replaces what is far with 8 m clay.
  - So the expected gain is not speed but quality: 2–4 m instead of 8 m at middle distance, within the same budget [S].
  - dtla-voxel did not make this comparison.
- **Street level:** no gain is expected; dtla-voxel measured 9 % slower [D] same, `:220-229`.

### 2. Fit

Prerequisites that are missing:

- **Data.** 2 and 4 m levels and the `detail` block. This touches `scripts/tiles.py` and the viewer's reader, which `CLAUDE.md` (rule 7) forbids changing "unless the plan says so".
- **Building ids.**
  - They are sent only to 1 m tiles, and they are part of the merge key and of the vertex [V] `web/src/stream.ts:178`, `web/src/mesher.worker.ts:125`, `:169`.
  - Loading building by building (`uBldOn`) and folding hidden buildings depend on them [V] `web/src/voxelMaterial.ts:160-169`.
  - dtla-voxel has nothing equivalent.
- **Real or clay blocks.** All of `city.ts` reasons in terms of `dims[1]`, `dims[8]` and per-block masks [V] `web/src/city.ts:8`, `:28-31`, `:186`. dtla-voxel's tree would replace that model entirely.
- **Foliage and trunks.** They exist only at 1 m, and trunks hang off the foliage tile [V] `web/src/stream.ts:105-111`, `web/src/trunks.ts`. At coarse levels a tree would be a block, as in the clay.
- **Collisions and picking.** The walker refuses cells that are not at the finest level [V] `web/src/nav/nav.ts:505`, `web/src/world.ts:68-71`.
- **Window shading.** It works per 1 m cell from the position, so it does not depend on the mesh. At coarse levels, though, the ground is taken at the block's corner [V] `web/src/voxelMaterial.ts:222-290`, `dtla:scripts/tiles.py:119`.

**Precedent:** turned down twice as "a large viewer change for no measured need" [N] `DECISIONS.md:172-176`, `:370`; `PLAN.md:143`.

### 3. Own baseline

In addition to the common one:

- Triangles of the clay and of each real block per view and level (`inventory.mjs`).
- What share of the visible surface is clay in each view and device at the adapted level. This is the quantity this technique would improve.
- The spread of real devices, if `perf_stats.py` has data.

### 4. Minimal experiment, in three stages with an exit after each

- **Stage A, offline (2 days, no viewer change).**
  - Generate 2 and 4 m tiles in a temporary directory, not versioned, with the `downsample` that `scripts/tiles.py:27-59` already has for 8 m.
  - Mesh them with the `cost1m.py` harness to get triangles per tile and level.
  - Apply dtla-voxel's rule (2 px / 1.5 px, 192 m) offline to the six poses.
  - Compute the resulting triangles against fixed 1 m and against the adapted level.
  - Output: expected triangles and added megabytes. No timings.
- **Stage B, fixed level (2 days).**
  - A query parameter draws the whole map at fixed 2 m or 4 m, reusing the clay's path. The streamer already handles any `s` [V] `web/src/stream.ts:89-102`.
  - It gives the real frame time per level and the images for visual validation.
  - It is the upper bound of the gain.
- **Stage C, real selection.** Only if A and B pass. This is already the implementation (3–5 weeks [S]).

### 5. Protocol

The common one, plus:

- Stage B in the six views, at 1 m, 2 m, 4 m and the current adapted level.
- A moving run: a continuous zoom from `overview` to `sol` in 20 s, repeated 3 times per variant.

### 6. Acceptance criterion (fixed now)

To move from B to C, all of these must hold on the UHD 620 laptop:

- In `overview` and `top`, the frame time estimated from stage A's mix of levels is at most 0.6 times that of fixed 1 m.
- Against the **current adapted level**, at equal frame time (±10 %): the share of the visible surface drawn at 4 m or finer rises by at least 30 points over the share drawn at 1 m today.
- In `sol` and `street`, at most a 5 % regression in the median and 10 % in the 95th percentile.
- Added download: at most +75 % over level 1 plus foliage, and only on demand.
- It passes the visual validation in point 7.

### 7. Visual validation

- **Still images.** For each pair of levels (8→4, 4→2, 2→1), place the camera at the distance where the rule would switch (coarse voxel = 2 px) and compare the two images with `abdiff.py`. Threshold: at most 2 % of pixels differing by more than 16/255.
- **In motion (required).**
  - Record the same zoom twice in stage B, once at each fixed level, and splice the sequence at the switch frame.
  - With `framerec.py`, the difference between the two frames at the splice must not exceed 1.5 times the median difference between consecutive frames in the rest of the zoom.
  - Do this at all three level switches, in leaf and bare.
- **By eye.** Review the sequences: the numbers do not catch a tower changing its silhouette.
- **If the jumps fail:** a fade or dither would be needed, which dtla-voxel does not have. That cost is not in any of the starting figures.

### 8. Risks and cost

- **Effort:** stages A and B, 4 days. Stage C, 3–5 weeks [S], by far the largest of the three.
- **What can go wrong:**
  - building ids do not carry over to 2–4 m blocks that mix two buildings;
  - trees jump from a green block to a crown with limbs when crossing to 1 m;
  - collisions with mixed levels.
- **What is lost:**
  - the block-and-clay model, which is simple and tuned (hysteresis, waiting for the trees, remembered level);
  - loading building by building;
  - literal compliance with rule 7.

### 9. Abandonment criterion

- **In stage A:** the expected triangle cut against the current adapted level is under 25 % at equal quality, or the added download exceeds 75 %.
- **In stage B:** it fails the in-motion jumps at two of the three level switches, or the street-level regression exceeds 5 %.
- **Without a mid-range device to measure on,** the technique stays unevaluated; it is not adopted on laptop figures alone.

---

## Technique 2: coarser shadow geometry

### What dtla-voxel does

- **Proxies.** Visible tiles cast no shadow. Copies that share their geometry and material cast instead, and are visible only during the shadow pass [V] `dtla:web/src/shadowTiles.ts:30-40`, `:76-89`.
- **Cap.** 4 m, except within 192 m of the camera (kept until 256 m) [V] `dtla:web/src/performanceProfile.ts:21`, `dtla:web/src/shadowTiles.ts:53-57`.
- **Dependence on technique 1.** It uses the 4 m ancestors the adaptive tree already holds; at fixed 1 m there is nothing to use [V] `dtla:web/src/shadowTiles.ts:47-62`, [D] `dtla:README.md:46`.
- **Redraws.** Shadows are not redrawn every frame there either [V] `dtla:web/src/daylight.ts:49`.

### What the figures actually say

- The "31 %" counts triangles of **the whole frame**, not of the shadow pass (9.45 M → 6.56 M) [V] `dtla:docs/measurements/shadow-culling-comparison.json`, [D] `dtla:docs/features/voxel-rendering-streaming.md:57-76`.
- It was measured with **shadows forced to redraw every frame**, which is not normal use [V] `dtla:web/tools/profile-streaming.mjs:19`, `:89-94`.
- The baseline was an intermediate state (2 m with different culling), and the cap and the culling changed together [D] same, `:70-71`.
- Main-pass GPU time fell from 8.44 to 6.71 ms under those conditions [D] same, `:65-67`.
- The image difference between coarse and exact shadows is computed but not checked against any threshold [V] `dtla:web/tools/check-shadow-lod.mjs:58-66`.

### 1. Hypothesis

- **Not at rest:** frame rate at rest will not improve, because the sun's map is not redrawn then [V] `web/src/daylight.ts:47-52`.
- **In the frames that redraw it:** moving or zooming the camera, changing the hour or day, and loading.
  - Those frames have a median of 83 ms today, against 33 ms at rest [N] `NOTES.md:1593`.
  - The peak is expected to drop, mostly in far views and on integrated GPUs [S].
- **Size of the gain:** it depends on how often the map is redrawn in real use, which has not been measured.

### 2. Fit

- **No need for technique 1.** Unlike dtla-voxel, this can be tested without it: this project already has 8 m tiles for the whole map. Not at 4 m, though, since those tiles do not exist.
- **The per-pass mechanism already exists.** A "gate" mesh switches visibility before each shadow map [V] `web/src/daylight.ts:61-84`. There is no need to patch the renderer as in `dtla:web/src/shadowTiles.ts:30-40`.
- **What to change:**
  - `web/src/daylight.ts`: what the sun's pass sees.
  - `web/src/city.ts`: keep the 15 clay tiles loaded even with the whole city at 1 m, where they are not loaded today [V] `web/src/city.ts:36-40`.
  - A depth material for the clay that does not discard where blocks are real [V] `web/src/voxelMaterial.ts:397-410`.
- **Known limitation:** the clay has no thin voxels and no seasons.
  - A bare tree would cast the shadow of a solid block [V] `web/src/voxelMaterial.ts:297-299`.
  - Lamps and spires would cast nothing [D] `dtla:docs/features/voxel-rendering-streaming.md:72-76`.

### 3. Own baseline

- `redraws.mjs`: sun-map redraws per minute while loading, orbiting, zooming, panning and at rest.
- Triangles and GPU time of one sun-map redraw, per view.
- Share of frames over 50 ms and over 100 ms during a flight between views (`web/tools/jank.mjs`, to be adapted), and how many coincide with a redraw (`web/tools/uploads.mjs` already logs it [V]).

### 4. Minimal experiment

A `?shadowlod=8` parameter (2 days [S]):

- In the sun's pass, 1 m tiles more than 256 m from the camera are hidden and the clay casts in their place.
- Within 192 m nothing changes.
- Without the parameter nothing changes at all, so A and B compare in the same build.

### 5. Protocol

- The common one, run twice and reported separately (dtla-voxel only gave the first):
  - with shadows forced to redraw every frame, for the cost of one redraw;
  - in normal use, for what a visitor notices.
- A 60 s flight between views, 3 repeats per variant: median, 95th percentile, and the count of frames over 100 ms.
- Dragging the hour slider for 10 s in `overview` and `prado` (each step redraws).

### 6. Acceptance criterion

On the UHD 620 laptop:

- The time of one sun-map redraw falls by at least 40 % in `overview` and 25 % in `prado`.
- In the flight, frames over 100 ms fall by at least 30 %.
- No view gets more than 3 % slower in the median with shadows in normal use.
- Memory grows by at most 30 MB with the whole city at 1 m (for keeping the clay loaded).
- It passes the visual validation.

### 7. Visual validation

- **Pairs.** Exact/coarse captures in the six views at 9:00, 13:00 and 19:30 (low sun), in June and January. Threshold with `abdiff.py`: mean channel difference under 2/255, and under 1 % of pixels above 16/255.
- **By eye**, three cases the threshold misses:
  - tree shadows in January;
  - shadows of towers and domes over narrow streets;
  - the 192–256 m boundary while moving the camera: no visible ring where the shadow changes shape.
- **Self-shadowing.** Check that coarse geometry does not shadow the fine visible geometry. dtla-voxel says nothing about this [V] (no comment or document addresses it).

### 8. Risks and cost

- **Effort:** baseline 1 day, experiment 2 days, adoption 2–3 more days [S].
- **What can go wrong:**
  - at 8 m the shadow is too coarse and 4 m would be needed, which depends on technique 1's data;
  - solid shadows under bare trees;
  - a visible ring at the boundary.
- **What is lost:** accuracy of distant shadows, and 15 clay tiles always in memory.

### 9. Abandonment criterion

- If `redraws.mjs` shows fewer than 6 redraws per minute in normal navigation, and fewer than 20 % of slow frames coincide with one: there is no problem to solve, and the technique is dropped without the experiment.
- If 8 m shadows fail the visual validation and technique 1 is not adopted.

---

## Technique 3: ambient occlusion out of the merge key

### What dtla-voxel has

- **It is not implemented.** `dtla:web/tools/bench-mesh-merging.mjs` runs the real mesher offline with the key altered and counts quads [V] `:1`, `:10-17`.
- **Sample:** the two heaviest tiles of levels 1, 1f and 2. Result: 20–29 % fewer quads without AO in the key [V] `dtla:docs/measurements/mesh-merging-sample.json`.
- **What it does not do:** draw anything, compare images or time frames. The document says "This is not a measured FPS gain" [D] `dtla:docs/features/voxel-rendering-streaming.md:28-34`.
- **There is no proposal for how AO would be shaded afterwards.** The project's own research recommends the opposite: "Preserve those merge keys" [D] `dtla:docs/voxel-performance-proposal.html:118`.

### 1. Hypothesis

- **Expected gains:** fewer quads in every 1 m tile, hence:
  - less GPU memory (498 MB today for the whole city [N] `NOTES.md:1426`);
  - less meshing time;
  - cheaper shadow redraws.
- **Frame rate:** little gain is expected on the laptop. Post-processing is half the frame and depends on pixels, not triangles [N] `NOTES.md:1331`, [S]. It would show most in far views at level 1 and on phones, which are memory-bound.
- **Size of the cut:** it may be smaller than dtla-voxel's 20–29 %. Here the key also holds the ground and the building, which still split quads once AO is removed [V] `web/src/mesher.worker.ts:169`.

### 2. Fit

- **What to change:** one line of the key in `web/src/mesher.worker.ts:169`, and the AO-dependent corner order (`:245`).
- **The real problem is what replaces per-vertex AO.** Once quads are merged, a per-vertex value no longer describes the inner edges. Options:

| Option | Cost | Problem |
| --- | --- | --- |
| a. Drop it and keep only N8AO | 1 day | N8AO is off below level 0.4 [V] `web/src/main.ts:48`: slow devices would get no AO at all |
| b. Compute it per fragment from a 3D occupancy texture per tile | 1–2 weeks [S] | More memory, and a texture read per fragment, exactly where this GPU is weakest |
| c. Take it out of the key only for distant tiles | 2–3 days [S] | A second meshing path; a level of detail in disguise |

- **Indirect requirement:** `scripts/cost1m.py` and the per-block costs in `zones.json` must be regenerated, because the budget is counted in triangles [V] `web/src/city.ts:59`.

### 3. Own baseline

Almost all of it exists already. `cost1m.py` meshes the 805 tiles in 57 s and gives triangles and bytes: 18.7 M triangles and 499 MB in the 2026-11-13 build [N].

### 4. Minimal experiment

- **Stage A, offline count (half a day, no viewer change).**
  - Port the idea of `bench-mesh-merging.mjs`: run this project's mesher with variants of the key over **all 805 base tiles and their foliage tiles**, not six.
  - Variants: without AO; without ground; without building; without all three. This also shows which field splits the most quads.
  - Check that face coverage does not change, as the original does [V] `dtla:web/tools/bench-mesh-merging.mjs:21-49`.
- **Stage B, option a behind a parameter (1 day).**
  - Only if A passes.
  - `?ao=merge` meshes without AO in the key, and the material ignores it.
  - It measures timings, and how much is lost visually with and without N8AO.

### 5. Protocol

- **Stage A:** deterministic, one pass.
- **Stage B:**
  - the common protocol, in the six views, at level 1 and at level 0.3 (where there is no N8AO);
  - plus meshing time per tile, GPU memory, and load time until the city is complete.

### 6. Acceptance criterion

- **Stage A:** at least 20 % fewer triangles **over the whole city** (not a sample).
- **Stage B, on the laptop:**
  - GPU memory at least 15 % lower;
  - frame time in `overview` at level 1 at least 10 % lower;
  - no view more than 2 % slower.
- It passes the visual validation at level 1 **and** at level 0.3.

### 7. Visual validation

- **Pairs.** With/without in the six views, at noon and under cloud (AO weighs more in diffuse light [V] `web/src/daylight.ts:142`).
- **What to look at:** what per-vertex AO gives and half-resolution N8AO does not:
  - edges between facade and pavement;
  - cornices;
  - the inner relief of tree crowns.
- **Threshold:** mean luminance difference under 3/255 per view, and a review by eye of `street` and `sol`.
- **Level 0.3:** there is no N8AO there. If the scene goes flat, option a does not work for the devices that most need the saving.

### 8. Risks and cost

- **Effort:** stage A half a day; stage B one day; adoption with option a, 1–2 more days; with option b, 1–2 weeks [S].
- **What can go wrong:**
  - the saving is small because ground and building dominate the key;
  - the image loses relief exactly on slow devices.
- **What is lost:** per-vertex AO, which is cheap, stable, and independent of post-processing.

### 9. Abandonment criterion

- Stage A under 15 % over the whole city: dropped.
- Option a fails validation at level 0.3, and the measured gain (under 20 % of memory) does not justify the 1–2 weeks of option b: dropped.

---

## Recommended order and dependencies

1. **Common baseline** (1–2 days). Without triangles per pass and GPU time separated from CPU, none of the criteria above can be checked.
2. **Technique 3, stage A.** The cheapest, with no viewer change, and its result changes the other two: if geometry drops by 20 %, so does what techniques 1 and 2 can save.
3. **Technique 2, redraw baseline**, and only if it clears the bar, the clay experiment.
4. **Technique 1, stages A and B.** Last, because it is the most expensive, breaks the most, and has already been turned down twice.

**Dependencies**

- Technique 2 at 8 m does not depend on technique 1 here. At 4 m it does: it needs those tiles.
- Technique 1 changes what geometry exists, so it would invalidate technique 2's measurements and force them to be repeated.
- Technique 3 changes the triangles per block: `cost1m.json` and `zones.json` must be regenerated before measuring anything else that uses the budget.
- All three compete for the same gain in far views; their percentages do not add up.

## Summary table

| Technique | Expected gain | Cost | Risk | Recommendation |
| --- | --- | --- | --- | --- |
| 1. Adaptive levels | Large against fixed 1 m in far views [D]; against the current clay, a quality gain at middle distance, unmeasured [S] | 4 days to evaluate; 3–5 weeks to adopt | High: no popping mitigation; breaks buildings, blocks, foliage and collisions; +71 % data [V] | **Evaluate later**, stages A and B only |
| 2. Coarser shadows | Lower peaks when shadows are redrawn (83 ms today); nothing at rest | 1 day baseline; 2 days experiment | Medium: coarse shadows at 8 m, solid bare trees | **Evaluate now** the baseline; the experiment only if it clears the bar |
| 3. AO out of the merge key | 20–29 % less geometry in dtla-voxel [V]; probably less here [S]; little fps gain on integrated GPUs [S] | Half a day for the count; 1 day for the prototype; up to 2 weeks if AO must be shaded per fragment | Medium: lost relief on devices without N8AO | **Evaluate now** the count; the rest only if it clears the bar |

---

## Baseline results (2026-11-14)

Measured on the development laptop: Intel UHD 620 through ANGLE on Vulkan and Mesa, headless Chromium, 1600 × 1000 at device pixel ratio 1, 11:00. `EXT_disjoint_timer_query_webgl2` is available here, so GPU time is measured per pass with timer queries.

**Tools.**
- `web/tools/passes.mjs`: triangles, draw calls and GPU time per composer pass, with the sun's and the twin's shadow maps split out of the scene pass.
- `web/tools/mergekey.mjs`: the offline merge-key count.
- `web/tools/launch.mjs`: the shared launcher. `probe`, `redraws`, `inventory`, `gpu1m`, `jank`, `abdiff` and `framerec` now use it, with the system Chromium on Vulkan.
- The raw JSON is in `data/baseline/` (not versioned).

Each figure is the median of 12 frames after 4 warm-up frames. "Adapted" is the level the viewer settled at by itself after 45 s.

### What is loaded

| | Buildings | Foliage | Trunks and limbs | Clay |
| --- | --- | --- | --- | --- |
| Whole city at 1 m, June | 18.67 M | 23.68 M | 0.47 M | — |
| Whole city at 1 m, January | 18.67 M | 23.68 M | 5.05 M | — |
| Adapted level, any view | 1.0–2.5 M | 0.2–3.0 M | 0.02–0.44 M | 0.80 M |

This explains the 42–47 M triangles per frame of the overview at level 1, an open question in the plan above: the foliage alone is 23.7 M, more than the buildings, and `scripts/cost1m.py` counts only the buildings. N8AO draws no geometry, and the twin's shadow map draws about 0.1 M.

The winter limbs add 4.6 M triangles at level 1, about 10 % of the overview.

### GPU time per pass, adapted level (ms)

| View, date | Level | Scene triangles | Scene | Twin shadow | N8AO | Bloom, tilt-shift, tone | Sun map redraw |
| --- | --- | --- | --- | --- | --- | --- | --- |
| overview, Jun | 0.14 | 4.1 M | 40.2 | 1.1 | off | 2.3 | 14.6 (3.9 M) |
| overview, Jan | 0.28 | 5.0 M | 49.9 | 1.3 | off | 3.8 | 20.1 (4.9 M) |
| prado, Jun | 0.21 | 2.0 M | 29.7 | 1.1 | off | 2.7 | 19.0 (3.4 M) |
| prado, Jan | 0.25 | 2.6 M | 36.2 | 1.1 | off | 3.3 | 34.6 (4.9 M) |
| sol, Jun | 0.43 | 2.0 M | 30.9 | 1.2 | 9.3 | 6.0 | 24.5 (3.1 M) |
| street, Jun | 0.39 | 2.2 M | 20.9 | 0.9 | off | 3.5 | 20.5 (2.0 M) |

At the level a visitor on this laptop actually gets, the scene pass costs 17–50 ms for only 2–5 M triangles: it is bound by fragments (the surface shader), not by triangles.

A sun-map redraw costs 15–37 ms, about as much as the rest of the frame.

### GPU time per pass, whole city at 1 m (ms)

| View, date | Scene triangles | Scene | N8AO | Post | Sun map redraw |
| --- | --- | --- | --- | --- | --- |
| overview, Jun | 42.8 M | 271 | 16.0 | 13.5 | 177 (42.8 M) |
| overview, Jan | 47.4 M | 312 | 15.0 | 13.1 | 217 (47.4 M) |
| top, Jun | 1.7 M | 40 | 16.6 | 10.6 | 179 (42.8 M) |
| prado, Jun | 4.9 M | 66 | 16.6 | 12.2 | 69 (15.7 M) |
| cibeles, Jun | 8.2 M | 91 | 16.7 | 12.9 | 73 (16.1 M) |
| sol, Jun | 2.0 M | 38 | 16.4 | 10.9 | 25 (3.7 M) |
| street, Jun | 13.3 M | 97 | 16.9 | 7.9 | 21 (1.9 M) |

At level 1 the scene pass follows the triangle count. The sun map takes in the whole city whenever the view is far or high (`top`: 1.7 M triangles in view, 42.8 M in the shadow map).

### Sun-map redraws (`web/tools/redraws.mjs`, overview, 21 June)

The first run of the tool had the mouse buttons swapped: in this viewer the left button pans and the right one rotates (`web/src/nav/nav.ts:69`). Its "orbiting" figure (51 redraws in 15.5 s) was a pan. The tool now uses the right buttons, takes a fixed level, and puts each redraw down to its cause: a refit of the sun's frame (`daylight.fitSun`: the focus moved or the view grew) or a change in what the map shows (`stillChanged` in `web/src/main.ts`: the tiles shown, real or clay, and their uniforms). Raw output in `data/baseline/redraws-causes.log`.

Each movement is 100 mouse steps 50 ms apart; the frames are slow, so it lasts 8–17 s at levels 0.15–0.3 and about 40 s at level 1.

| Activity | Level 0.15 | Level 0.3 | Level 1 (whole city) |
| --- | --- | --- | --- |
| Loading | 22 in 6.8 s | 29 in 10.1 s | 287 in 132 s |
| After loading, still | 0 in 25 s | 0 in 25 s | 0 in 25 s |
| Rotate 47° | 12 in 8.1 s (all set) | 19 in 9.8 s (all set) | 0 in 40 s |
| Tilt 23° | 11 in 7.9 s (all set) | 19 in 9.0 s (all set) | 0 in 35 s |
| Pan 1.3 km | 54 in 15.0 s (set 46, fit 9) | 61 in 17.2 s (set 52, fit 9) | 9 in 42 s (all fit) |
| Zoom in and back out | 2 in 8.0 s (set) | 7 in 8.9 s (set) | 0 in 21 s |

**Cause, verified.** With the whole city real (level 1), rotating and tilting never redraw the map, and a 1.3 km pan redraws it 9 times, once per refit of the frame (a sixteenth of its width; `web/src/daylight.ts:169-178`). At the levels this laptop runs at, 85–100 % of the redraws while moving come from the set of shown tiles changing. The budget gives blocks in view priority (`web/src/city.ts:70-95`). As the view turns, blocks swap between real and clay, the set of shadow casters changes, and `stillChanged` redraws the map as often as its 300 ms limit allows (`web/src/main.ts:356-357`). Panning at level 0.3 redraws it 3.5 times a second.

The refits are not the problem: 9 per 1.3 km is the design. The swaps are. Each one changes only which blocks cast at 1 m and which as 8 m clay, which have the same massing, so a map a second or so out of date would mostly differ in detail.

### Merge key (`web/tools/mergekey.mjs`, all 805 base and 805 foliage tiles)

| Key | Buildings | Foliage | City |
| --- | --- | --- | --- |
| As it is | 18.67 M | 23.68 M | 42.35 M |
| Without AO | 12.17 M (−34.8 %) | 19.93 M (−15.8 %) | 32.10 M (−24.2 %) |
| Without ground height | −0.1 % | −0.1 % | −0.1 % |
| Without building id | −0.5 % | 0.0 % | −0.2 % |
| Without all three | −35.5 % | −16.1 % | −24.6 % |

The face area per direction is identical in every variant. The plan's assumption that ground height and building id would keep splitting quads was wrong: AO is almost the whole effect.

### What the baseline says about each technique

- **Technique 3 passes stage A** (−24.2 % over the whole city, against the 20 % required).
  - The saving is in triangles and GPU memory.
  - At the adapted level on this laptop the scene pass is fragment-bound and N8AO is off. Option a (N8AO only) would leave these devices with no AO, and is unlikely to speed them up.
  - Stage B decides it.
- **Technique 2 clears its abandonment bar** (the threshold was 6 redraws per minute; moving gives 70–210).
  - A redraw costs as much as a frame.
  - But almost all of those redraws come from the budget swapping blocks between real and clay, not from the camera (see above). A cheaper fix comes first: fewer redraws for swaps while the camera moves (a longer limit than 300 ms while moving, one redraw when it stops). Technique 2 makes each redraw cheaper; this makes them rarer. Coarser geometry is only worth measuring for what is left after it.
- **Technique 1** is not yet measured. The baseline shows that at the adapted level only 2–5 M triangles are drawn, and that the cost is per fragment. That weakens the speed argument and leaves the quality argument: 2–4 m instead of 8 m clay at middle distance.

## Fewer redraws for block swaps (2026-11-14)

Adopted (`DECISIONS.md`, 2026-11-14): while the camera moves, swaps redraw the sun's map at most every 1.5 s, and once when it stops; a refit takes any pending swap with it. `redraws.mjs`, overview, 21 June (raw output in `data/baseline/redraws-stillmove.log`):

| Activity | Level 0.15, before → after | Level 0.3, before → after |
| --- | --- | --- |
| Rotate 47° | 12 → 5 | 16 → 5 |
| Tilt 23° | 10 → 5 | 20 → 6 |
| Pan 1.3 km | 51 → 13 (9 of them refits) | 56 → 16 (9 of them refits) |
| Zoom in and out | 2 → 1 | 6 → 3 |
| Loading, still | unchanged | unchanged |

Visual check with `web/tools/shadowswap.mjs`: after a 10° turn with no swap redraw at all, the stale map differs from a fresh one in 0.10 % of pixels in `prado` (all on far blocks at the top of the view; `docs/img/shadow-swap-prado-stale.png`, `-fresh.png`) and in none in `sol`, `cibeles` and `overview`.

For technique 2 this leaves the refits (9 per 1.3 km pan, by design), hour and day changes, and loading. Its experiment is only worth running if those still show as slow frames.

## Technique 3, stage B: option a behind `?ao=merge` (2026-11-14)

`?ao=merge` meshes without per-vertex occlusion (`bakeAO` in `web/src/mesher.worker.ts`, set by `web/src/main.ts`): every face gets the neutral value, so occlusion no longer splits the greedy rectangles and the material needs no change. Without the parameter nothing changes. The budget still counts each block's triangles as meshed with occlusion, so at a given level both variants show the same blocks. Raw output in `data/baseline/ao_l03_*.json` and `ao_l1_*.json`.

### Time (`web/tools/passes.mjs`, 15 June, 11:00)

Level 0.3, no N8AO, A-B-B-A (each figure the mean of its two runs; the laptop drifted by up to 12 % between A and A2):

| View | Frame GPU, baked → merged | Sun-map redraw | Triangles shown |
| --- | --- | --- | --- |
| overview | 55.8 → 47.6 ms (−15 %) | 19.6 → 15.0 ms (−23 %) | −22 % |
| top | 39.2 → 31.2 ms (−20 %) | 18.5 → 14.6 ms (−21 %) | −21 % |
| prado | 45.6 → 39.4 ms (−14 %) | 24.3 → 22.3 ms (−8 %) | −21 % |
| cibeles | 38.8 → 36.6 ms (−6 %) | 22.0 → 20.2 ms (−8 %) | −20 % |
| sol | 29.0 → 27.1 ms (−7 %) | 21.1 → 19.1 ms (−9 %) | −26 % |
| street | 20.7 → 20.4 ms (−2 %) | 22.7 → 21.0 ms (−7 %) | −26 % |

Level 1 (whole city, 42.3 → 32.1 M triangles), one run each:

| View | Frame GPU | Scene pass | Sun-map redraw |
| --- | --- | --- | --- |
| overview | 291 → 247 ms (−15 %) | 262 → 219 ms | 186 → 153 ms (−18 %) |
| prado | 109 → 90 ms (−17 %) | 76 → 60 ms | 70 → 60 ms (−14 %) |
| sol | 70 → 61 ms (−13 %) | 41 → 33 ms | 28 → 26 ms (−6 %) |

The baseline's reading that the adapted level is fragment-bound was too strong: at level 0.3 the far and middle views gain 14–20 % from a fifth fewer triangles. The time criteria pass: GPU memory −24 % by triangle count (vertex bytes follow it; not measured directly), overview at level 1 −15 %, no view slower.

### Image (`scripts/screenshot.py`, 15 June 13:00; mean luminance difference, threshold 3/255)

| View | Level 0.3, clear | Level 0.3, cloudy | Level 1, clear |
| --- | --- | --- | --- |
| street | 1.5 | 2.9 | 2.6 |
| sol | 1.4 | 2.3 | 1.4 |
| prado | 2.0 | **3.5** | 1.7 |
| overview | **4.0** | **5.7** | — |

The merged image is always lighter (the signed difference is positive in every pair). At level 1, with N8AO, it passes. At level 0.3, without N8AO, it fails in the overview and in `prado` under cloud: the dark gaps between buildings and in courtyards go, and the city reads flatter and washed out (`docs/img/ao-overview-cloudy-l0.3-bake.png` against `-merge.png`). At street level the difference is hard to see (`ao-street-cloudy-l0.3-*`, `ao-prado-clear-l1-*`).

### Verdict

- **Option a is dropped**, by the plan's own criterion: it fails the visual check at level 0.3, which is where the devices that need the saving run.
- **The saving is real and worth a second option.** It is 24 % of the geometry and 13–20 % of the frame in far and middle views, against the "little in fps" this plan expected.
- **Where the loss is:** in far views, the large-scale darkening of gaps and courtyards. Up close, N8AO or nothing makes little difference. That points to option c (occlusion out of the key only in far tiles) being the wrong way round: the far tiles are where it shows.
- **Next candidates:**
  - **Option b:** occlusion per fragment from a per-tile occupancy texture. It costs 1–2 weeks.
  - **Keep N8AO on below level 0.4:** compare its cost with the 14–20 % gained.
  - **A cheaper far-field term:** for example darkening by the depth of the gap to the neighbouring roofs, which the ground and height data already give. Not yet designed.

`?ao=merge` stays as an evaluation switch.

## N8AO's cost and its tie to technique 3 (2026-11-14)

Measured in `docs/n8ao-evaluation.md`. Two results bear on this plan:

- **N8AO fades with camera distance** (its radius is in world metres): it adds 6–20/255 of darkening up to about 2.5 km and almost none at the overview's 5.9 km. With N8AO forced on, `?ao=merge` passes the image check near and at middle distance but still fails in the overview (4.0–5.7/255). N8AO cannot replace the per-vertex occlusion where the saving matters most. That follow-up of technique 3 is dropped; a far-field occlusion term (option b, or a cheap gap darkening from heights) is what remains.
- **The pass costs 10–25 % of the frame on the UHD 620** (6–18 ms), against about 1 ms on dtla-voxel's GTX 1080 Ti. The report recommends fading it out between 4 and 6 km, and matching the tone when it is off below level 0.4.

## Technique 2: do the remaining redraws make the slow frames? (2026-11-14)

The abandonment test of technique 2, run after the swap limit. `web/tools/slowframes.mjs` records every frame's interval and whether the sun's map was redrawn in it, and why, through rotate, tilt, pan and zoom (as `redraws.mjs`), a tour of eight views with `flyTo`, and the hour dragged from 16:00 to 19:00 in 10 s. Overview, 21 June, UHD 620, at the adapted level and at level 0.3; raw output in `data/baseline/slowframes-*.log` and `.json`.

A redraw shows in its own frame's interval or the next one, since the GPU runs behind, so a slow frame "coincides" if either of them redrew. The "chance" column is the share of all frames with a redraw that near, which is what the coincidence would be if redraws had nothing to do with it.

| Activity | Redraws / min (adapted, 0.3) | Causes | Frames > 100 ms with a redraw (adapted; 0.3) | Chance (adapted; 0.3) |
| --- | --- | --- | --- | --- |
| Rotate | 39, 36 | swaps | 5 of 30 (17 %); 2 of 26 (8 %) | 8 %; 7 % |
| Tilt | 13, 34 | swaps | 0 of 2; 2 of 31 (6 %) | 2 %; 6 % |
| Pan | 63, 56 | 9 refits, 4 swaps | none slow; 0 of 3 | 6 %; 7 % |
| Zoom | 8, 19 | swaps | none slow; 0 of 1 | 1 %; 2 % |
| Fly between views | 426, 364 | 85 % refits, the rest swaps | 19 of 22 (86 %); 27 of 35 (77 %) | 39 %; 41 % |
| Drag the hour | 666, 484 | refits (the light moved) | 37 of 37; 43 of 43 | 93 %; 95 % |

The same frames split by whether a redraw was near (share over 100 ms, mean interval):

| Activity | Near a redraw, adapted | Elsewhere, adapted | Near a redraw, 0.3 | Elsewhere, 0.3 |
| --- | --- | --- | --- | --- |
| Rotate | 36 %, 85 ms (14 frames) | 15 %, 58 ms | 17 %, 74 ms | 15 %, 56 ms |
| Tilt | 0 %, 33 ms | 1 %, 36 ms | 17 %, 53 ms | 15 %, 51 ms |
| Pan | 0 %, 32 ms | 0 %, 31 ms | 0 %, 47 ms | 1 %, 39 ms |
| Fly | 9 %, 51 ms | 1 %, 31 ms | 15 %, 67 ms | 3 %, 36 ms |
| Hour | 20 %, 60 ms | 0 %, 18 ms (13 frames) | 36 %, 91 ms | 0 %, 17 ms (7 frames) |

**What it says**

- **Moving the camera by hand: the redraws are not what makes it slow.** At the rates left after the swap limit, slow frames coincide with a redraw about as often as chance would have it (0–17 % against 1–8 %), always under the 20 % bar. The slow frames while rotating and tilting (15 % of them over 100 ms) come from elsewhere, most likely the blocks the budget swaps in, which have to be uploaded.
- **Flights and hour drags: they are.** A flight refits the sun's frame almost every frame, because the focus crosses a sixteenth of the frame's width in one or two frames. A drag of the hour moves the light, and every step redraws by design. Near a redraw, frames are 20–30 ms longer on average in a flight and 40–75 ms longer in a drag, and slow frames go from 0–3 % to 9–36 %.
- **The abandonment test is not met.** It needs fewer than 6 redraws a minute and fewer than 20 % of slow frames with one; hand navigation alone gives 8–63 a minute, and flights and hour drags give 77–100 % coincidence. Technique 2 stays open, but for two moments only, both driven by refits rather than swaps: flights between views and dragging the hour.

**Next, before the `?shadowlod=8` experiment.** As with the swaps, a cheaper fix could come first:

- **Flights:** during a `flyTo`, fit the sun's frame once to cover both ends of the flight (or the path, up to the size the frame allows), and refit when it lands. Shadows mid-flight would be coarser, for 1.6 s.
- **Hour drags:** redraw at most every 100–150 ms while the slider moves, and once when it stops. The shadows would step instead of gliding.
- **Technique 2** makes each of these redraws cheaper rather than rarer. Its experiment is worth running only if the slow frames in flights and drags are still there after these two.

## Technique 2: the two cheaper fixes, and the verdict (2026-11-14)

Adopted (`DECISIONS.md`, 2026-11-14):

- **Flights:** during a `flyTo` the sun's frame is held over both ends of the flight, and follows the camera again for the last fifth. `?flyhold=0` turns it off.
- **Hour drags:** a new light direction refits the frame at most every 120 ms while the light keeps moving; the last step lands at most 120 ms after it stops. `?lightstep=0` gives the old behaviour.

`slowframes.mjs` at level 0.3, A-B-B-A (A: `flyhold=0&lightstep=0`, B: the fixes), plus one run with the light never refitting during the drag (`lightstep=1000000`), as the upper bound of what fewer or cheaper redraws can give there. Raw output in `data/baseline/holds-*.log`.

| Activity | Measure | A (before), two runs | B (fixes), two runs | No light refits |
| --- | --- | --- | --- | --- |
| Fly (8 views, 20.9 s) | sun-map redraws (refits) | 128 (108), 128 (108) | 47 (27), 46 (29) | |
| | frames drawn | 434, 419 | 457, 436 | |
| | frames over 100 ms | 24, 36 | 27, 34 | |
| | of them near a redraw | 79 %, 78 % | 44 %, 44 % | |
| Hour drag (11 s) | sun-map redraws | 96, 89 | 57, 52 | 6 (swaps) |
| | frames drawn | 126, 129 | 135, 139 | 155 |
| | frames over 100 ms | 41, 45 | 49, 41 | 45 |

Rotating and panning are unchanged, as they should be.

**Image.** `web/tools/flyshadow.mjs` freezes a flight from `overview` to `sol` (slowed to 8 s) and captures the held frame, then the frame fitted to the camera from the same pose. At 40 % of the flight both are the same: the frame is already at its largest size there. At 75 % (camera 1 km up) the held frame is 8.8 km wide against 6.6 km; shadows are a little softer, as the blur is in texels (mean difference 4.6/255, 8.6 % of pixels over 16/255; `docs/img/fly-shadow-sol-75-held.png`, `-followed.png`), for under half a second before the frame follows the camera again.

**What it says**

- The fixes do what they were for: refits in a flight fall by 74 % and redraws in an hour drag by 40 %, and 3–8 % more frames are drawn in both.
- **They do not remove the slow frames, and neither would technique 2.** Frames over 100 ms are as many after the fixes, and as many again with no light refits at all during the drag (45). The slow frames in flights and drags come from elsewhere: in flights, most likely the tiles streamed in as the view changes; in drags, not from `setHour` itself (0.5 ms of CPU per call, the sky's light 0.5 ms each time it is regenerated, no shader compiled).
- **Upper bound for technique 2.** With no light refits the drag draws 11–15 % more frames than with the fix. Making each redraw 40 % cheaper, its own acceptance bar, would give under half of that, in drags only, and nothing in hand navigation, where redraws no longer coincide with slow frames.

**Verdict: technique 2's experiment (`?shadowlod=8`) is not worth running.** What remains of the redraw cost after the swap limit and these two fixes is under the 5 % of the frame that this evaluation asks of a change. The slow frames left in flights and hour drags are a separate question, for a profile of streaming and uploads, not for the shadow pass.
