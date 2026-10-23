# Arline native runtime

`arline-runtime` is the Python-free Rust backend and Tauri desktop host for Arline Studio's React chat and writing interface. The executable embeds the built interface, owns the local SQLite store, serves the loopback API, and talks to the local LM Studio OpenAI-compatible API. LM Studio remains the neural-model provider; this migration moves application/runtime behavior into Rust and does not claim model-quality or inference-speed parity.

From the repository root in PowerShell 7:

```powershell
.\run-native.ps1
# Subsequent launches, using the compiled release executable:
.\run-native.ps1 -SkipBuild
```

Building requires Node/npm, Rust with MSVC, and the Windows C++ tools/SDK. Running the desktop executable requires WebView2 and LM Studio. Model discovery and loading are native Rust flows: the loader uses LM Studio's SDK WebSocket `loadModel` channel first, passing the exact model, GPU offload ratio, context length, and flash-attention keys. The `lms` CLI is a compatibility fallback for SDK failure or unavailable endpoints; its fallback path cannot apply flash attention. Credentials stay out of CLI arguments. No separate Python server is required.

The launcher bootstraps a copy of the configured workspace, configuration, writer contract, SQLite database, and managed media into `%LOCALAPPDATA%\Arline Studio`. The copy includes uncheckpointed WAL changes, rewrites imported media paths into the copied managed-media directory, rejects paths outside that directory, and preserves the source workspace and existing destinations. Later launches use the app-data copy.

Use a separate local data directory for a trial:

```powershell
.\run-native.ps1 -SkipBuild -DataDirectory E:\Arline-native-trial
.\run-native.ps1 -SkipBuild -Headless -Port 17861
```

The default loopback port is `7861`; an explicit port of `0` selects a free port. The executable also accepts `--config`, `--root`, `--data-dir`, `--port`, `--headless`, `--bootstrap-from`, and `--import-workspace`. The default executable path is `crates/arline-runtime/target/release/arline.exe`.

## Migrated runtime surface

The Rust runtime now owns the tested application flows for:

- workspace bootstrap and project/world/branch selection;
- documents, revisions, folder ownership/cycle/depth checks, sessions, turns, modes, feedback, and forks;
- single-response generation, Story Lab discussion, streaming SSE, split UTF-8, cancellation, and failed-partial persistence;
- chained beat generation with previous-surface context, per-beat budget accounting, and completed-prefix persistence when a middle beat fails;
- bounded generation context, writer contracts, scoped canon/reference context, private profile filtering, and media upload/storage containment;
- analysis and quality validation, memory indexing/query/backfill, discovery capture/review/canon decisions, spatial/temporal projections, and workspace/canon workflows including snapshots, branches, merges, proposals, retcons, and conflict reporting;
- native import/export and reset/recovery IO paths, including copy-only legacy bootstrap with SQLite WAL and managed-media handling.

The legacy route fixture contains 213 entries. The route-coverage test establishes that these routes are recognized without server/unimplemented errors; that inventory is a recognition check, not proof that all 213 routes have identical semantics or output to the historical backend.

## Validation

Run the crate suite from the repository root:

```powershell
cargo test --locked --offline --features desktop --manifest-path crates/arline-runtime/Cargo.toml
```

The completed migration test matrix is recorded in [`VALIDATION.md`](VALIDATION.md). Keep the original workspace as the source of record while reviewing the native app. The migration does not establish universal compatibility with every historical database version, exact NLP output parity, model-quality parity, or model-speed parity.
