# R2 — Versioned semantic index

Opheline · 6 November 2026 · `codex/retrieval-r2-index`

R2 adds durable native embedding storage and explicit maintenance operations. Native semantic results are not wired into the writer or production retrieval. Existing LM Studio embeddings, legacy JSON vectors, FTS5, narrative authority and visibility policies are preserved. R3 still owns scope-safe hybrid recall and ranking.

## Checkpoint, data preservation and ownership

Before editing, `.codex-audit/retrieval-r2-20261106/pre-r2-checkpoint.zip` captured 25 files, HEAD, the binary working-tree diff and a SHA-256 manifest. Every archive entry passed CRC/hash verification. Repository and installed databases were copied through SQLite's online backup API using read-only source connections; both backups passed integrity checks. Sizes: 1,892,352 and 1,929,216 bytes. Configuration copies and manifests remain local and ignored.

Twelve unchanged R0/R1 files, including generation/analysis code, Phase A–C tests, the frozen 520-sibling fixture, frozen Bekko references, both earlier reports and Cargo manifests, match the checkpoint byte-for-byte. Relevant R1 provider modules are extended for identity inspection, explicit unloading and a process-wide residency limit. No dependency was added. No commit, push or merge was performed.

| Source | Responsibility |
|---|---|
| `migrations/semantic_index_v1.sql` | Additive schema, constraints, indexes and derived-source invalidation triggers. |
| `src/foundation/memory/semantic_index.rs` | Binary codec, generation contracts, status/coverage and internal fixture search. |
| `semantic_index/jobs.rs` | Queue, batching, leases, cancellation, retries, atomic commits and recovery. |
| `semantic_index/snapshot.rs` | Current source/chunk validation using the caller's SQLite connection. |
| `memory/indexing.rs` | Re-chunking identity, checksum-aware idempotence and same-revision supersession. |
| `memory/embedding*` | Existing R1 provider, optional native model, process residency reservation and explicit unload. |
| `store.rs` | Shared row decoding on caller-owned transactions and the vector-validation SQL function. |
| `lib.rs` | Maintenance initialization that preserves live writer run status. Normal startup recovery is unchanged. |
| `examples/semantic_index.rs` | Explicit maintenance CLI; no story-recall/search endpoint. |
| `semantic_index/tests*`, `tests/fixtures/semantic_index_r2.json` | Correctness, recovery and controlled native storage benchmark. |

## Additive migration and retention policy

The semantic schema has its own version **1**; the existing workspace schema version remains **7**, preserving the previous runtime's version boundary. Before first semantic migration, the application makes a unique SQLite online backup beside the selected database, named `*.before-semantic-v1-<uuid>.bak`. This also happens for fresh test/workspace stores. The migration runs in an IMMEDIATE transaction. It does not alter or remove legacy embedding tables or authoritative narrative tables.

| Table | Key and retained information |
|---|---|
| `semantic_model_generations` | Immutable fingerprint key; exact model/backend/dimensions, identity JSON, encoding version and creation time. Reusing a fingerprint with another identity is rejected. |
| `semantic_vectors` | `(chunk_id, model_fingerprint)` key; source revision, content checksum, chunker version, dimensions, little-endian f32 BLOB and indexed time. |
| `semantic_index_jobs` | Model/scope, status, durable cursor, progress/error counters, cancellation, owner/lease, timings and timestamps. A partial unique index prevents duplicate queued/running jobs for the same generation/scope. |
| `semantic_index_items` | Per-chunk/generation pending/current/failed/stale bookkeeping, captured identity and bounded errors. |
| `semantic_pending_sources` | Atomic dirty-source markers written by memory-chunk insert/update/delete triggers. These are a durable invalidation ledger, not proof of coverage. |
| `semantic_index_meta` | Independent semantic schema version. |

Vectors reference registered model generations. They deliberately have **no chunk foreign key**: deleted/replaced chunks cannot make old vectors eligible, but historical storage remains available for rollback and future explicit cleanup. No automatic generation/vector garbage collection is introduced.

Both Rust and SQLite validate exactly 384 dimensions and 1536 bytes, finite components and nonzero norm. Encoding is explicitly little-endian. SQLite uses the deterministic `semantic_f32_valid_v1` function, registered on each application connection. Corrupt vectors injected by bypassing CHECK constraints are excluded by decoding on read and can be reindexed.

External SQLite migration/integrity tools must register this function when evaluating the vector CHECK constraint. Plain read queries and old-runtime narrative writes do not require it; raw insertion into the managed vector table is not a supported provisioning path.

## Source identity and incremental behavior

Source revisions remain content hashes. Chunk layout identity now incorporates the structural chunker and configured size/overlap in a stable 48-bit `chunker_version`, exactly representable by SQLite and JavaScript. Chunk IDs include that identity. Refreshing with changed settings cannot reuse an old layout merely because the number of chunks is unchanged.

Source replacement marks previous active chunks stale inside the same transaction before activating the new set. This also handles extra old ordinals from a different layout at the same source revision. The idempotent path checks actual chunk IDs, checksums and text; it can repair a damaged projection while reusing a valid vector for unchanged source text. Existing chunks are retained and adopt the new layout identity when refreshed; changing chunking settings alone does not silently rewrite an entire workspace.

Eligibility for a stored vector requires matching generation, active chunk, source revision, content checksum, chunker version and a decodable vector. Authoritative sources are independently re-read: documents, entity variants, facts, relationships, timeline events and turn/chat-window text. Missing, archived, trashed, scratch and quarantined material is excluded. Owner/folder records participate in snapshot freshness checks. Content changes are detected even if `updated_at` is preserved.

This is storage freshness, not narrative visibility or Canon authority. R2 can retain vectors for different branches; it does not decide which character may know their contents. Unsupported legacy/synthetic source kinds are reported as excluded instead of being silently trusted.

Coverage is defined over the selected scope's **existing memory projections**. Run the existing Memory backfill/refresh when authoritative resources have not yet been projected. `awaiting_source_refresh` identifies existing projections whose authoritative source changed; `index_source` refreshes its requested source first. A job's finished pass is not a claim that every resource in the workspace was backfilled.

## Batches, commits, progress and recovery

1. Explicit maintenance captures a verified R1 model identity and registers its generation.
2. Candidate rows are scanned in stable ID order in pages of 64. Valid existing vectors are skipped.
3. Inference batches honor 1–64 texts, 64 KiB per text and 1 MiB total, with a default CLI batch size of 32.
4. Database connections/transactions used for selection are released before `EmbeddingProvider::embed_batch`.
5. An IMMEDIATE commit transaction rechecks job ownership/cancellation/lease and each chunk's identity, source existence/content, ownership and lifecycle.
6. Matching vectors, their item state and the durable job cursor/counts commit atomically. Stale results are discarded, never relabeled as current.
7. Coverage is checked after the pass. A database change across finalization, discarded snapshots or remaining missing/stale projections leaves the job `partial`, not `completed`.

Statuses distinguish queued, running, completed, partial, failed, interrupted and cancelled jobs. `index_status` independently reports current/pending/failed chunks, stale vectors, excluded material, source-refresh needs, generation availability, last failure, database/vector bytes and recent jobs. Job `failed` counts failed operations/batches; coverage `failed` counts current failed chunks. Timings include provider validation/inference, batch transaction cost and job duration. Commit timing is best-effort telemetry written after the atomic data commit; progress does not depend on that telemetry update succeeding.

The durable queue accepts at most **16 queued/running jobs**. At most four process-wide preflight requests may verify artifacts before enqueue; excess requests receive HTTP-style 429 errors before hashing or loading. One process-wide work permit dispatches an index job; requests arriving while it is occupied remain queued rather than spawning unbounded workers. Explicit `resume`/index operations dispatch work; startup does not load models or start an indexing daemon. The public worker also takes the existing storage maintenance read gate, allowing ordinary source edits while preventing an in-process destructive storage reset/import during its job.

Each running job has a unique process owner and a **60-second renewable batch lease**. Reopening another AppState in the same process does not steal a registered live job. An aborted worker in that process is recoverable immediately after its active registration disappears. An unfamiliar process owner's job is interrupted only after lease expiry; a restart may therefore require waiting up to 60 seconds before reconciliation. A batch that outlives/lost its lease cannot commit. Retry resets the scan cursor and attempt counters, preserving committed vectors and skipping them on rescan, so new IDs behind an old cursor are not missed.

Cancellation is cooperative through a durable flag. An in-flight batch checks it before commit; previously committed batches remain. Provider, model identity, input and SQLite failures leave explicit failed/partial state. If the failure-status write itself fails, the running lease remains recoverable. The tests inject SQL failures and real writer-lock contention; they do not kill an OS process during a physical disk write.

## Process memory and model lifecycle

R1 sessions remain per-AppState, but a new **one-resident-model-per-process** reservation covers initialization and the entire loaded session lifetime. Another AppState/service receives a typed `resource_busy` error instead of initializing a second large model. The reservation is released after model destruction, including errors and idle eviction. Configuration is not shared between workspaces.

Index jobs explicitly unload their provider before releasing the work permit. This bounds retained RAM and allows another workspace to proceed, at the cost of a fresh session for a later job. No-op jobs do not run inference. An existing standalone R1 diagnostic session can occupy the residency slot until explicitly unloaded or its TTL expires; retry the failed index job after release. Independent processes have independent residency limits; this is not a machine-wide RAM quota.

Every batch retains R1's actual-content artifact/runtime validation. No timestamp-only identity cache or individual missing-document inference loop is introduced. The model/runtime remain optional. Without a usable provider, normal retrieval stays lexical/structured; index maintenance returns a typed error or a retryable job failure. Status reads do not hash model files: cached diagnostics distinguish compiled/loaded/busy/last error, and are not an installation-availability probe.

## Maintenance commands and configuration

Use the [R1 native configuration reference](RETRIEVAL_R1_BEKKO_REPORT.md#configuration). No new persistent setting or dependency is required. Bekko remains an explicit backend choice; an explicit false in either existing enable gate disables native embedding. The R2 managed binary index supports native Bekko only; LM Studio's existing cache/provider path is retained separately and is not reinterpreted as Bekko vectors.

The CLI requires absolute root/config paths and an existing database. It will not create an empty workspace for a mistyped database path. For an installed native workspace, pass the actual flat database path explicitly because the application launcher can override the TOML's legacy relative path.

```powershell
$root = 'C:\ArlineTrial'
$config = "$root\config\arline.toml"
$database = "$root\arline_history.db"

cargo run --locked --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --example semantic_index -- --root $root --config $config --database $database index-pending --project PROJECT_ID --batch-size 32
# The result includes job ID, fingerprint, progress and coverage.

cargo run --locked --manifest-path crates/arline-runtime/Cargo.toml --example semantic_index -- --root $root --config $config --database $database status --fingerprint MODEL_FINGERPRINT --project PROJECT_ID
# Other commands: index-source --source-type document --source-id ID,
# reconcile --fingerprint FP, resume JOB_ID, cancel JOB_ID.
```

`open_index_maintenance` initializes the managed index and reconciles index leases without marking a live writer turn interrupted. Normal application startup keeps its previous generation-recovery behavior. No semantic maintenance HTTP route was added.

`--project` selects that exact project's projections. Shared library projections without that project ID require an unscoped pass or explicit source indexing; indexing does not change ownership.

Stored-vector cosine search is compiled only into controlled test/qualification fixtures. It uses an explicit project and authorized chunk allowlist before exact scoring/top-K, current-source validation, finite vector decoding and stable score/ID ordering. An unavailable generation produces an error; an authorized empty result is distinct. There is no arbitrary live-workspace semantic search CLI or writer integration until R3 supplies the authoritative narrative prefilter.

## Validation and measured results

Correctness coverage includes additive migration/backup restoration, legacy row retention, endian/finite/dimension checks, idempotence, edits with unchanged timestamps, damaged projection repair, archival/deletion/supersession, re-chunking, model changes, corrupted BLOBs, partial batches, SQL aborts, real writer contention, cancellation, late insertion behind a cursor, bounded repeated requests, live/aborted worker recovery and maintenance initialization beside a live writer. Existing R0/R1 suites and LM Studio compatibility tests are retained.

A maintenance CLI smoke run used a separate copy of the repository backup. Eleven existing narrative/legacy tables retained identical rows after migration. The CLI also rejected an absent database and left that path uncreated. Live repository/installed data was not migrated by these tests.

| Final verification | Result |
|---|---|
| Default-feature all-target tests | **214 passed**, none failed. |
| Native-feature all-target tests | **215 passed**, none failed; two explicit real-model tests ignored in the ordinary suite. |
| R2 correctness cases | **20 passed** in each feature configuration. |
| Strict Clippy, all targets | Passed with default and native features, `-D warnings`. |
| Real provisioned R1 reference/parity test | Passed separately, including frozen vector references and truncation. |
| Real provisioned R2 release benchmark | Passed separately; measured results below. |
| Frozen Phase A–C regression cases | All eight passed in both suites. |
| Preservation and whitespace | Twelve checkpoint files match byte-for-byte; `git diff --check` passed. |

Reproduce the feature checks from the repository root (the runs above used `--offline` with already provisioned dependencies):

```powershell
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko -- -D warnings

# Point to existing qualified files; these commands do not provision a model.
$env:ARLINE_BEKKO_MODEL_DIR = 'C:\Models\bekko'
$env:ARLINE_ONNX_RUNTIME = 'C:\Runtime\onnxruntime.dll'
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --lib qualified_bekko_vectors -- --ignored --test-threads=1
$env:ARLINE_R2_REPORT = "$PWD\.codex-audit\retrieval-r2-20261106\native-benchmark-repeat.json"
cargo test --release --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --lib native_semantic_index_benchmark -- --ignored --test-threads=1
```

Windows qualification used the same locally provisioned Bekko revision and ONNX Runtime CPU 1.27.0 as R1, Rust 1.93.0, Ryzen 9 7950X, two intra-op threads and a 512-token cap. No files were downloaded or installed. The frozen development storage fixture has **256 synthetic documents, 16 edits and 32-text batches**; OS file caches/system load were uncontrolled. This is not a held-out narrative retrieval evaluation.

| Metric | Final release-mode run |
|---|---:|
| Initial 256-chunk index | **3850.75 ms; 66.48 chunks/s** |
| No-op pass | **183.66 ms; zero embedding calls** |
| Sixteen edited chunks | **1474.11 ms; 10.85 chunks/s** |
| Full native batch p50 / p95, nine batches including fresh-session batches | 197.49 / 1266.12 ms |
| Artifact/runtime validation across the initial eight batches | 795.72 ms (~3.11 ms per indexed chunk) |
| Initial batch transactions, source recheck through COMMIT | 54.66 ms total |
| Reopen and recover an expired job | 30.66 ms |
| Exact diagnostic search, 20 samples | 30.78 ms p50 / 48.78 ms p95 |
| Logical SQLite size, before / initial / incremental | 1,261,568 / 1,974,272 / 2,043,904 bytes |
| Stored vector payload after edits | 417,792 bytes; 256 current + 16 retained stale vectors |

Phase timings include identity inspection, core job execution and explicit session unloading; fixture preparation and uncontended scheduler setup are excluded. The earlier run took 2909.86 ms initially, 173.93 ms for no-op and 1417.98 ms incrementally. Two observations do not establish stable throughput or tail latency. Fresh session construction/teardown is included in incremental job cost; it is not a warm-inference-only rate.

The final isolated test process recorded 702,033,920 peak resident bytes by the loaded probe and 703,098,880 across residency transfer (~670.53 MiB). Loaded resident memory was 347,422,720 bytes (~331.33 MiB), falling to 54,743,040 (~52.21 MiB) after a two-second test eviction. A second service was rejected while residency was occupied and loaded successfully after release. R1's full 300-second eviction record remains separate; R2's memory probe scales the configurable TTL to two seconds.

For context, frozen R1 recorded warm single-text inference at 2.07/2.71 ms p50/p95, full provider calls at 93.61/94.67 ms and 91.52 ms median integrity validation. R2 amortizes validation across batches, rather than omitting it. These are different workloads and lifecycle boundaries; no matched retrieval speedup or narrative recall improvement is claimed. Initialization still has a substantial RAM peak.

Linux remains **unqualified**. Read-only environment discovery found no Docker command, and `wsl --list --quiet` reported that WSL is not installed. No machine/VM changes were made. Ubuntu CI already includes default/native-feature checks from R1, but this branch has not been pushed and those checks have not run there. Fresh desktop/browser QA and multi-process load stress were not performed.

Raw reports, logs, checkpoint and copied-database evidence are local under `.codex-audit/retrieval-r2-20261106/`; the final native report is `native-benchmark-final.json`.

## Backup and rollback

Keep the automatic pre-migration backup and the pre-R2 checkpoint. For an additional online backup, use SQLite's backup API, including committed WAL frames; copying only the main file while it is open is insufficient. Example standalone Python script, run with `uv run --no-project python backup.py` after setting explicit paths:

```python
import math, sqlite3, struct
from pathlib import Path
source = Path(r'C:\ArlineTrial\arline_history.db').resolve()
target = Path(r'C:\ArlineBackups\arline-r2.db').resolve()
def valid(blob, dimensions):
    if dimensions != 384 or not isinstance(blob, bytes) or len(blob) != 1536:
        return 0
    values = struct.unpack('<384f', blob)
    return int(all(map(math.isfinite, values)) and any(values))
with target.open('xb'):  # refuse to overwrite an existing backup
    pass
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst:
        dst.create_function('semantic_f32_valid_v1', 2, valid, deterministic=True)
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone() == ('ok',)
```

For rollback, stop users of the selected database and restore a backup into a **separate data directory**, then review it with the previous runtime. Do not overwrite the live workspace. R2 tables may also remain in place while using the old lexical/LM Studio path; historical embedding rows are retained and the workspace version was not raised. Backup restoration, authoritative document retention and old-style SQLite narrative writes without the new function were tested. This is not a claim that a previous desktop binary was launched against every historical schema.

Do not indiscriminately drop tables or restore the entire source checkpoint over later user changes. R2 cleanup/retention policy is intentionally deferred. Source rollback must preserve the accepted R0/R1 and Phase A–C work.

## R3 integration boundary

R3 can consume immutable generation identities, validated f32 decoding, current-source checks, job/status APIs and stored vectors. It must add an authoritative project/world/branch/session/time/POV prefilter **before semantic top-K**, independent final eligibility checks and deterministic relevance fusion. Vector presence alone must never grant Canon or visibility.

Query embeddings must use the same verified model fingerprint as the selected stored generation, in addition to matching its dimensions and encoding.

The frozen R0 520-sibling candidate-cap case is unchanged. FTS pre-scope limits, opaque temporal comparisons, explicit-source exceptions, hybrid ranking and narrative-specific weighting remain R3 work. R3 must also deliberately retire/adapt the retained legacy HTTP passage-embedding loop; R2 never copied it into native generation. Writer integration must continue through selected evidence only, with R4's tokenizer budgeting remaining separate.
