# Native narrative retrieval: R0 baseline

Opheline · 5 November 2026 · Windows x86_64 · Rust 1.93.0

Scope: R0 only, based on `ef5bf206eae3e73ce289544e38df7c979adda1f0` plus the existing uncommitted Phase A–C changes. Work is isolated on `codex/retrieval-r0-baseline`. No Bekko/ONNX dependency, model download, embedding migration, default-setting change, push, merge, or remote PR was performed. This is an audit of native retrieval and its generation boundary, not a complete application or Python-backend audit.

## 1. Architecture and ownership

| Boundary | Owning source and behavior |
|---|---|
| Initialization | `crates/arline-runtime/src/lib.rs`: `AppState::open` initializes the store, memory, generation tables, and interrupted-turn recovery. |
| HTTP entrypoints | `generation.rs::handle`: `/api/analyze`, `/api/generate`, `/api/generate/stream`. Normal generation also owns multi-beat orchestration. |
| Shared preparation | `generation.rs::prepare_generation`: analysis/retrieval → planning decision and optional planner → output budget → bounded writer context. Single, streaming and beat requests share this boundary. |
| Retrieval handoff | `analysis.rs::analyze_async_profiled`: deterministic workspace analysis, retrieval, selected evidence, compact provenance block. Raw request prompt is currently the retrieval query. |
| Query API and lanes | `foundation/memory.rs::handle`, `retrieve_async`, `retrieve`, `structured_candidates`: FTS5 plus structured/temporal/spatial/thread evidence; optional LM Studio embeddings/reranking. |
| Eligibility | `memory.rs::scope_allowed`, `scope_allowed_inner`, `guarded`, `temporal_allowed`: source/lifecycle checks, project/world, branch/session lineage, time, POV, scratch/trust controls, and explicit-source exceptions. |
| Context selection | `memory.rs::pack_retrieval`: chunk deduplication, per-source cap, final result count, estimated token budget, selected/excluded traces. |
| Indexing | `memory/indexing.rs::replace_chunks` plus `chunking.rs`: content revision hashes, stable chunk identifiers, transactional source replacement, stale old revisions and source links. `refresh_document`, `refresh_turn`, backfill and projection refresh provide indexing entrypoints. |
| Writer | `generation.rs::chat_payload`, `model_stream`: existing LM Studio writer. Canon decisions remain in existing review/workspace workflows. |
| Settings | `memory/settings.rs`, `config/arline.toml`: nested and legacy settings. Repository defaults enable automatic FTS/structured retrieval, disable dense/reranker, select at most 12 chunks, at most two per source, and pack approximately 4096 tokens. Installed settings can differ. |

Current generation path:

```text
request → hydrate session scope → prepare_generation
  → analyze_async_profiled → workspace analysis
  → retrieve_async → FTS + structured → eligibility → pack
                    [optional LM Studio dense/rerank → repack]
  → selected-only compact memory → optional planner
  → trim memory, then oldest history; retain mandatory context
  → existing LM Studio writer → persist/review/index
```

The Python-era milestone documents describe a richer query compiler and fusion design. Those descriptions must not be treated as proof of the current native implementation.

## 2. Confirmed defects and regression risks

| Finding | Evidence / implication | Boundary |
|---|---|---|
| Candidate-to-writer leakage in the committed baseline | The existing Phase A change replaces `result.results` with `result.selected` and removes a hard-coded limit of 20. Candidate results include material excluded by packing. Retain this fix before any new semantic provider. | R0, already fixed locally |
| Pre-scope candidate ceiling | FTS SQL orders by importance/recency and limits to 500 before branch/session/POV eligibility filtering; dense search also starts from a global recent 500-row pool. Eligible evidence can be omitted before selection. The synthetic scope-pressure benchmark reproduces the FTS case without exposing sibling evidence. | R3 ranking/candidate work |
| Importance-dominated ranking | FTS does not use BM25 ordering here; dense cosine candidates are merged and sorted by importance. `rrf_k` is a setting, not proof of implemented weighted RRF fusion. | R3 |
| Request-time document embedding | Dense query handling fetches missing passage embeddings individually and caches JSON vectors by chunk ID/model. Cold queries can incur many provider calls. No native provider or versioned binary semantic index exists. | R1/R2 |
| Incomplete semantic cache identity | Content revisions participate in chunk IDs, so ordinary edited text does not simply reuse the old chunk ID. However, embedding cache identity does not fingerprint model artifacts/tokenization/pooling. Replacing a model under the same key is unsafe; re-chunking also needs an explicit version/config identity. | R2 |
| Approximate input accounting | Retrieval estimates characters/4; final generation estimates characters/3. Beat overhead is reserved heuristically and attached image costs are not counted. The planner runs before final writer-budget validation. Passing budget tests does not prove actual tokenizer/window correctness. | R4 |
| Temporal comparisons need qualification | `temporal_allowed` falls back to string ordering for nonnumeric world-time values. Arbitrary fictional labels are therefore not conservatively incomparable. Existing numeric/story-order tests do not establish correctness for opaque labels. | Eligibility prerequisite before semantic rollout |
| Explicit-source authority exception | `scope_allowed_inner` immediately permits explicitly listed sources after lifecycle checks, bypassing its ordinary lineage/time/POV/trust logic. This is an existing API behavior, not semantic authorization. Define and test allowed exceptions before attaching a broader candidate source. | Eligibility prerequisite; preserve compatibility deliberately |
| Prompt-injection filtering is limited | `guarded` recognizes a short phrase list; compact manuscript text is still model input. This is not comprehensive protection, particularly with explicit exceptions. | R3/R4/R5 fixtures |
| Recovery/idempotency limits | Startup recovery assumes one active runtime per database. Key claims can precede a turn being created, so preparation failure can leave a duplicate response with no turn/status; clients need a new key. Checkpoint throttling is delta-driven, not a periodic flush, so 250 ms is not a hard wall-clock crash-loss bound during stalls or write failures. | Preserve Phase B/C; qualify before rollout |

The latter scope, temporal, cache and lifecycle observations are source-level findings; this R0 run does not claim exhaustive exploit or fault-injection coverage for them.

## 3. Phase A–C implementation to retain

| Phase | Actual implementation and coverage |
|---|---|
| A: retrieval/context integrity | Selected-only evidence, compact source/revision/authority/trust provenance, configured `final_k`, retrieval diagnostics outside evidence serialization, memory-first trimming, oldest-history trimming, HTTP 413 if mandatory writer context cannot fit. |
| B: durable generation | Streaming completion waits for persistence; failed commit emits error, cancellation saves in-memory text, checkpoints are throttled, startup marks running turns interrupted. Derived memory refresh failure is recorded without rejecting otherwise saved output. |
| C: request identity | Additive `generation_requests` table, atomic primary-key claim, 409 for duplicate identity, 422 for scope/payload mismatch, keyless compatibility. Existing tests exercise concurrency, retry and deliberate regeneration. |

Preserved files: `.github/workflows/ci.yml`, runtime `src/analysis.rs`, `src/generation.rs`, `src/lib.rs`, `tests/legacy_route_coverage.rs`, and `tests/orchestration_o01.rs`. The CI addition runs default-feature runtime tests and strict Clippy on Ubuntu; it does not establish that Linux or desktop checks have run for this branch.

## 4. R0 changes, compatibility and backups

R0 adds a six-case handoff regression covering saved `final_k=3` and zero evidence budget on normal, streamed and two-beat generation. All writer calls are inspected for unique candidate markers. The original seven Phase A–C tests remain.

`examples/retrieval_baseline.rs` and `tests/fixtures/retrieval_r0.json` add a repeatable, model-free baseline through the real in-process query router. The frozen development fixture contains 523 synthetic chunks and three probes: exact name, mixed Indonesian/English paraphrase, and sibling-branch crowding. It intentionally bypasses extraction/indexing to isolate retrieval. It records selected IDs, Recall@5, MRR@10, nDCG@10, forbidden sibling selection, latency samples/p50/p95, and a fixture SHA-256. This is not the held-out R5 evaluation set.

No production source changes were needed beyond retaining the existing correctness patch. R0 adds no schema or API migration. The Phase C table creation is pre-existing, additive and idempotent; legacy embedding tables are retained.

Local, ignored evidence is under `.codex-audit/retrieval-r0-20261105/`:

- Repository database: SQLite online backup, **1,892,352 bytes**, 106 tables, integrity check `ok`.
- Installed database: SQLite online backup, **1,929,216 bytes**, 116 tables, integrity check `ok`.
- Both runtime TOML files were copied locally, with hashes/manifests. Secrets/configuration contents are not included in this report.
- The installed runtime overrides the configured database path to `%LOCALAPPDATA%/Arline Studio/arline_history.db` in `main.rs`; its flat database was backed up, rather than assuming the TOML-relative path was active.

Backup sources were opened through SQLite read-only connections; committed WAL content is included. No application initialization, migration or recovery ran against either source database. Backups are local review/recovery artifacts and must not be committed.

## 5. Validation and performance observations

Commands run from the repository root:

```powershell
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --test orchestration_o01 --example retrieval_baseline
cargo run --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example retrieval_baseline -- --out .codex-audit/retrieval-r0-20261105/baseline.json --repeats 20
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings
```

- Before R0 additions: **184 tests passed, zero failed**, default features, including 77 unit tests and three inference-benchmark tests. Original Phase A–C suite: seven passed.
- After additions: **eight Phase A–C tests passed**, including all six new endpoint/budget combinations; the baseline example compiles.
- Strict default-feature all-targets Clippy passed. `git diff --check` passed. Hash comparison confirmed the five pre-existing tracked production/CI/test-fixture files were unchanged by R0; the existing untracked orchestration test file received the additional regression test.
- An initial added-test fixture incorrectly indexed an absent TOML table and failed. It was corrected to use `RuntimeConfig::set`; it was a test setup error, not a pre-existing runtime failure.
- Retrieval benchmark: 20 timed repetitions per probe after one untimed warm-up. Metrics were stable across repetitions. Results:

| Probe | Recall@5 | MRR@10 | nDCG@10 | p50 ms | p95 ms | Forbidden sibling chunks selected |
|---|---:|---:|---:|---:|---:|---:|
| Exact name | 1 | 1 | 1 | 25.76 | 28.92 | 0 |
| Mixed-language paraphrase | 0 | 0 | 0 | 24.84 | 26.61 | 0 |
| Scope before candidate cap | 0 | 0 | 0 | 2925.13 | 3364.97 | 0 |

The scope-pressure probe has one eligible match and 520 higher-importance matches confined to an ineligible sibling. FTS takes 500 before the branch gate, so the valid match is never considered. Repeated per-candidate database scope/lifecycle lookups are a likely contributor to the latency, but no stage-level profiler was run to apportion it. The mixed-language miss is expected for lexical retrieval without translation/embeddings. Zero forbidden selections applies only to these probes, not to every scope exception.

These are Windows debug-build in-process router timings, including persisted retrieval traces and excluding fixture setup. They are not production latency estimates. The benchmark database main file was 1,073,152 bytes; WAL size, peak RAM and indexing throughput were not measured. No comparative speedup is claimed.

Frozen fixture SHA-256: `1b29de1f8804a1916d75a7df7cdf4fc0296282a3cc48a2087c7a99dd175ef5ac`.

Tests use temporary databases and mock generation providers. Desktop-feature execution, browser QA, actual writer-tokenizer accounting, Bekko inference, Linux execution, peak RAM and indexing throughput were not measured in R0. No pre-existing automated failure was observed in the executed baseline suite. The benchmark's recall failures are retained as baseline limitations, not hidden by tuning fixtures.

## 6. R1 integration points and sequencing

1. Introduce a small native embedding module beside `foundation/memory/`, with provider-owned lazy session/tokenizer state, bounded concurrency and idle eviction. `AppState` owns its shared lifecycle; run blocking ONNX CPU work outside async workers and outside database transactions.
2. Extend `memory/settings.rs` and existing configuration validation additively for backend, local artifacts, threads, max tokens and keep-warm. Preserve existing installations and lexical fallback; do not turn Bekko on globally before qualification.
3. Replace only the optional embedding boundary in `retrieve_async`; keep `scope_allowed` and packing authoritative. Generation should continue consuming selected evidence through the shared preparation function, without knowing the embedding backend.
4. Inspect Verithen's actual ONNX/tokenizer/pooling/normalization implementation and model artifact identity during R1. The requested 384 dimensions, 512-token baseline and 300-second keep-warm are target contracts, not facts validated by R0.
5. In R2, add versioned f32-BLOB storage and resumable batch indexing alongside the legacy table. Never copy the current per-query passage-embedding loop into the native provider. Match chunk revision/checksum and model fingerprint before admitting vectors.
6. Resolve temporal/explicit-source eligibility exceptions and the pre-scope cap deliberately in the later scope/ranking work; qualify them before enabling semantic retrieval by default. R1 can test native inference in isolation while fallback remains the retrieval default.

## Rollback and review boundary

R0's additions are tests, a fixture, benchmark tooling and this report. They can be omitted without database changes. Do not reset or revert the pre-existing Phase A–C working-tree changes when reviewing R0. For a runtime trial, use a separate data directory populated from a backup; do not copy a snapshot over a live database. Keep legacy embedding storage during future additive migrations.

No remote PR was created because this branch has not been pushed and pushing was explicitly prohibited. The local branch and diff are the reviewable result. R0 does not qualify a Bekko rollout or claim improved retrieval quality.
