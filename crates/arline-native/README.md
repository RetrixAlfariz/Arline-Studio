# Arline Native Core

`arline-native` is the first Rust layer underneath Arline Studio. It is deliberately small: Python still owns narrative semantics, Canon authority, planning, deliberation, retrieval policy, and the web service. Rust owns deterministic byte-heavy primitives that benefit from native execution and stronger memory-safety guarantees.

## v0.1 boundary

- SHA-256 content hashing
- content-addressed object paths
- atomic blob writes
- blob deduplication
- file-to-blob ingestion
- safe lookup/removal

The existing SQLite schema remains authoritative for metadata. The native layer does **not** replace SQLite and does **not** decide Canon.

## Build locally

Rust stable and Python 3.11+ are required.

```powershell
uv tool run maturin develop --release --manifest-path crates/arline-native/Cargo.toml
```

or build a wheel:

```powershell
uv tool run maturin build --release --manifest-path crates/arline-native/Cargo.toml
```

The extension is installed as `_arline_native`. `src.storage.BlobStore` loads it automatically. Without the extension, Arline falls back to a byte-compatible Python implementation.

Backend selection:

```powershell
$env:ARLINE_STORAGE_BACKEND = "auto"   # default; prefer Rust, fall back to Python
$env:ARLINE_STORAGE_BACKEND = "rust"   # strict; fail if native extension is missing
$env:ARLINE_STORAGE_BACKEND = "python" # deterministic fallback/testing
```

## Why this is below Python

```text
Arline Intelligence (Python)
  parser / planner / memory / deliberation / writer
                  |
                  v
Arline Storage Facade (Python)
                  |
          +-------+-------+
          |               |
          v               v
  arline-native Rust   Python fallback
          |               |
          +-------+-------+
                  v
         SQLite metadata + blobs
```

Future native work should be justified by profiling. Likely candidates are batch state resolution, event-journal compaction, branch diffs, cache/index hot paths, and large serialization batches. Prompt logic and authority semantics should stay out of the native layer unless there is a concrete reason to move them.
