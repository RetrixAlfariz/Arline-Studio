# R1 — Optional native Bekko embedding runtime

Opheline · 6 November 2026 · Local branch `codex/retrieval-r1-bekko`

R1 adds a standalone CPU embedding capability, not a new retrieval engine. The default build and existing installations do not load Bekko. Native retrieval integration remains deferred to R2/R3; FTS5, structured state, packing, narrative eligibility and the LM Studio writer retain their ownership.

## Implementation and checkpoint

Before dependency changes, `.codex-audit/retrieval-r1-20261106/pre-r1-checkpoint.zip` captured HEAD, a binary working-tree patch, all changed/untracked R0 files, configuration and both Cargo files, with a SHA-256 manifest. The archive was checked as readable. No reset, stash, commit, push, merge or remote PR was performed.

| Source | Responsibility |
|---|---|
| `src/foundation/memory/embedding.rs` | Typed `EmbeddingProvider`, `BekkoConfig`, identity/result/error contracts, async admission and blocking inference boundary; no database or writer access. |
| `embedding/artifacts.rs` | Bounded artifact reads, actual-content SHA-256, pinned default-model integrity, metadata checks, consistent load snapshots and vector-identity construction. |
| `embedding/lifecycle.rs` | Per-AppState lazy session, serialized first load/inference, one idle worker, TTL updates, shutdown, replacement and error cleanup. |
| `embedding/native.rs` | Explicit native library loading, ONNX Runtime version/binding checks, FastEmbed tokenizer/session setup, masked mean pooling and normalized vector validation. |
| `memory/settings.rs`, `config.rs` | Additive backend configuration and validation; legacy LM Studio compatibility and conservative enable-gate resolution. |
| `lib.rs` | Each `AppState` owns an `Arc<EmbeddingService>`. Creating it performs no artifact or native-library I/O. |
| `memory.rs` | Native backend remains diagnostic-only; query requests retain lexical/structured results rather than invoking the legacy passage-embedding loop. |
| `examples/bekko_diagnostic.rs` | Explicit local qualification, parity checks, timings, memory, eviction and concurrent reload; never opens an application database. |

Verithen was inspected locally at commit `771e7ad39ad2da4c9001e00c6068eca892ffaa31`, including `semantic_native.rs`, its tests, `semantic.rs`, `MILESTONE-07-REPORT.md` and `bekko-artifacts.json`. Those reference files had no working-tree modifications when inspected. The cache pattern and FastEmbed setup are adapted from its MIT OR Apache-2.0 implementation. Arline does not copy its Git, MCP or persistence architecture, nor its process-global mutable model cache.

## Configuration

Existing files retain the LM Studio embedding backend. `native-bekko` is an **opt-in Cargo feature**, absent from default features. The repository configuration only gains an explicit `backend = "lmstudio"`; no existing model selection or enable flag is switched.

Example native configuration for a deliberately provisioned installation:

```toml
[memory]
# If this legacy gate exists, it must also be true for explicit native calls.
# R1 production retrieval still falls back to FTS5 + structured state.
dense_enabled = true

[memory.embedding]
enabled = true
backend = "native_bekko_onnx"
model = "hotchpotch/bekko-embedding-v1-a8m"
dimension = 384
model_dir = "models/bekko-embedding-v1-a8m"
max_tokens = 512
threads = 2
keep_warm_seconds = 300
query_prefix = ""
passage_prefix = ""
# Optional; if omitted, use executable-adjacent onnxruntime.dll/libonnxruntime.so.
# Explicit values must be absolute, for example:
# runtime_library = 'C:\ArlineDependencies\onnxruntime.dll'
```

Use `enabled = false` for provisioning without native inference. Enabling this configuration does **not** activate production native retrieval in R1. An absent backend means `lmstudio`, including legacy `[memory_embedding]` configurations. Nested fields take precedence over their legacy counterparts. When both `memory.dense_enabled` and embedding `enabled` exist, **either explicit false disables embeddings**; if only one exists, it controls activation. With neither, embeddings are disabled. This prevents conflicting saved flags from automatically activating retrieval. Memory status reports the same effective flag for both paths.

Relative model paths resolve against `RuntimeConfig.root`, the application data root in normal native launches (`%LOCALAPPDATA%/Arline Studio` on Windows). Explicit `--config` workflows must supply the intended `--root`, or use an absolute `model_dir`; the provider never resolves paths directly against its current working directory. Runtime-library paths are always absolute or executable-adjacent. `ORT_DYLIB_PATH`, PATH and the current directory are not application-level library-selection inputs.

Native configuration rejects unknown backend names, wrong model/dimensions, nonempty prefixes, invalid field types, max tokens outside 2–512, threads outside 1–32, keep-warm outside 0–86400 seconds, and relative explicit library paths. Larger input lengths are deliberately unqualified. Texts longer than the token cap are truncated by the pinned tokenizer; input byte limits are separately bounded to prevent unbounded allocations.

## Provisioning and artifact identity

Provision these six files **locally**, without renaming an alternative ONNX graph:

```text
models/bekko-embedding-v1-a8m/
  onnx/model.onnx
  tokenizer.json
  config.json
  tokenizer_config.json
  special_tokens_map.json
  1_Pooling/config.json
```

The checked-in [artifact manifest](../crates/arline-runtime/tests/fixtures/bekko-artifacts.json) records sizes and SHA-256 values for the official default model at revision `c721113d59a1d91b447450324f51c4b3332c924a`. The default ONNX graph is 130,099,079 bytes, SHA-256 `96d8cc6199e96357b21b2fb12f6d7ffd2d4abc7b182fe94b5468fbd6dc819af7`. No `not_recommended` graph is accepted under its filename. Different contents require deliberate manifest/revision qualification, not silent cache reuse.

Obtain the pinned files through your chosen trusted provisioning process from the [model revision](https://huggingface.co/hotchpotch/bekko-embedding-v1-a8m/tree/c721113d59a1d91b447450324f51c4b3332c924a), then compare all six hashes against the manifest. Arline does not download files, weights or native libraries. This implementation's Windows checks reused existing local Verithen artifacts read-only.

Every explicit native operation hashes file contents, including same-size/same-timestamp replacements. The fingerprint includes all artifact digests, exact model, dimensions, max tokens, empty prefixes, pooling and the pinned preprocessing/runtime implementation contract. Thread count affects session reuse, not stored vector identity. Loaded bytes are rechecked against the captured identity before session construction, avoiding storing a newly loaded model under a stale identity.

Pinned hashes establish integrity relative to the shipped manifest; they do not authenticate artifact provenance. `ModelIdentity` distinguishes `integrity_verified=true` from `provenance_authenticated=false`. Local model paths and runtime libraries are trusted provisioning inputs, not untrusted uploads.

## Lifecycle and failure contract

- One semaphore admits one native blocking operation per AppState. It prevents a pool of blocked inference tasks, while the cache mutex serializes session creation and inference. Separate AppStates never share mutable model/session configuration.
- The session is loaded on first native call, reused while its key is valid, and evicted after configured idle time measured from inference completion. Zero keep-warm drops it after every batch. Replacement/thread changes reload; max-token changes also change vector identity.
- One condition-variable worker per cache exits when empty. Shutdown signals do not block async workers; a bounded worker wait also handles a shutdown-notification race. Already-running blocking work finishes or fails before its session is discarded.
- Configuration is a per-call snapshot. Changes take effect on the next native call; an idle old session can remain until its prior TTL expires. Disabling a native call clears any cached session without hashing/loading files. There is no automatic preload on settings save.
- Inference errors and caught native-wrapper panics discard the session. Diagnostics retain a typed error and `fts5+structured` fallback. A poisoned process-wide runtime binding fails with a restart-required error rather than being reused silently.
- Inputs are 1–64 texts, at most 64 KiB each and 1 MiB total; inference sub-batches are 16. An empty batch is an explicit input error; an empty string is a supported tokenizer input.
- Diagnostics use a nonblocking cache snapshot. `busy=true` means loaded-state fields were unavailable, not that the model was evicted. Before a native attempt, availability is unprobed; `compiled` does not imply artifacts/runtime are installed. Lexical status never hashes artifacts.

## Native dependencies, loading and redistribution

Pinned optional dependencies: FastEmbed **7.5.0**, `ort`/`ort-sys` **2.0.0-rc.15**, libloading **0.9.0**, with Tokenizers **0.23.2** resolved in Cargo.lock. FastEmbed defaults and hub/download features are disabled. ORT is dynamically loaded with API 24 support; only CPU execution is configured. Fifty packages were added to the lockfile, with no pre-existing package versions removed/upgraded.

The native library must report **ONNX Runtime 1.27.0**. Missing files, missing dependencies, invalid exports and wrong versions return errors from native calls and do not prevent ordinary application startup. Windows preloading restricts DLL dependency search to the DLL directory and trusted default application/system directories; the wrapper subsequently binds the same absolute file. Linux loads an absolute shared library; package its dependencies with appropriate loader metadata and trusted system libraries rather than a working-directory search path.

ORT permits a process-wide library/environment binding. Arline retains that small environment across model eviction and checks canonical path plus actual library-content SHA-256 on every native operation, including reused sessions. Replacing the runtime path/contents after binding requires restarting Arline. Model eviction does not unload or replace the runtime itself.

The model card declares [MIT](https://huggingface.co/hotchpotch/bekko-embedding-v1-a8m); FastEmbed and Tokenizers are Apache-2.0, ort is MIT OR Apache-2.0, libloading is ISC, and [ONNX Runtime is MIT](https://github.com/microsoft/onnxruntime). A future binary distribution must retain the applicable license/copyright texts, Apache notices where provided, ONNX Runtime `LICENSE` and `ThirdPartyNotices.txt`, and notices for its actual transitive/native dependencies. Redistributing model files additionally requires the model's notices. No weights, DLLs, shared libraries or new installer package are bundled by R1; a source dependency declaration alone is not a completed redistribution audit.

## Tests and qualification

The frozen five-text reference fixture comes from Verithen's Python ONNX CPU reference under the same six artifacts and a 512-token cap. It covers English, Indonesian, Japanese, software terminology and short input. Arline also tests mixed Indonesian/English, empty text and over-limit input. Native parity requires cosine **at least 0.99999** and maximum component difference **at most 1e-4**; these are numerical parity tolerances, not retrieval thresholds. Unit-norm tolerance is `1e-5`. These tolerances are intended for future matched-artifact platform checks; Linux execution has not established them there.

The real test additionally verifies session reuse, truncation by comparing inputs with different suffixes beyond the cap, and changed max-token identity/reload. Model-free tests cover serialized concurrent first load, workspace isolation, reuse/eviction/reload, zero retention, replacement, load/inference errors, panic cleanup, missing/oversized/replaced files, malformed pooling metadata, missing/incompatible runtime files, runtime-binding replacement policy, invalid settings, disabled/feature-missing behavior and lexical fallback. Existing LM Studio dense/reranker tests remain.

Reproducible commands (repository root; paths below are deliberately operator-supplied):

```powershell
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --all-targets
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --all-targets -- -D warnings

$env:ARLINE_BEKKO_MODEL_DIR = 'C:\Provisioned\bekko-embedding-v1-a8m'
$env:ARLINE_ONNX_RUNTIME = 'C:\Provisioned\onnxruntime.dll'
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --lib qualified_bekko_vectors -- --ignored --nocapture

cargo run --locked --offline --release --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --example bekko_diagnostic -- --model-dir $env:ARLINE_BEKKO_MODEL_DIR --runtime-library $env:ARLINE_ONNX_RUNTIME --out qualification.json --repeats 20 --eviction-seconds 2
```

The live model test is ignored during ordinary CI because it requires explicitly provisioned local files. Ubuntu CI now includes native-feature compilation/lifecycle tests, but no branch push or Linux CI execution occurred here. Tests use temporary storage and mock writers; the qualification example opens no application database.

| Check | Result |
|---|---|
| Default-feature all-targets suite | **194 passed**, zero failures |
| Native-feature all-targets suite | **195 passed**, zero failures; one provisioned-model test ignored by default |
| Explicit native tests including provisioned-model parity | **9 passed**, zero failures |
| Default-feature focused provider tests after final validation edits | **7 passed**, zero failures; the later busy-snapshot regression also passed and is included in the final full suites |
| Strict all-targets Clippy, default and native features | Both passed |
| Existing Phase A–C regression suite | All **8 passed** inside both full suites |
| Diff hygiene and preservation | `git diff --check` passed; seven unchanged R0/Phase A–C source/fixture/report files matched the checkpoint byte-for-byte |

Initial implementation checks exposed an outdated exact settings-shape expectation and a 40-ms reuse test vulnerable to scheduling delays. The settings test now checks all frozen fields plus explicit additive fields; the lifecycle test uses a long reuse TTL before shortening it for eviction. No failures remain in the executed checks. Both full suites and strict Clippy passed after the final source and diagnostic-test edits.

The first full-duration diagnostic exposed a harness error: a nonblocking `busy=true` snapshot was interpreted as zero loads/eviction while model destruction held the cache lock. The harness now waits for a readable, fully idle snapshot and retains its load count before checking concurrent reload. A deterministic busy-cache regression test covers this contract; that focused test passed. The initial failed qualification file is retained separately rather than overwritten.

Local raw evidence is retained under `.codex-audit/retrieval-r1-20261106/`, including the checkpoint, preservation check, qualification JSON and copied test/Clippy logs. The Windows release probe uses a Ryzen 9 7950X, two ORT intra-op threads, 512 tokens and ONNX Runtime CPU 1.27.0. The loaded DLL SHA-256 is `c23aede8d9b9bd203a9a736dda5fd0392b3240d98a93edd8178d83cdfcbebd13`.

The final release-mode qualification passed and is retained as `qualification-300s-final.json`. Twenty warm single-text samples followed one cold five-text batch; batch throughput used one batch of 16 short reference texts. Timings are local observations, not corpus-scale retrieval benchmarks. `total_ms` includes async admission/blocking dispatch, artifact/runtime validation and inference; stage timings separate validation, session load and inference.

| Measurement | Observed |
|---|---:|
| Cold full provider call, five texts | 1190.12 ms |
| Cold session construction | 1046.50 ms |
| Warm single-text inference p50 / p95 | **2.07 / 2.71 ms** |
| Warm full provider call p50 / p95 | **93.61 / 94.67 ms** |
| Warm artifact + runtime content validation p50 | 91.52 ms |
| Batch of 16, full call / inference only | 125.93 / 33.29 ms |
| Batch throughput, full call / inference only | 127.05 / 480.66 texts/s |
| Missing-artifact failure detection p50 / p95 | 0.041 / 0.088 ms |
| Actual 300-second idle eviction wait | **300.055 s**, worker stopped |
| Concurrent reload after eviction | One new session; second request reused it |
| Changed intra-op thread setting | Session reloaded; vector identity unchanged |
| Minimum reference cosine, five texts | 0.9999999999999962 |
| Maximum reference component error | **2.2352e-8** |

Windows process memory counters recorded 236,937,216 resident bytes after initial inference (~225.96 MiB), falling to 39,993,344 after eviction (~38.14 MiB). Peak resident memory was 685,969,408 bytes during the first load (~654.19 MiB), and 693,338,112 bytes across reload/thread-change checks (~661.22 MiB). The retained ONNX environment and shared tokenizer/runtime allocations remain after session eviction; the process does not return to its ~5.91 MiB startup footprint.

Two material limits remain: hashing all artifact/runtime contents dominates warm call latency, and initialization has a substantial transient RAM peak. R2 should amortize validation across bounded batches rather than embedding individual missing passages during generation. Neither CPU-only execution nor idle eviction makes the loader's peak memory negligible. These measurements do not establish memory behavior for long batches, narrative retrieval quality, production tail latency or throughput under contention.

The missing-provider figure measures native error detection only; ordinary R1 retrieval never invokes the native provider and retains its lexical/structured path. The initial two-second probe is also retained, but the final report above uses the successful full-duration run.

No Linux execution, Linux reference parity, fresh desktop/UI test or installer redistribution qualification has been performed. Linux remains **unqualified**, even though the code and CI steps support a future run there. Windows CPU embedding qualification passed; this does not qualify a native retrieval rollout.

## R2 handoff and rollback

R2 should consume `EmbeddingProvider::embed_batch` and store each returned `ModelIdentity.fingerprint` with its vectors, source revision/checksum and dimensions. Inference belongs outside write transactions. Before committing a batch, independently recheck source revisions and eligibility so edits/deletions during inference cannot publish stale rows. Preserve the legacy JSON embedding table, add versioned little-endian f32 BLOBs, resumable jobs and explicit pending/failed/current states. Batch indexing must not recreate the old per-query missing-passage loop.

Recommended additive schema boundary, **not implemented by R1**:

| Proposed table | Key and essential fields |
|---|---|
| `semantic_model_generations` | Model fingerprint primary key; exact model ID, dimensions, serialized identity contract, created time and schema/encoding version. |
| `semantic_vectors` | Primary key `(chunk_id, model_fingerprint)`; source revision, content checksum, dimensions, little-endian f32 BLOB and indexed time. Check `length(vector_blob) = 4 * dimensions`. Admit only rows whose revision/checksum still match an active source chunk. |
| `semantic_index_jobs` | Job ID, captured model fingerprint, resumable cursor, status, counts, bounded error and timestamps. Recover interrupted jobs without marking partially indexed sources current. |

Decide retention/foreign-key policy during R2 against actual historical schemas. Vector presence must never grant eligibility or authority; scope remains a separately enforced retrieval boundary.

R3 must still repair the sibling-branch candidate cap, relevance fusion and eligibility exceptions identified in R0. R4 owns accurate writer-tokenizer budgeting. No retrieval cutoff, similarity threshold, hybrid-quality improvement or fix for the R0 candidate-cap failure is claimed by R1.

Rollback is to omit `native-bekko` and leave/revert the native backend selection in the copied application configuration; default lexical/structured retrieval remains usable. Disabling either enable gate prevents new native calls and clears a cached session when such a call is attempted; otherwise it expires under its existing TTL. Runtime-library replacement requires process restart. No R1 database migration needs reversing. Restore only specific files from the pre-R1 checkpoint if reviewing source rollback, preserving the accepted R0 and Phase A–C changes.
