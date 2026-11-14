# Evaluation plan: the cost of the agent simulation

## Context

This plan covers the street-life simulation: cars, buses, pedestrians, bike riders, trains and traffic signals. It asks what that simulation costs and which optimisations are worth evaluating. Nothing here is implemented. It starts from two places:

- the code as it stands;
- the performance work documented in dtla-voxel, which has no agent simulation, only rendering and streaming.

Tags, as in `docs/renderer-evaluation-plan.md`:

- **[V]** verified in this repository's code, or in the installed three.js 0.186.1, postprocessing 6.39.5 and n8ao 2.0.1;
- **[D]** stated by dtla-voxel's documentation or code;
- **[S]** my assumption.

Paths prefixed `dtla:` are in `../dtla-voxel`. Paths prefixed `three:` are under `web/node_modules/three/src/`.

**Hardware caveat.** All of dtla-voxel's figures come from one desktop: i7-9700K, GTX 1080 Ti through ANGLE/D3D11, headless Chromium, 1600 × 1000 [D] `dtla:docs/rendering-profile.html:90`. It never measured an integrated GPU or a phone [D] `dtla:docs/features/voxel-rendering-streaming.md:265`. Its viewer has no simulation. Its figures are a direction, not a forecast.

**Summary of the conclusion**

- **The simulation is a small share of the frame on the development laptop** (Intel UHD 620, fragment-bound).
  - Hiding every agent saves 1.6–4.6 ms of GPU, 2–8 % of the frame.
  - The logic and the instance writes take 1.4–7.4 ms of main-thread CPU per frame.
  - The GPU, not the CPU, sets the frame time here [S, from the frame intervals below], so CPU savings show only on a device with a weaker CPU.
- **Two findings are bigger than any change to the simulation itself:**
  - With N8AO on, the transparent fountain and precipitation materials make N8AO render the scene twice more every frame [V]. That costs 1.8 ms of GPU, 3.7–5.0 % of the frame (measured below).
  - The agents' shadow map (the sun's "twin") is cleared and redrawn every frame at the city map's full 4096² size, whatever the agents' number [V]. That costs 0.9–1.2 ms, almost all of it fixed.
- **Recommended order:**
  1. **Phase 0:** the instrumentation, including a switch that turns the simulation off.
  2. **Phase 1:** three cheap, invisible changes (N8AO's transparency, instance uploads, signals).
  3. **Phase 2:** graded population and a cheaper twin map.
  4. **Structural changes** (worker, shader) only if a phone or a CPU-throttled run shows the logic as the bottleneck.

---

## Step 1: the simulation as it stands (one page)

**Agents and where they live.**

| Kind | Where | Cap | Source |
| --- | --- | --- | --- |
| Cars and buses (6 % of spawns, on roads of class ≥ 2) | a circle of 900 m around the focus (orbit target, or the camera in walk and ride) | 1 400 | [V] `web/src/sim/life.ts:22`, `:160-176`; `web/src/sim/meshes.ts:4`; `web/src/main.ts:156` |
| Pedestrians | same circle, on footpaths | 4 000 | [V] `life.ts:178-182` |
| Bike riders | same circle, on footpath edges with a bike weight | 1 200 | [V] `life.ts:184-189` |
| Trains (8 tracks, 32 services, 3–8 cars each) | the whole map | 240 cars | [V] `web/src/sim/trains.ts:15-24` |
| Signal heads | the whole map | 1 157 | [V] `meshes.ts:63-68`, `life.ts:758-770` |
| Trams | none: the data has 0 routes; the code is idle | 240 sections | [V] `life.ts:102` |

- **Zone changes.** The zone is recomputed when the focus moves more than 120 m (`life.ts:120`). Recomputing (`setActive`, `:140-157`) walks all 3 224 roads and 11 249 footpath edges and drops the agents left outside [V].
- **Population.** It depends only on the hour (Gaussian "bells" with peaks at 8:00 and 17:00) and, for bikes, on the season (`life.ts:121-130`, `:387-394`) [V].
  - It does not depend on camera distance, render level, device or weather [V].
  - Measured at 17:00 after 30 s: 487–705 cars, 1 538–1 583 people, 7–16 riders. At 3:00: 102–142 cars, 138–140 people (tables below).
- **Logic.** A fixed step of 1/30 s through an accumulator, 0–3 steps per frame. `dt` is capped at 0.1 s (`life.ts:19`, `:117-132`) [V]. Each step:
  - breaks deadlock cycles every 0.5 s (O(cars));
  - spawns and trims agents;
  - `snapshot()`: three path lookups per car, an 8 m hash grid, and a 5 × 5-cell neighbour query per car;
  - `stepCars`: the Intelligent Driver Model (IDM), lane changes, junction boxes, OSM turn restrictions;
  - `stepPeople` and `stepRiders` (`life.ts:384-405`, `:408-473`, `:589-633`) [V].
  - There is no pathfinding: the next edge is a random weighted choice. Signals are fixed-time and computed from the clock (`life.ts:14`, `:28-32`) [V].
- **Every frame**, whatever the step: `trains.update`, then `render()` (`life.ts:133-134`, `:651-659`) [V].
  - Cars are interpolated between the last two steps, people extrapolated and smoothed.
  - Every agent's matrix is rewritten, and its colour where it has one, including the body colour, which never changes.
  - All 1 157 signal lamps are rewritten every frame, though they only change at phase boundaries (`life.ts:758-770`) [V].
- **Drawing.** 15 `InstancedMesh`es (11 for street life, 4 for trains), all with `frustumCulled = false` (`meshes.ts:17-24`, `:69`; `trains.ts:44-52`) [V]. With `count = 0` the GL draw is skipped (`three:renderers/webgl/WebGLBufferRenderer.js:21`) [V].
- **Uploads.** `setCount` sets `needsUpdate` on every matrix and colour buffer every frame, empty ones included (`meshes.ts:74-80`) [V].
  - Without `updateRanges`, three 0.186.1 uploads the whole array with `bufferSubData`, whatever `count` is (`three:renderers/webgl/WebGLAttributes.js:87-90`) [V].
  - `addUpdateRange(start, count)` uploads only those elements; units are array elements, so 16 per matrix (`three:core/BufferAttribute.js:181-192`, `WebGLAttributes.js:103-147`) [V]. Nothing in `web/src` uses it [V].
  - Measured: 1 353 KB flagged per frame, against 205–571 KB in use.
- **Shadows.**
  - Cars, buses, riders, people, poles and trains cast shadows (`meshes.ts:45-64`, `trains.ts:46`) [V].
  - They cast into a second directional light, `twin`, of zero intensity. Its map is the same size as the sun's (4096², 2048 on phones) and its frame is copied from the sun's every frame (`web/src/daylight.ts:37`, `:66-69`, `:224-234`; `main.ts:69`) [V].
  - It keeps three's default `autoUpdate = true`, so it is cleared and redrawn every frame (`three:renderers/webgl/WebGLShadowMap.js:170`) [V]: at night, in the overview at 6 km, and while the agents are hidden during loading.
  - A gate mesh switches the casters so that each map sees only its own (`daylight.ts:75-97`) [V].
  - Every shadowed fragment of the city samples both maps (`daylight.ts:7-17`) [V].
- **Culling.**
  - Agents are drawn with no frustum, distance or size culling [V].
  - The simulation stops only while the city is loading (`main.ts:358-361`) [V].
  - In the overview, the 900 m circle is fully simulated and drawn, at a few pixels per car [S].
- **Measurement tools.**
  - On the Linux and Vulkan launcher:
    - `web/tools/probe.mjs`: GPU per frame without a part (`life` among them), plus `lifeUpdateCpuMs`;
    - `web/tools/passes.mjs`: GPU per pass, with the twin's shadow split out;
    - `web/tools/allocs.mjs`: heap sampling by function;
    - `web/tools/slowframes.mjs`, `jank.mjs` and `inventory.mjs`.
  - The traffic tools (`simtest`, `simlong`, `stuck`, `flow`, `roots`, `chains`) and `longtasks` still launch Chrome with macOS's Metal flags, so they do not run here as they stand [V].
  - No URL parameter turns the simulation off or changes its population [V].

**Not determined.**
- The CPU and GPU cost on a phone.
- Whether the main thread, not the GPU, ever sets the frame time on a real device.
- The cost of `bufferSubData` on an integrated GPU's shared memory.
- Whether the traffic tools' figures are stable from run to run, since the simulation is not seeded.

---

## Step 2: dtla-voxel's improvements, and whether they carry over

| dtla-voxel | Problem there | Measured there [D] | Equivalent in this simulation |
| --- | --- | --- | --- |
| **Shadow-map cache** (`615991b`, padded fit `7466d95`; `dtla:web/src/daylight.ts:49`, `:59`, `:139-175`) | an 8192² map redrawn every frame: 1 309 of 1 575 draw calls | frame −24 % Civic Center (9.02 → 6.89 ms), −33 % Bunker Hill, −20 % overview (`dtla:docs/rendering-profile.html:23-31`); the padded fit was never timed | **Yes, by analogy.** The city's map is already cached here (Warsaw's design, refined in `DECISIONS.md` 2026-11-14). The twin is the uncached one: it must change when agents move, but not when none are on screen or at night; and its frame could cover the agents' 1.8 km circle instead of the city's frame. → C3 |
| **Simplified shadow geometry, per-pass culling** (`dtla:web/src/shadowTiles.ts`) | shadows cast at the visible level of detail | 4 m with box culling against 2 m with spheres: −31 % triangles, −20 % main-pass GPU (8.44 → 6.71 ms) (`dtla:docs/features/voxel-rendering-streaming.md:57-83`) | **Partly.** The agents' shadow geometry is already small (0.09 M triangles in the twin pass). The analogue is not drawing agents' shadows where they cover under a pixel, and per-pass culling of agent meshes (`frustumCulled = false` today). → C3, C6 |
| **Idle rendering** (`2787413`; `dtla:web/src/main.ts:79`, `:316-328`) | redrawing a still scene | **no measurement exists** | **No.** Agents move in every frame they are shown, so a still camera is not a still scene. An idle mode would mean freezing the agents, a product decision, not an optimisation. → C12, not to be evaluated |
| **Fewer allocations per frame** (`98283fe`, `d328345`; `dtla:web/tools/profile-gc.mjs`) | 0.7–1.2 MB per frame of garbage | −72 % to −98 % bytes per frame; GC time 57 → 6.5 ms per 8 s; **mean frame time unchanged** (deleted artifacts in history, not in docs) | **Yes, directly.** Here the simulation makes about 69 % of the frame's garbage (measured below), and `DECISIONS.md` 2026-11-13 already halved it. dtla-voxel's own result warns that this buys fewer GC pauses, not frames. → C9, C10 |
| **Upload limit per frame** (`dtla:web/src/performanceProfile.ts:18`, `dtla:web/src/stream.ts:249-314`) | tile meshes arriving together, uploaded in one frame | **no before/after measurement**; the 2 MiB value is not justified | **By analogy, inverted.** The upload here is steady, not bursty: 1.35 MB every frame, 2.4–6.6 times what is used. The fix is not a budget but uploading only what changed. → C1 |
| **Quality profiles in one object** (`dtla:web/src/performanceProfile.ts:5-53`) | settings scattered, able to bypass caches | not a performance change; `mobile` profile chosen by coarse pointer and small screen | **Yes.** This simulation has no quality knob at all. A profile could set population scale, twin map size and logic rate together. → C7 |
| **Measurement protocol** (`dtla:web/tools/profile.mjs`; `dtla:docs/features/voxel-rendering-streaming.md`) | — | warm-up 1.5 s, 6 s samples, 2 rounds in reversed order, timer queries per pass, mean and p95; no p99; no automated thresholds | **Yes.** This repository already uses timer queries per pass, A-B-B-A order and a 5 % bar (`docs/n8ao-evaluation.md`). What is missing for the simulation: a switch to turn it off, a CPU split, p99, and seeded long runs. → Phase 0 |
| **Negative result: packed 16-byte quads** (`1034c95`) | geometry memory | 741 → 206 MiB, but frame 19.40 → 27.67 ms (+43 %) on the GTX 1080 Ti; cause not isolated (`dtla:docs/features/voxel-rendering-streaming.md:214-239`) | **A warning for C11.** Moving agent animation into the shader shrinks uploads but adds vertex work; less data is not a faster frame. |
| **Negative results: boxes for every bounding sphere, removing post effects** | — | inside the noise (`dtla:docs/voxel-performance-proposal.html:61`; `dtla:docs/rendering-profile.html:41-47`) | Bounding checks per agent mesh may cost more CPU than they save (C6). |

---

## Baseline (measured 2026-11-14)

**Setup.** Development laptop: Intel UHD 620 through ANGLE on Vulkan and Mesa, headless Chromium, 1600 × 1000 at device pixel ratio 1. Level 0.3 is where this laptop adapts to, canvas 1024 × 640. The date is 21 June, clear. Raw output is in `data/baseline/sim_*` (not versioned). The tools that wrap viewer methods at runtime are scratch scripts, not committed, and change no code. Each figure is a single run unless marked A-B-B-A.

**GPU per pass** (`passes.mjs`, 17:00, the viewer's loop paused while measuring):

| View | Frame GPU | Scene | Twin shadow pass | Twin share |
| --- | --- | --- | --- | --- |
| sol | 28.4 ms | 23.6 ms | 1.17 ms (0.09 M triangles, 10 calls) | 4.1 % |
| cibeles | 40.1 ms | 34.8 ms | 1.22 ms | 3.0 % |
| prado | 47.5 ms | 42.2 ms | 1.12 ms | 2.4 % |
| overview | 58.1 ms | 52.6 ms | 1.18 ms | 2.0 % |

At 3:00 the twin pass costs the same, 1.13–1.24 ms. Its cost is the clear and the traversal of a 4096² map, not the agents [S, from the equal figures at very different populations].

**Hiding all agents** (`probe.mjs`, render level from the slider, GPU of one composer pass):

| View | Budget | Frame, 1× | Without agents | Saving |
| --- | --- | --- | --- | --- |
| sol | 1.36 M | 78.8 ms | 76.2 ms | 2.6 ms (3.3 %) |
| sol | 0.20 M | 67.4 ms | 65.8 ms | 1.6 ms (2.4 %) |
| overview | 0.98 M | 98.7 ms | 96.1 ms | 2.6 ms (2.6 %) |
| overview | 0.20 M | 82.1 ms | 78.6 ms | 3.5 ms (4.3 %) |
| sol, N8AO on, level 0.3 | — | 35.2 ms | 32.5 ms | 2.7 ms (7.7 %) |
| cibeles, N8AO on, level 0.3 | — | 47.5 ms | 43.6 ms | 4.0 ms (8.3 %) |

**CPU and uploads with the simulation running** (scratch script wrapping `life.step`, `life.render`, `life.update`; 10 s after 30 s of fill):

| View, hour | Cars / people / riders | fps | Steps per frame | `update` per frame | of it logic / drawing | Per step | Flagged / used per frame | Scene renders per frame |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sol 17:00 | 487 / 1 538 / 7 | 33 | 0.90 | 4.5 ms | 2.2 / 2.3 | 2.4 ms | 1 353 / 503 KB | 1 |
| cibeles 17:00 | 705 / 1 583 / 16 | 24 | 1.22 | 6.0 ms | 3.6 / 2.4 | 2.9 ms | 1 353 / 571 KB | 1 |
| overview 17:00 | 680 / 1 558 / 9 | 17 | 1.49 | 7.0 ms | 4.5 / 2.5 | 3.0 ms | 1 353 / 559 KB | 1 |
| sol 3:00 | 102 / 138 / 0 | 36 | 0.83 | 1.4 ms | 0.7 / 0.7 | 0.8 ms | 1 353 / 205 KB | 1 |
| overview 3:00 | 142 / 140 / 0 | 18 | 1.47 | 2.2 ms | 1.4 / 0.8 | 1.0 ms | 1 353 / 216 KB | 1 |
| sol 17:00, N8AO on | 486 / 1 538 / 7 | 27 | 1.09 | 4.7 ms | 2.4 / 2.3 | 2.2 ms | 1 353 / 503 KB | **3** |
| overview 17:00, N8AO on | 680 / 1 558 / 9 | 15 | 1.51 | 7.4 ms | 4.8 / 2.6 | 3.2 ms | 1 353 / 559 KB | **3** |

- **Steps per frame rise as fps falls.** The logic costs more where the frame is already slow. This is the fixed step catching up, not a spiral: `dt` is capped at 0.1 s.
- **The flagged bytes do not change** with population or hour: every buffer is flagged at full capacity.
- **The simulation is not culled by distance.** The overview simulates and draws as many agents as `cibeles`.

**N8AO's two extra renders** (scratch script, N8AO forced on, level 0.3, `transparencyAware` toggled at runtime, A-B-B-A, median of 12 frames):

| View | Auto-detected (true) | Forced false | Saving |
| --- | --- | --- | --- |
| sol | 37.31, 37.19 ms | 35.19, 35.62 ms | 1.85 ms (5.0 %) |
| cibeles | 48.70, 48.64 ms | 46.58, 47.17 ms | 1.80 ms (3.7 %) |

- **Cause** [V]: n8ao's `detectTransparency` sets `transparencyAware` whenever any material in the scene is transparent, visible or not (`web/node_modules/n8ao/dist/N8AO.js:1806-1813`). The fountains' material (`web/src/fountains.ts:10`) and the precipitation's (`web/src/weather.ts:75`) always are.
- **Effect:** `renderTransparency` then calls `renderer.render(scene, camera)` twice per frame (`N8AO.js:1880-1916`).
- **Shadows:** each call runs the shadow pass again, and the twin, still on `autoUpdate`, is cleared and redrawn in both (`three:renderers/webgl/WebGLShadowMap.js:170`, `:336-339`).
- **Scope:** this is not the simulation's own cost, but it is triggered by animated scene content and doubles the twin's work. It goes in this plan as C4.

**Allocations** (`allocs.mjs`, Gran Vía, level 0.3, still view): 23.1 MB/s, 559 kB per frame.
- The simulation's functions make about 15.9 MB/s of it, 69 %: `snapshot` 4.0, `carObstacle` 4.0, closures in `life.ts` 4.5, `path.at` 1.5, `stepPeople` 0.9, `stepCars` 0.6.
- The profiler reports positions in the served module, so its line numbers do not match the source.

---

## Step 3: candidates

| # | Candidate | From |
| --- | --- | --- |
| C1 | Upload only the instances in use, and only buffers that changed | code; three's `addUpdateRange` |
| C2 | Signal lamps rewritten only at phase changes; constant colours written once | code |
| C3 | A cheaper twin map: off when nothing casts into it, a frame fitted to the agents' circle, a smaller map | code; dtla-voxel's shadow cache |
| C4 | N8AO's transparency renders off | code (three, n8ao) |
| C5 | Simulate and draw less when agents are under a pixel (far views) | code; dtla-voxel's idle rendering by analogy |
| C6 | Frustum and distance culling of agents, per pass | code; dtla-voxel's per-pass culling |
| C7 | Population, twin map size and logic rate graded in one quality profile | dtla-voxel's profiles |
| C8 | Logic at 15–20 Hz instead of 30 Hz | code |
| C9 | Cheaper structures in the logic: lane lists, `pose()`, `carObstacle`'s closures, `setActive` | code; dtla-voxel's allocation work |
| C10 | Allocations per frame in the drawing functions and trains | code; dtla-voxel's allocation work |
| C11 | Structural: animation in the vertex shader, or the logic in a web worker | code; dtla-voxel's packed-quad result as a warning |
| C12 | Idle rendering as in dtla-voxel | dtla-voxel |
| C13 | Removing the idle tram code | code |

---

## Step 4: the plan

### Phase 0: instrumentation (1–1.5 days, no visible change)

Without it no criterion below can be checked.

1. **`?life=0`** skips `life.update` and hides the group. It gives the simulation's total cost in one A/B pair, CPU and GPU together, in normal running and not with the loop paused.
2. **`?pop=<0..1>`** scales the density targets. It separates the cost per agent from the fixed cost, and is C7's experiment too.
3. **A CPU split in `web/src/perf.ts`**, behind `?perf=sim` (off by default): the mean and p95 of `step` per call, `step` per frame, `render` per frame, and the whole frame's main-thread time (from the start of the rAF callback to the end of `composer.render`). The scratch wrapper used above becomes a tool, `web/tools/simcost.mjs`.
4. **Bytes flagged per frame** for instance buffers (by attribute `version`), also in `simcost.mjs`.
5. **The traffic tools on `launch.mjs`**:
   - `simtest`, `simlong`, `stuck`, `flow`, `roots`, `chains`;
   - `flow.mjs` passes a `sim=` parameter the viewer ignores, which should be removed;
   - `simlong.mjs` reads `L._fps` and `L.nAssert`, which do not exist.
6. **A seeded `Math.random`** in those tools, as `probe.mjs` already does. Two runs of the same build should then give the same traffic, so a difference in traffic statistics can be blamed on the change.
7. **p99 of the frame interval** in `slowframes.mjs` and `jank.mjs`, as well as p95.
8. **A weak-CPU device.** Chrome's `Emulation.setCPUThrottlingRate` at 4× and 6×, through CDP from Playwright. This is the stand-in for a mid-range phone's CPU. The UHD 620 is already a weak GPU. A real phone opening the published site with `?perf=sim` stays a gap until one is available.

**Baseline protocol.** Each scene runs at 17:00 (peak) and 3:00 (few agents):

- `street` and `sol`: many agents, close;
- `cibeles`: middle distance;
- `overview`: far.

For each scene and configuration: 2 s of warm-up, then 3 samples of 8 s in A-B-B-A order. Record:

- the frame interval (median, p95, p99);
- the GPU per pass (`passes.mjs`);
- the main-thread time;
- `step` and `render`;
- bytes flagged;
- GC time (`allocs.mjs`).

Each at no throttling and at 4× CPU throttling, and `?life=0` against default.

**Acceptance bar for every candidate** (the bar of `docs/n8ao-evaluation.md`): a change must save at least 5 % of the frame in at least one scene and configuration, with no other scene more than 2 % worse in the median.

- **CPU-only changes** are judged at 4× throttling, where the main thread can set the frame time.
- **Changes that save GC** are judged on p99 and GC time instead, with a bar of −30 %.

### Candidates

Each candidate below gives the same fields: evidence, expected gain, the change, an experiment that a switch turns on and off, an acceptance criterion fixed now, validation, risk and effort, interactions, and when to abandon it.

**Two validations are common to all of them:**
- **Image:** pairs of screenshots compared with `abdiff`, with a mean difference under 3/255 and under 1 % of pixels over 16/255.
- **Traffic**, for anything that touches vehicle logic: three seeded runs of 15 minutes at 17:00 with `flow`, `stuck` and `simlong`. Exits per minute and mean speed must stay within ±5 % of the baseline. Cars stopped for more than 60 s must not rise. The stuck count must not grow between the first and the last 5 minutes, which would mean gridlock building up.

#### C1. Upload only what is used and what changed

- **Evidence.**
  - `setCount` flags every buffer every frame (`web/src/sim/meshes.ts:74-80`) [V].
  - three uploads the whole array (`three:renderers/webgl/WebGLAttributes.js:87-90`) [V].
  - 1 353 KB are flagged per frame against 205–571 KB used, measured.
  - Poles never change after creation, so they are already right.
  - Tram buffers have count 0 and are flagged anyway [V].
- **Expected gain.** 0.8–1.1 MB less copied per frame. On an integrated GPU with shared memory this is a CPU-side driver copy, of the order of 0.1–0.5 ms [S]. Likely under the 5 % bar alone. It also benefits C5 and C7, which lower the counts.
- **Change.**
  - `setCount` adds `addUpdateRange(0, n × itemSize)` before flagging.
  - It does not flag when `n` is 0 and was 0 before.
  - The body colour is written only when a car is spawned (see C2).
- **Experiment.** `?uprange=0` keeps the full uploads.
- **Acceptance.** Main-thread time −5 % at 4× throttling in `cibeles` at 17:00, or GPU −5 %, measured with `passes.mjs` while the loop runs.
- **Validation.** Image pairs (none of it should differ); `simcost` shows the bytes flagged equal to the bytes used.
- **Risk.** Low. One trap: three merges ranges and clears them after each upload (`WebGLAttributes.js:103-147`); a range set when no upload follows stays for the next. Half a day.
- **Interactions.** It multiplies the saving of C5 and C7.
- **Abandon** if the 4×-throttled saving is under 2 % in every scene. Even then keep it if it is still under 20 lines, since it costs nothing at run time.

#### C2. Signals only at phase changes; constant colours written once

- **Evidence.**
  - `drawSignals` composes 1 157 matrices and sets 1 157 colours every frame, though the lamps change only at the boundaries of a 64 s cycle (`life.ts:758-770`, `:14`) [V].
  - Car body and people's shirt colours are rewritten every frame (`life.ts:661-679`, `:703-731`) [V].
- **Expected gain.**
  - Signals: about 1 157 × (compose + setColorAt) per frame, an estimated 0.1–0.3 ms of CPU [S].
  - Plus 88 KB of uploads per frame.
  - Colours: a few hundred `setColorAt` per frame.
- **Change.**
  - Signals: keep the last phase per controller and rewrite only the heads whose phase changed. The matrix changes only with the lamp's height, so recompute it then.
  - Colours: since agents are compacted when one leaves, write the colour on spawn and on compaction only.
- **Experiment.** `?sigcache=0` keeps the old path.
- **Acceptance.** `render` per frame −15 % in `sol` at 17:00, or main-thread −5 % at 4× throttling.
- **Validation.**
  - Image pairs at one signal phase.
  - Frame-by-frame lamp colours compared with the old path over a full 64 s cycle: they must be identical.
- **Risk and effort.**
  - Risk: low for signals. Colours tied to compaction need care: a colour must move with its agent when the array is compacted.
  - Effort: half a day.
- **Abandon** if `render` falls less than 10 %.

#### C3. A cheaper twin map

- **Evidence.**
  - The twin is redrawn every frame at the sun's map size, over the sun's frame (`web/src/daylight.ts:66-69`, `:224-234`) [V].
  - It costs 1.1–1.2 ms whatever the population: the same at 3:00 as at 17:00.
  - In the overview its frame is about 6.6 km wide for agents within a 1.8 km circle [V].
  - It is also redrawn at night, while the agents are hidden, and twice more per frame when N8AO's transparency is on (C4) [V].
- **Expected gain.** Up to the pass's 0.9–1.2 ms (2–4 % of the frame). The sampling of the twin's map by every shadowed fragment remains.
  - **(a)** Skip the redraw when no caster is in view of the light or the agents are hidden. At night, when the sun's light is below its threshold, skip it entirely.
  - **(b)** Fit the frame to the 900 m circle plus the trains' tracks in view. This is a resolution gain more than a time gain.
  - **(c)** A 2048² map on all devices.
  - Together these likely take the twin from 1.2 to about 0.3 ms [S].
- **Change.**
  - `twin.shadow.autoUpdate = false`, with `needsUpdate` set each frame unless (a) applies.
  - Its own frame, quantised like the sun's.
  - The map size as a profile setting (C7).
- **Experiment.** `?twin=old|lazy|fit|small`, combinable.
- **Acceptance.** The twin pass −50 % in every scene, and the frame −2.5 % in `sol` and `cibeles`. The bar is half the usual 5 %, because the whole pass is under 5 %. With C4 (one candidate's pair of switches), at least 5 %.
- **Validation.**
  - Image pairs at 9:00, 13:00 and 19:30 in `sol` and `street`, where agents' shadows are visible. (b) must not cut a shadow at the circle's edge.
  - At night: a pair to check that nothing changed.
- **Risk.**
  - (a) Low.
  - (b) Medium: two frames to keep consistent; a long train shadow outside the circle.
  - (c) Coarser agent shadows.
- **Effort.** 1 day.
- **Interactions.**
  - **C4:** C4 removes the two extra redraws per frame first.
  - **C5:** C5's far view would turn the twin off entirely.
- **Abandon** if (a) and (c) together save under 0.5 ms; then (b) only for image quality, judged by eye.

#### C4. N8AO's transparency renders off

- **Evidence.** Measured: 3 scene renders per frame instead of 1 with N8AO on, and −1.8 ms (3.7–5.0 %) with `transparencyAware` forced false, A-B-B-A. The mechanism is in the Baseline above.
- **Expected gain.** 1.8 ms where N8AO runs, at level 0.4 or above and nearer than 5.5 km. It also removes two of the twin's three redraws per frame.
- **Change.**
  - Set `n8.configuration.transparencyAware = false` explicitly in `web/src/post.ts`; that also turns off auto-detection (`N8AO.js:1670-1672`).
  - Alternatively, if the fountains or rain need it: set it true only while precipitation or a fountain is visible.
- **Experiment.** `?n8transp=auto|off`.
- **Acceptance.** −3 % of the frame in `sol` and `cibeles` with N8AO on (already measured at 3.7–5.0 %; to confirm in normal running), and passing the image validation.
- **Validation.** Image pairs with N8AO on:
  - at the fountains (Cibeles, Neptuno) in daylight;
  - in rain and in snow, where transparent particles in front of geometry could pick up AO darkening.
  - Judged by eye in motion as well.
- **Risk and effort.**
  - Risk: low.
  - Effort: an hour plus the validation.
  - Strictly it is not the simulation's cost, but it is the largest single item found.
- **Abandon** if the fountain or rain pairs fail the threshold. Then evaluate the conditional variant.

#### C5. Less simulation and drawing in far views

- **Evidence.**
  - The overview, at 6 km, simulates and draws the same 680 cars and 1 558 people as `cibeles`, measured.
  - At the overview's distance a car is under 2 px long: 4.6 m × 2 005 px focal / 5 900 m ≈ 1.6 px [S].
  - The overview has the most steps per frame (1.49) because its fps is lowest.
- **Expected gain.**
  - Overview: the whole simulation, 7.0 ms of main thread and 2.6–3.5 ms of GPU (3–4 %).
  - Middle views: a fraction of that.
- **Change.** Grade by the camera's distance to the focus:
  - beyond about 3 km, skip drawing and the twin;
  - beyond 4.5 km, stop stepping and resume where it stopped;
  - in between, step at half rate.
  - Graded, not cut, to avoid a visible pop at the threshold. The thresholds are set from the pixel size, not guessed: a car under 1 px.
- **Experiment.** `?farlife=0` keeps the current behaviour.
- **Acceptance.** Overview frame −5 % without throttling or main thread −10 % at 4×; no change at all in `sol`, `street` or `cibeles`.
- **Validation.**
  - A zoom from the overview to `sol` recorded with `framerec.mjs`. The agents' fade must not exceed the 1.5× median frame-difference rule of `docs/renderer-evaluation-plan.md` (technique 1, point 7).
  - Traffic: after a pause, the statistics recover within 30 s.
- **Risk.** Medium: a still city from afar may read as frozen. That is a product choice, to be shown to the user before adoption.
- **Effort.** 1 day.
- **Interactions.** It overlaps C6 and C7; if C7 grades population by level, C5 is its distance axis.
- **Abandon** if the overview gains under 3 %.

#### C6. Frustum and distance culling of agents, per pass

- **Evidence.**
  - `frustumCulled = false` on all agent meshes (`meshes.ts:21`, `trains.ts:47`) [V].
  - three culls an `InstancedMesh` by one bounding sphere for all its instances, computed once (`three:objects/InstancedMesh.js:151-179`, `three:math/Frustum.js:148-152`) [V]. With agents spread over a 1.8 km circle, that sphere is always in view, so turning culling on would cull nothing.
- **Expected gain.**
  - Only instance-level culling helps: writing only the instances in the camera's frustum (or the light's, for the twin) into the buffers.
  - About half the agents of the circle are behind the camera in a street view [S].
  - Saving: part of `render` (2.3–2.5 ms) and of the vertex work of 0.1 M triangles, which is small.
- **Change.** In the draw functions, test each agent's point against the camera's frustum, widened by its size and its shadow length. Two counts per mesh would be needed for the main pass and the twin pass, so either:
  - one list for the union of both frusta; or
  - a separate `InstancedMesh` for the twin, which doubles the uploads.
- **Experiment.** `?lifecull=0`.
- **Acceptance.** `render` −30 % in `street` at 17:00, and frame −2 % at 4× throttling.
- **Validation.**
  - Image pairs in `street` and `sol`, including agents' shadows cast into view from outside it.
  - The ride and follow modes (`life.pose`) unchanged.
- **Risk.** Medium: the frustum test costs CPU per agent; shadows from off-screen agents.
- **Effort.** 1 day.
- **Interactions.** It shares the per-agent loop with C1 and C2.
- **Not to be evaluated as a plain `frustumCulled = true`:** with one sphere per mesh it cannot cull anything here.
- **Abandon** if `render` falls under 20 %.

#### C7. Population, twin size and logic rate in one profile

- **Evidence.**
  - Population is fixed by the hour (`life.ts:121-130`, `:387-394`) [V].
  - The only device setting that touches agents is the shadow map size on phones (`main.ts:69`) [V].
  - dtla-voxel puts all such settings in one frozen object chosen once [D] `dtla:web/src/performanceProfile.ts:5-53`.
- **Expected gain.**
  - Cost scales with population: at 3:00, with a fifth of the agents, `update` is 1.4–2.2 ms against 4.5–7.0, measured.
  - A 0.5 scale on weak devices: about −40 % of logic and drawing CPU [S, from the 3:00 figures].
- **Change.**
  - A `sim` block in a quality profile: `population`, `twinMapSize`, `stepHz`.
  - Chosen from the render level the viewer already remembers and adapts (`main.ts` `level`), not from device detection: the level is the measured capability.
  - Below level 0.3: population 0.6. Below 0.15: population 0.4.
- **Experiment.** `?pop=` (from Phase 0) for the curve, then `?simprofile=0` to turn the grading off.
- **Acceptance.**
  - At 4× throttling, main thread −15 % at level 0.15 in `cibeles` at 17:00.
  - The visual density, judged by eye in `sol` at 17:00, must still read as a busy city. Shown to the user, since it changes what is seen.
- **Validation.** Traffic with fewer cars: mean speed rises a little, which is expected. The stuck count must not grow.
- **Risk.** Low to medium. The adaptive level reacts to frame time, so lowering the population may raise the level, which costs more GPU. Measure the level the viewer settles at, not only the frame time.
- **Effort.** 1 day.
- **Interactions.**
  - C5 is its distance axis.
  - C8 can be one of its fields.
- **Abandon** if the population curve shows the cost is mostly fixed: under 30 % less CPU at a 0.5 scale.

#### C8. Logic at 15–20 Hz

- **Evidence.**
  - `STEP = 1/30` (`life.ts:19`) [V].
  - Cars are interpolated between the last two steps, and people are extrapolated and smoothed (`life.ts:661-679`, `:703-731`) [V]. So drawing does not need 30 Hz.
  - One step costs 2.2–3.2 ms at 17:00, measured.
- **Expected gain.** At 20 Hz, a third fewer steps: about −1 to −1.5 ms of main thread at 17:00 [S].
- **Change.** `STEP` from the profile (C7). IDM is stable at 0.05 s for these parameters [S, to be checked].
- **Experiment.** `?stephz=30|20|15`.
- **Acceptance.**
  - Main thread −10 % at 4× throttling.
  - The traffic validation passes with the stricter bar: exits per minute within ±3 %.
- **Validation.**
  - Traffic, as above.
  - Video of `street` at 17:00 checked by eye for stutter in cars and people. Interpolation hides most of it; the extrapolated people may overshoot at corners.
  - Junction boxes and deadlock timers are in seconds, so they keep their meaning [V `life.ts:386`].
- **Risk.** Medium: collisions missed at a coarser step, and cars overlapping at junctions.
- **Effort.** Half a day plus the long runs.
- **Abandon** if 20 Hz fails the traffic bar. 15 Hz is tried only if 20 Hz passes.

#### C9. Cheaper structures in the logic

- **Evidence** [V]:
  - lane lists are arrays changed with `indexOf`/`splice` (`life.ts:493-518`);
  - `pose()` runs `includes` over the whole list every frame while riding (`life.ts:808`);
  - `carObstacle` makes three closures per car per step (`life.ts:299-362`);
  - `setActive` makes about seven map/filter passes over 14 500 edges (`life.ts:140-157`);
  - `stepRiders` and the people trim rebuild arrays every step (`life.ts:395-399`, `:614`).
  - `DECISIONS.md` 2026-11-13 rejected rewriting `carObstacle` (about 3.5 MB/s) for the risk to Warsaw's traffic logic.
- **Expected gain.**
  - GC: the simulation makes 69 % of the garbage, about 16 MB/s, measured.
  - dtla-voxel cut its garbage by 72–98 % but saw no change in mean frame time [D]. Expect the same here: fewer GC pauses, so a better p99, not a better median.
  - `setActive` is a spike when the focus moves 120 m, unmeasured.
- **Change.** Rewrites that keep the behaviour, each one separate:
  - `pose` by an index kept on the agent;
  - lane removal by swap where the order allows (lanes are ordered by position, so it does not);
  - `carObstacle` with its closures hoisted into methods;
  - `setActive` with reused typed arrays.
- **Experiment.** None at run time: each rewrite is checked against the old code by a seeded run of 10 000 fixed steps. The state hash (positions, speeds, lanes) must be identical.
- **Acceptance.**
  - GC time −30 % and frame p99 −10 % in `cibeles` at 17:00 at 4× throttling.
  - A `setActive` spike under 8 ms.
- **Validation.** Identical state hash, which is stronger than the traffic statistics.
- **Risk.**
  - Medium: Warsaw's logic is subtle.
  - The identical-hash rule makes it safe or makes the rewrite fail visibly.
- **Effort.** 2–3 days.
- **Abandon** a rewrite that cannot reach the identical hash in half a day. Abandon all of it if the first two (`pose`, `carObstacle`) give under 10 % less GC.

#### C10. Allocations per frame in drawing and trains

- **Evidence.** [V]
  - Each draw function creates `Matrix4`, `Quaternion`, `Vector3`s, `Color`s and arrays on every call: `life.ts:662-665`, `:683-686`, `:704-705`, `:735-737`, `:759-761`.
  - `trains.render` allocates an array per train car and a `slice` per train (`trains.ts:108-125`, `:26`).
  - `fountains.update` does the same per jet (`web/src/fountains.ts:19-20`).
- **Expected gain.**
  - Tens of small objects per frame, against the 560 kB per frame total.
  - Under 5 % of the garbage [S]. Small on its own.
- **Change.** Module-level scratch objects, as `DECISIONS.md` 2026-11-13 did for the grids.
- **Experiment.** `allocs.mjs` before and after; no switch needed, since it is a pure refactor checked by an identical frame.
- **Acceptance.** Garbage −5 % in `allocs.mjs`; otherwise fold it into C9 as cleanup, not as an optimisation.
- **Validation.** Image pairs, identical.
- **Risk.** Very low. 2 hours.
- **Abandon** as a separate item: it is not worth a measurement of its own. Do it alongside C9 if C9 goes ahead.

#### C11. Structural: shader animation or a web worker

- **Evidence.** Only if Phases 1 and 2 leave the logic or the instance writes as the main-thread bottleneck at 4× throttling, or on a real phone.
- **Options.**
  - **(a) Vertex shader.** Upload each agent's path segment and start time, and let the vertex shader place it. Uploads happen only on edge changes. But IDM car following needs the logic's positions every step, so this would serve people and trains, not cars [S].
  - **(b) Web worker.**
    - The logic runs in a worker and posts positions per step in a transferable array.
    - The main thread keeps only drawing.
    - Picking, following and walk collisions read agent state on the main thread (`life.pick`, `life.pose`, `nav.ts:231-262`, `:595`) and would need a mirrored copy.
- **Expected gain.**
  - (b): the 1.4–4.8 ms of logic per frame leaves the main thread.
  - (a): most of the 2.3–2.6 ms of drawing, for people and trains.
- **Experiment.** A prototype of (b) behind `?simworker=1`, people only first.
- **Acceptance.** Main thread −25 % at 4× throttling in `cibeles` at 17:00, with no frame where a following camera lags behind its agent.
- **Risk.** High:
  - message latency and a frame of lag;
  - two copies of state;
  - dtla-voxel's packed-quad result: smaller data does not mean a faster frame on every GPU.
- **Effort.** 1–2 weeks.
- **Abandon** if the 4×-throttled main thread after Phase 2 is already under 16 ms in every scene.

#### C12. Idle rendering

**Not to be evaluated.** dtla-voxel skips the draw when nothing changes [D] `dtla:web/src/main.ts:316-328`, and never measured the gain. Here agents, fountains, precipitation and the sky move in every frame. A still frame would mean pausing the city, which is a product decision, not an optimisation. The idle case it would serve (a tab left open) is already covered by the browser stopping rAF in hidden tabs.

#### C13. Removing the idle tram code

**Not to be evaluated as an optimisation.**
- With 0 tram routes, `stepTrams` and `drawTrams` loop over empty lists, apart from a few allocations per step (`life.ts:520-587`, `:682-701`) [V].
- The two tram buffers (30 KB) are flagged every frame, which C1 fixes anyway.
- Removing the code is a cleanup to decide on its own merits, not something this plan can measure.

### Order and checkpoints

| Phase | Work | Effort | Checkpoint: measure again, then decide |
| --- | --- | --- | --- |
| 0 | Instrumentation: `?life=0`, `?pop=`, `?perf=sim`, `simcost.mjs`, traffic tools on `launch.mjs`, seeding, p99, CPU throttling | 1–1.5 days | The baseline protocol in full. **Stop here if** `?life=0` saves under 5 % of the frame in every scene, both without throttling and at 4×: the simulation is not worth optimising, apart from C4. |
| 1 | C4, C1, C2 (cheap, invisible) | 1–1.5 days | The same protocol. Keep each candidate that passes its bar. |
| 2 | C3, C5, C7, then C8 (graded or visible; C5 and C7 shown to the user) | 3–4 days | The same protocol, at 4× throttling too. **Continue to Phase 3 only if** the main thread at 4× still exceeds 25 ms in a peak scene. |
| 3 | C9 (with C10), C6 | 3–4 days | The same protocol plus the 10 000-step state hash. |
| 4 | C11, only if Phase 3 leaves the main thread at 4× over 20 ms, or a real phone shows the logic as the bottleneck | 1–2 weeks | — |

**Dependencies.**
- C1 multiplies C5's and C7's savings.
- C4 before C3, since C4 removes two of the twin's three redraws.
- C7 owns C8's rate and C3's map size.
- C6 and C1 share the per-agent drawing loop, so do them by the same hand.

### Summary table

| # | Candidate | From | Expected gain | Effort | Risk | Changes what is seen | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C4 | N8AO transparency renders off | code | 1.8 ms, 3.7–5.0 % where N8AO runs (measured) | an hour | low | maybe at fountains and in rain | **evaluate now** |
| C1 | Upload only what is used | code + three | 0.8–1.1 MB less per frame; under 5 % alone | half a day | low | no | **evaluate now** |
| C2 | Signals at phase changes, constant colours once | code | 0.1–0.3 ms CPU, 88 KB per frame | half a day | low | no | **evaluate now** |
| C3 | Cheaper twin map | code + dtla | up to 1.2 ms, 2–4 % | 1 day | low to medium | agents' shadow resolution | **evaluate now**, after C4 |
| C5 | Less simulation far away | code + dtla | overview 3–4 % GPU, 7 ms CPU | 1 day | medium | yes, in far views | evaluate after Phase 1 |
| C7 | One quality profile for the simulation | dtla | about −40 % sim CPU at 0.5 population | 1 day | low to medium | yes, density | evaluate after Phase 1 |
| C8 | Logic at 20 Hz | code | about −1 to −1.5 ms CPU at peak | half a day plus runs | medium | possibly, motion | evaluate after Phase 1 |
| C9 | Cheaper logic structures | code + dtla | GC and p99, not median | 2–3 days | medium | no (identical hash) | evaluate later |
| C6 | Instance-level culling | code + dtla | part of 2.3–2.5 ms CPU | 1 day | medium | no | evaluate later |
| C10 | Drawing allocations | code + dtla | under 5 % of garbage | 2 hours | very low | no | fold into C9 |
| C11 | Shader animation or worker | code | 1.4–4.8 ms main thread | 1–2 weeks | high | no | only if Phase 3 does not suffice |
| C12 | Idle rendering | dtla | — | — | — | — | **do not evaluate** |
| C13 | Remove tram code | code | negligible | — | — | — | **do not evaluate** (a cleanup) |

### What remains undetermined, and what would settle it

- **A phone's cost.** Neither the GPU nor the CPU share has been measured. It needs a real phone opening the published site with `?perf=sim` (Phase 0). CPU throttling only approximates the CPU, and `profile.py --phone` emulates the screen only.
- **Whether the main thread ever sets the frame time on a real device.** On this laptop the GPU does [S]. It needs the frame interval against the main-thread time at 4× and 6× throttling, and on the phone.
- **What a `bufferSubData` of 1.35 MB costs on shared memory.** It needs C1's A/B with the GPU timer and the main-thread time.
- **The cost of `setActive` when the zone moves.** It needs a `?perf=sim` long-task trace during a pan of 1 km (`longtasks.mjs` on `launch.mjs`).
- **The traffic statistics' run-to-run spread.** It needs three seeded runs of the same build before any logic change. If seeding is not enough to make them repeat, widen the ±5 % bar to the measured spread plus 2 points.
- **Whether `transparencyAware = false` changes anything visible** at the fountains or in rain (C4's validation).
- **The twin map at night.** The sun's light is held at a minimum after dusk, so agents may still cast faint shadows. Whether they show at night decides whether C3(a) may skip it then. It needs an image pair at 23:00.
