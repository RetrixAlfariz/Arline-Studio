# Native runtime validation — 2026-10-23

This document records the Rust/Tauri backend migration checks. Validation stayed local; no commits, pushes, or in-place migration of the original workspace were performed.

## Completed automated suite

The desktop-featured crate suite completed with **136 tests passed**:

```powershell
cargo test --locked --offline --features desktop --manifest-path crates/arline-runtime/Cargo.toml
```

The tests cover the following boundaries.

| Area | Covered behavior |
| --- | --- |
| Native host and contracts | Rust runtime, Tauri desktop feature, loopback API, startup/config contracts, model discovery/loading settings |
| Workspace | bootstrap, project/world/branch selection, documents and revisions, folder ownership/cycles/depth, sessions, turns, forks |
| Generation | writer modes, bounded context, canon/reference scope, streaming HTTP, split UTF-8, cancellation, failed partial output, Story Lab shape |
| Analysis and memory | quality validation, structured analysis, FTS/evidence projection, memory refresh/backfill/query, spatial and temporal scope, discovery review/canon decisions |
| Canon/workspace workflows | proposals, explicit apply, snapshots, branches, merges, retcons, conflict/history reporting, profile and blueprint privacy |
| IO and import | manuscript and project export/import, reset recovery, feedback artifacts, copy-only legacy import, SQLite WAL preservation, managed-media rehoming and containment |
| Route inventory | 213 legacy route entries are recognized and exercised for server/unimplemented errors; this is route recognition, not semantic proof for every route |

## Release checks

The completed final clippy check is:

- `cargo clippy --locked --offline --features desktop --all-targets -- -D warnings` — **passed**.

The frontend and optimized desktop build passed through `run-native.ps1 -BuildOnly`. Existing Vite chunk-size and runtime brand-asset warnings remain. The release opened a responsive `Arline Studio` window and served the embedded React interface. Its health endpoint reported `runtime: rust` and `python_required: false`; its process tree contained Arline and WebView2 with zero Python children.

The configured `qwen3.5-4b-uncensored-hauhaucs-aggressive` model was loaded locally with context length 32768 and flash attention enabled. Three release prompts exercised writing, same-session continuation, and Story Lab, with actual model deliberation and provider token statistics. The initial scene retained the sealed box and exact requested ending; continuation retained the notes, seal, box, and visual viewpoint. Story Lab returned exactly three numbered one-sentence alternatives. Word limits remained imperfect: 127 words for a requested 90–120, and 116 for 70–100. These are model observations, not a broad writing-quality benchmark.

Saving and downloading the real writing run produced a readable ZIP with 17 artifacts, including prose, analysis, writer input, provider response, validation, and token statistics. Raw release evidence is under `.codex-audit/full-parity/live/release-*`; previous raw trials were retained.

## Evidence and limits

All 286 pre-existing files outside the native crate matched the pre-turn preservation manifest, including the existing uncommitted changes. The original database remained unchanged during release validation; its last-write time still predates this task. Runtime tests used copied storage.

The repository retains local audit evidence under `.codex-audit/`, including the full-parity and live model/runtime records. Those records support the tested native flows and the migration boundary; they do not establish universal historical database compatibility, exact NLP output parity, broad model-quality improvement, or faster inference.
