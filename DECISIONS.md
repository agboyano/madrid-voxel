# Decisions

Log of non-trivial decisions: date, decision, reason and rejected alternatives.

## 2026-11-10: Default branch `main`

- **Decision:** the repository's initial branch is `main`.
- **Reason:** GitHub's default, and what the Pages workflow from dtla-voxel will expect.
- **Rejected:** `master` (git's built-in default here).

## 2026-11-10: Install the viewer with pnpm from its lockfile

- **Decision:** install `web/` dependencies with `npx -y pnpm@12.11.2 install --frozen-lockfile` and run the dev server with `npx -y pnpm@12.11.2 exec vite`.
- **Reason:** the Warsaw viewer declares `packageManager: pnpm@12.11.2` and ships `pnpm-lock.yaml`; this reproduces the upstream dependency versions exactly, with no global install.
- **Rejected:** `npm install` as written in `PLAN.md`, which ignores the pnpm lockfile, resolves versions afresh and adds a `package-lock.json`.

## 2026-11-10: Screenshot harness on the system Chromium and the real GPU

- **Decision:** `scripts/screenshot.py` uses Python Playwright (dev dependency) with the system Chromium, ANGLE on the GPU (`--use-angle=gl`), and sets the viewer's "Render size" slider to 1 before capturing.
- **Reason:** headless Chromium otherwise renders with SwiftShader, which cannot stream the city in reasonable time; and the viewer's adaptive level draws most of the map as grey clay on slow GPUs, which makes screenshots depend on the machine. Setting the slider uses the existing UI, so the viewer is unchanged.
- **Rejected:** downloading Playwright's bundled Chromium (extra download, same result); reusing `web/tools/shot.mjs` (Node, macOS Metal flags, writes outside `docs/img/`); changing the viewer to accept a level parameter (Phase 0 must not change the viewer).

## 2026-11-10: Keep Warsaw's `tiles.py`

- **Decision:** keep Warsaw's `scripts/tiles.py` and tile reader as they are.
- **Reason:** dtla-voxel's tiles are byte-compatible but add levels 2 and 4 and an optional detail block that Warsaw's `city.ts` does not use; `CLAUDE.md` rule 7 forbids format changes unless the plan says so.
- **Rejected:** adopting dtla's `tiles.py` (needs viewer changes for no Madrid-specific gain).
