# R3 — Scope-safe hybrid narrative retrieval

Opheline · 6 November 2026 · `codex/retrieval-r3-hybrid`

R3 adds opt-in native hybrid retrieval through the existing selected-only writer boundary. **The default remains `legacy`.** Windows qualification uses real provisioned Bekko/ONNX Runtime and synthetic narrative fixtures; it does not establish relevance or latency on a large user manuscript. Linux remains unqualified.

## Preservation and compatibility

The branch starts from `codex/retrieval-r2-index`. Before editing, `.codex-audit/retrieval-r3-20261106/pre-r3-checkpoint.zip` captured all 37 tracked/untracked changed files, HEAD, a binary diff and SHA-256 manifest; CRC and entry hashes passed. Two read-only-source SQLite online backups passed integrity checks. All evidence remains local and ignored. No commit, push or merge was performed.

Thirty-one checkpoint files remain byte-for-byte unchanged, including R0–R2 fixtures/reports, R2 jobs, snapshots, migration and embedding lifecycle, Cargo files, generation/recovery code and existing compatibility tests. Six existing files were deliberately extended: configuration, `config.rs`, `memory.rs`, `semantic_index.rs`, `analysis.rs` and the Phase A–C integration test file. Original Phase A–C cases remain intact; new cases are appended.

**No schema change or dependency was introduced.** Semantic schema v1, workspace schema v7, `semantic_f32_valid_v1`, binary encoding, old JSON embedding tables, automatic migration backups, snapshot freshness checks and historical vector retention remain intact. R3 tests and benchmarks use temporary stores; live repository/installed databases were not opened for migration or indexing.

## Implementation and ownership

| Component | R3 responsibility |
|---|---|
| `memory/scope.rs` | Typed request scope and temporal comparison, request/session validation, cached lineage/lifecycle/source ownership gate and conservative SQL prefilters. |
| `memory.rs` | Paged lexical/structured discovery, shared eligibility, legacy compatibility, packing and rollout dispatch. |
| `memory/hybrid.rs` | Deterministic intent, native query operation, RRF, final revalidation, shadow comparison and profiling. |
| `semantic_index/retrieval.rs` | Read-only scope-aware adapter over R2 vector decoding, current-vector checks and authoritative snapshots; scoped readiness. |
| `analysis.rs` | Existing selected-only integration plus aggregate readiness/fallback diagnostics and evidence labeling. |
| `examples/hybrid_qualification.rs` | Isolated, frozen, real-model comparison and resource probes. |

R2 continues to own storage, generations, indexing, retries, cancellation, leases, migration and model residency. R3 does not implement another index or provider. No ANN service, external Verithen dependency, mandatory planner LLM, Canon promotion change or generation-architecture rewrite was added. Verithen's already provisioned local artifact paths were used only as qualification inputs.

## Scope and temporal contract

`NarrativeScope` parses project/world/branch/session/POV IDs, lens, world time, story order and author/scratch flags. Malformed types and unknown lenses are rejected. An existing session supplies its project/world/branch; conflicting request values fail closed. Known branch/world ownership is resolved and checked, including explicit project/world links. Omitted or unknown IDs do not grant a cross-scope exemption.

Each scan uses a request-local gate with one SQLite connection, cached source/owner rows, cached ancestor turn sets and a lifecycle set. Project/world/visible branches and direct lifecycle exclusions are pushed into chunk SQL before page limits. Additional checks run before a row enters a lane. Where SQL cannot express the complete contract, discovery continues in **64-row pages until enough eligible rows are found or the query is exhausted**. There is no global 500-row ceiling. Structured lanes also page and bound their eligible output. Native exact cosine scans eligible indexed rows and retains a bounded top candidate set.

Branch ancestors are visible only through their fork cutoff; nested ancestry retains the earliest applicable recorded-time cutoff. Session ancestors require a known fork turn and include only turns through that boundary. Missing cutoff turns expose no ancestor history. Siblings and descendants remain excluded. Source deletion, archival/trash, owner/folder lifecycle, scratch policy, quarantined trust, known instruction patterns, private/author-only POV restrictions and declared `visible_to` restrictions apply to every lane. Canon facts marked draft remain provisional; rejected/superseded/deleted sources are excluded.

| Time values | Comparison |
|---|---|
| Finite numbers, including numeric strings | Numeric order. |
| RFC3339 timestamps | Chronological order, normalized by the date-time parser. |
| Identical opaque fictional labels | Equality only. |
| Different opaque labels, mixed or unsupported types | `Incomparable`; conservatively excluded when a chronological restriction applies. |

World chronology, story order and recorded fork timestamps remain separate. Historical interval ends are exclusive. Current-state projections do not substitute for requested historical intervals. Unknown fictional labels are never sorted alphabetically. Future evidence requires the existing explicit author/future flag and no character POV.

Absent time metadata retains the existing timeless-evidence behavior; the engine does not invent chronology for an undated passage. Equality of an opaque label establishes only the same label, not an order between eras.

### Explicit-source policy and legacy compatibility

Previously, matching an explicit source ID bypassed trust, scratch, lineage, time and POV checks. R3 keeps the request shape but tightens its meaning: **only `context_lens="author"` with no POV may use an explicit source to cross project/world/branch/session boundaries**. The reference must contain matching nonempty source type and ID. Lifecycle, trust, instruction hygiene, chronology and scratch restrictions still apply. Future inspection separately requires `allow_future_author_knowledge=true`.

Ordinary scene/POV references grant no elevated visibility. This safety correction applies in all modes, as does conservative temporal comparison. Legacy rollback restores the qualified legacy provider/ranking path, not the unsafe ID bypass. An integration relying on old implicit cross-scope behavior must supply intentional author context; it cannot override lifecycle or trust by naming an ID.

## Native query, readiness and fallback

One semantic operation calls the existing provider with **one query text**. Provider artifact/runtime validation is retained on each call. The returned verified identity must exactly match the stored generation contract, including fingerprint, dimensions and encoding. R3 does not select an older generation when files/settings change. Vectors must match active chunk revision/checksum/chunker identity and R2 authoritative source snapshots before scoring.

Inference runs outside SQLite transactions. Retrieval performs no memory backfill, index maintenance, passage embedding or no-op reindex. Manual indexing remains an explicit R2 operation. The legacy LM Studio rollback path retains its existing compatibility behavior, including legacy cache filling; that path is not used by native hybrid retrieval.

Four process-wide native query admission slots bound queued inference work. Existing R1/R2 per-service admission and one-resident-model reservation remain authoritative. Missing artifacts/runtime, a feature-disabled binary, invalid/unavailable native settings, contention and an absent active generation produce explicit lexical/structured fallback. No model is loaded merely because an index exists or legacy mode is selected.

Readiness distinguishes:

- Authoritative sources never projected, and sources requiring projection refresh, including ownership moves.
- Current projected chunks awaiting embedding for the verified active generation.
- Current valid indexed chunks.
- Stale/invalid vector rows encountered in the eligible projection scan.
- Provider/generation unavailability. If no current fingerprint can be verified, embedding readiness is **unknown**, rather than falsely declaring existing chunks unembedded.

`semantic_result_state` distinguishes provider unavailable, generation unavailable, partial coverage, empty matches and available matches. Partial coverage can enrich eligible lexical results without pretending that the whole manuscript is indexed. Coverage is computed from sources/projections, never from a job's completed status. Legacy mode explicitly reports that coverage was not inspected, avoiding model/file probes and full readiness scans on the default path.

Scoped readiness is not a historical-vector garbage-collection inventory: retained obsolete generations/deleted chunks remain available through R2 maintenance status. SQL-pruned forbidden rows are not enumerated in diagnostic exclusion counts. Those counts describe only rows remaining after safe prefilters.

## Intent, ranking and packing

The deterministic planner recognizes current state, historical recall, relationships, POV knowledge, recent scene continuation and general manuscript search from the request and established context. Existing structured Canon/state, intervals, epistemic, spatial and thread lanes are reused. Conversation projections participate in lexical/semantic lanes; continuation can add up to eight recent **eligible** turn/chat-window chunks.

Hard eligibility precedes lane selection. Current accepted state/Canon gets an applicability tier for current-state questions; provisional/exploratory/contradictory evidence is lower priority. Relevance then uses reciprocal rank fusion, `sum(1/(rrf_k + rank))`, default `rrf_k=60`, across relevance-ordered lexical/structured and semantic candidates. FTS uses BM25 in the new path. Importance cannot override relevance. All final ties use stable IDs. Existing source diversity, final K and estimated-token packing remain in place.

The experimental cosine floor is configurable as `memory.semantic_min_score`, finite in `[-1,1]`. The development choice is **-1.0**, admitting every valid cosine to ranking rather than importing an unqualified 0.5 threshold. No held-out query was used to tune weights or thresholds. Synthetic results below show that this simple fusion can underperform semantic-only ranking; additional development data is needed before changing it.

After inference/fusion, the final gate rereads actual memory chunks and current authoritative metadata in a fresh read transaction, rejects changed/deleted/ineligible sources, updates provenance and reapplies authority ordering. Only final `selected` rows enter `analyze_async_profiled` and shared generation preparation. Raw candidates, excluded rows, score components and traces stay outside writer input. Provenance retains source, revision, authority and trust. The evidence block explicitly states that passages are evidence rather than instructions/Canon decisions and escapes angle-bracket delimiters. Pattern-based hygiene and evidence labeling are not a proof against every possible model prompt-injection strategy.

Normal, streaming and multi-beat generation continue through the same boundary. Phase B recovery, Phase C idempotency, LM Studio writing and context-overflow rejection are preserved. Token counts remain estimates; R4's tokenizer-aware compiler is not implemented here.

## Rollout configuration and rollback

```toml
[memory]
engine_mode = "legacy"       # default; alternatives: shadow, hybrid
semantic_min_score = -1.0
```

Use the existing [R1 native configuration](RETRIEVAL_R1_BEKKO_REPORT.md#configuration) and explicit enable/backend gates to enable native query embeddings. Either saved embedding-disable gate continues to win. Existing installations with no new setting remain legacy.

- `legacy`: legacy importance ordering/LM Studio compatibility, with the shared scope/time safety fixes. Native passage retrieval is inactive.
- `shadow`: opt-in hybrid comparison plus separately packed legacy input. Writer input is legacy; the comparison contains IDs, counts and timings, not shadow passages. It performs extra query work and writes retrieval traces only.
- `hybrid`: opt-in eligible hybrid `selected` evidence reaches the writer.

Set `memory.engine_mode="legacy"` to roll back the engine without migrating/dropping data. Keep the pre-R3 checkpoint and database backups. For source rollback, review the checkpoint diff and restore into a separate checkout/data directory; never overwrite later user changes or the live database. R2's [backup/rollback procedure](RETRIEVAL_R2_SEMANTIC_INDEX_REPORT.md#backup-and-rollback) still applies. No R3 schema change required a new migration or old-runtime schema contract.

## Diagnostics and qualification

Local retrieval responses/traces include effective scope, intent, lane counts, post-prefilter exclusion counts, generation identity, readiness, fallback, component ranks, selected IDs, estimated context cost and timings. Profile stages cover scope planning, lexical/structured/recent discovery, query embedding, semantic candidates/readiness, fusion, final eligibility and packing. The HTTP total also includes persisted tracing/dispatch. Generation diagnostics carry aggregate readiness/fallback and counts; these are not serialized into the writer prompt. No authentication/authorization server was added to the existing local maintenance API; developer traces are not suitable for publication as a multi-user endpoint.

### Correctness

| Verification | Result |
|---|---|
| Default-feature all-target suite | **226 passed**, none failed. |
| Native-feature all-target suite | **227 passed**, none failed; three explicit real-model cases ignored in the ordinary suite. |
| R3 focused correctness | Eleven cases passed in both feature configurations. |
| R2 index correctness | All twenty existing cases passed in both configurations. |
| Phase A–C plus rollout matrix | Original eight cases and new mode/path matrix passed. |
| Strict Clippy, all targets | Passed with default/native features and `-D warnings`. |
| Provisioned Bekko → writer paths | Passed separately for normal, streaming and beats. |
| Provisioned release relevance/resource qualification | Passed; results below. |
| Preservation/whitespace | Thirty-one checkpoint files byte-identical; original Phase A–C lines preserved; `git diff --check` passed. |

Coverage includes the frozen 520-sibling regression, author-reference pagination without SQL lineage pruning, nested forks and session cutoffs, retcons/lifecycle, current/historical state, opaque time, explicit-source trust/POV limits, corrupt/wrong-generation vectors, partial/unprojected/stale sources, concurrent source edits during inference, deterministic fusion, exact names, zero budgets, provider errors and shadow isolation. A dense top-1 regression also verifies that higher-cosine sibling/private vectors cannot displace a lower-cosine eligible bilingual passage. The three ordinarily ignored cases are R1 reference parity, the R2 native benchmark and the new R3 native writer test. R1/R2 real-model qualification remains the preserved prior-milestone record; R3 explicitly ran the new native writer and comparative benchmark cases.

An added writer matrix exercises all three rollout modes across normal, streaming and beat routes, checking forbidden text and diagnostic exclusion. A separate real Bekko test indexes bilingual evidence and verifies its selected-only handoff to each writer route. Writer services are mocked; this verifies request preparation, streaming completion and persistence, not live LM Studio literary quality.

### Frozen evaluation protocol

`tests/fixtures/retrieval_r0.json` is unchanged. The R0 example retains its original debug methodology: isolated in-process router, one warm-up per query, 20 samples, scope/packing and persisted trace included. The 520-sibling case now selects the eligible result with Recall@5=1 and zero forbidden selections. The original 2.93/3.36-second debug references are historical observations, not production SLOs. No debug-to-release speedup is claimed.

The final isolated debug rerun measured the scope-pressure case at **20.47 ms p50 / 24.76 ms p95**. Exact-name recall stayed 1 at 21.08/22.33 ms; lexical-only mixed-language recall stayed 0 at 20.21/21.75 ms. The earlier R3 pressure rerun was 21.23/22.96 ms. These use the frozen R0 methodology; machine/cache load was not a controlled paired experiment with the historical R0 measurement.

`retrieval_r3.json` is a frozen authored synthetic corpus: **24 narrative documents, six development queries, ten held-out queries**, English/Indonesian, four exact-name queries. SHA-256: `2b7d626dab96a801c4c62ac2e2e8e7713ea74df74218af727d6400c607c8f6a4`. Predefined primary gate: held-out mean nDCG@10 improves over safe legacy, exact-name Recall@5 remains 1, unauthorized selections remain zero. Repeated timing samples are not independent relevance observations.

Four arms use identical text/scope fixtures: safe legacy; scope-aware BM25/structured retrieval; Bekko-only diagnostic ranking; full hybrid. The legacy arm includes mandatory safety fixes and is not an execution of the archived pre-R3 binary. Bekko-only rankings are extracted from the same eligible candidate pool before hybrid packing; their reported latency includes hybrid orchestration and is not isolated semantic-search latency. Current-state factual correctness and branch/time safety are asserted by discriminating regression fixtures, separately from this relevance corpus.

Final Windows release measurements: one warm-up per query and three timed repeats, 48 samples per arm. Both frozen runs produced identical relevance metrics and passed the predefined gate. Reports are `qualification-release.json` and `qualification-release-final.json`. Windows used the R1-qualified local Bekko revision, ONNX Runtime CPU 1.27.0 and two intra-op threads. Files were neither downloaded nor installed.

| Arm | Held-out Recall@5 | MRR@10 | nDCG@10 | Query p50 / p95 |
|---|---:|---:|---:|---:|
| Safe legacy | 0.30 | 0.250 | 0.286 | 18.57 / 22.59 ms |
| Scope-aware FTS/structured | 0.40 | 0.320 | 0.339 | 31.20 / 43.66 ms |
| Bekko-only diagnostic | 1.00 | 0.858 | 0.893 | 127.05 / 133.27 ms* |
| Full hybrid | **0.70** | **0.470** | **0.525** | **127.47 / 143.00 ms** |

\* Bekko-only latency includes hybrid orchestration, as described above. All arms retained exact-name Recall@5=1; all measured unauthorized selections were zero. Development nDCG@10 was 0.500 legacy, 0.667 scope FTS, 1.000 semantic-only and 0.667 hybrid. The simpler semantic-only ranker outperformed RRF on this fixture; hybrid improves the qualified legacy baseline but is not established as the best ranker.

| Hybrid stage | p50 | p95 |
|---|---:|---:|
| Scope planning | 1.80 ms | 2.30 ms |
| Lexical/structured discovery | 10.78 ms | 12.08 ms |
| Query embedding, including integrity verification | 95.13 ms | 97.06 ms |
| Semantic candidates and scoped readiness | 5.43 ms | 5.81 ms |
| Fusion | 0.12 ms | 0.21 ms |
| Final eligibility and current metadata reread | 3.87 ms | 4.17 ms |
| Packing | 0.24 ms | 0.29 ms |

Per-stage percentiles do not add to end-to-end percentiles. The latter includes dispatch, runtime configuration and persisted tracing. Median provider artifact validation was 92.74 ms; inference itself was 2.35 ms. Median estimated packed cost was 515.5 tokens, range 493–530, at final K=10 and an 8192-token packing ceiling. R4 must replace this estimate with actual tokenizer accounting.

Peak process resident memory was **700,469,248 bytes (~668.02 MiB)**; loaded resident memory was **253,644,800 (~241.89 MiB)**. After explicit unload/resource probes it was **55,271,424 (~52.71 MiB)**. This is not another full 300-second idle-eviction test. The first run's hybrid p50/p95 was 125.71/132.61 ms; caches and system load were uncontrolled, and no numeric production latency SLO was predeclared.

Outside timed samples, a second AppState sharing the fixture database reported `resource_busy` and selected one lexical result without another resident model. A query overlapping an explicitly requested no-op index pass returned ten selected items; the index completed with zero new passage embeddings. This is a bounded contention probe, not sustained/multi-process load qualification.

R2's 66.48 chunks/s, 183.66 ms no-op pass, 30.78 ms diagnostic-search p50 and ~670 MiB peak measure different operations. R3's complete query includes artifact verification, scope, readiness, fusion, final revalidation and persistence. It never pays a no-op indexing pass per query. No cross-workload speedup or RAM improvement is inferred. Neither the 24-document corpus nor the 520-row pressure fixture establishes large-corpus manuscript performance: exact search/readiness remain linear scans with paged buffers and request-local caches.

### Reproduce

```powershell
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko -- -D warnings

# Use already provisioned qualified artifacts and a new output path.
$env:ARLINE_BEKKO_MODEL_DIR = 'C:\Models\bekko'
$env:ARLINE_ONNX_RUNTIME = 'C:\Runtime\onnxruntime.dll'
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --test orchestration_o01 r3_native_index -- --ignored --test-threads=1
cargo run --release --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --features native-bekko --example hybrid_qualification -- --out C:\ArlineReports\r3.json --model-dir $env:ARLINE_BEKKO_MODEL_DIR --runtime $env:ARLINE_ONNX_RUNTIME
cargo run --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example retrieval_baseline -- --out C:\ArlineReports\r0-pressure-debug.json --repeats 20
```

Output paths must be new; qualification refuses to overwrite previous reports. Raw JSON, logs, backups, manifests and the checkpoint remain under `.codex-audit/retrieval-r3-20261106/`. Linux is unqualified: read-only discovery reconfirmed no Docker command and WSL not installed; no VM/system change was made. No desktop visual QA or actual legacy desktop binary launch was performed.

## R4 handoff and rollout decision

R4 should consume final eligible `selected` evidence with immutable source/revision/authority provenance, honor partial/unknown coverage, and account for the evidence label, provenance and separators using the actual writer tokenizer. It should replace approximate packing without weakening scope or introducing generation-time index maintenance. Keep raw traces separate, preserve overflow rejection and all three generation paths, and retain selected-only recovery/idempotency regressions.

The hybrid engine remains an explicit experiment despite passing the bounded relevance gate. Before considering default activation, qualify real manuscript workloads, larger scopes, sustained resource contention and platform behavior; improve fusion on separate development data and repeat the frozen held-out gates. No default activation, publication or release action was taken.
