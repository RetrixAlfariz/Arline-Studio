# Python Backend Retirement — Gap List

Status: **frozen, not yet deleted** (2026-11-08). `src/` and the legacy
vanilla-JS UI (`src/interface/web/static`) accept parity fixes only, no new
features. Deletion waits until every row below is resolved or explicitly
accepted as dropped.

## What is already at parity

- **HTTP surface.** All 213 Python routes are recognised by the native router
  (`tests/legacy_route_coverage.rs`, fixture `tests/fixtures/legacy-routes.json`).
  A live diff of `src/` decorators against the fixture shows no missing route;
  differences are only the `/api/memory` router prefix and `/api/frontend`,
  which native already serves.
- **Browser smoke.** CI job `native-browser` builds the React UI, embeds it in
  the release binary, starts `arline --headless`, and runs
  `frontend/tests/browser_smoke.mjs`.

## Behavioural gaps (route exists, logic is thinner)

| Python subsystem | Lines | Native counterpart | Gap |
|---|---|---|---|
| `src/discovery/` (physical items, garment, identity, provisional autopatch/materialize, continuity resolution, performance) | ~8.6k | `foundation/memory/discovery.rs` (~0.5k) + SQL in `foundation/memory.rs` | Native stores and lists propositions, and handles decisions and conflicts. It has no physical-item merge/refinement/ambiguity, no provisional autopatch, and no continuity *resolver* (conflicts are listed, not detected the same way). |
| `src/state_extractor/` | ~2.3k | none | No native state extraction from turns. |
| `src/memory/` (query, v121, store) | ~4.7k | `foundation/memory/*` | Native has FTS + semantic index + hybrid. Exact ranking parity is not established (see `crates/arline-runtime/VALIDATION.md`). |
| `src/analytical_system/`, `src/narrative/`, `src/directives/` | ~2.9k | `analysis/*`, `inference/deliberation.rs` | Partially ported; no output-parity tests. |

## Must move before deleting

- `crates/arline-runtime/build.rs` embeds `src/interface/web/static/assets`
  (brand SVGs referenced by the README and served at `/static/assets/*`).
  Move them to `frontend/public/` or `crates/arline-runtime/assets/` first.
- `run-native.ps1`, README "Development" section, and `pyproject.toml` /
  `uv.lock` references.
- CI lanes: `floating`, `locked`, Python wheel smoke, legacy `browser`.

## Decision needed per row

For each behavioural gap: **port**, **drop** (feature retired with Python), or
**defer** (keep Python until ported). Record the decision here; delete `src/`
only when no row says *defer*.
