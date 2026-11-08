# R4 — Token-aware narrative context compiler

Opheline · 7 November 2026 · `codex/retrieval-r4-context`

R4 compiles and validates complete writer payloads against a **reported loaded instance window**, with explicit verified, conservative and unavailable accounting. The native default uses conservative UTF-8 byte accounting; a separately configured, qualified LM Studio SDK helper provides model-compatible counts. **Legacy retrieval remains the default.** No retrieval weights, eligibility rules, embedding provider, Canon policy or database schema were changed.

## Checkpoint and preservation

The branch starts from `codex/retrieval-r3-hybrid`. Before edits, `.codex-audit/retrieval-r4-20261107/pre-r4-checkpoint.zip` captured all 44 changed/untracked files, HEAD, the binary working-tree diff and a SHA-256 manifest. CRC and entry hashes passed. Repository/installed databases were backed up through read-only-source SQLite online backup and passed integrity checks. Live narrative databases were not migrated, indexed or used for generation qualification.

All R0–R3 retrieval/index/provider implementations, fixtures and reports remain intact. Intentional existing-file changes cover generation preparation, planner serialization/validation, compact evidence provenance, configuration validation, error diagnostics, module registration and mock loaded-model metadata in HTTP tests. Tokio's existing dependency enables its `process` and `io-util` features for the optional counter subprocess; no new crate or model download was introduced. Original Phase A–C assertions remain in place. No commit, push, merge or deployment was performed.

An isolated R3 source snapshot, reconstructed from HEAD plus the pre-R4 checkpoint, runs the same preparation harness for the release comparison. It uses temporary databases and mock writing, not copies of live narrative data. All snapshots, reports, logs and executable hashes remain local/ignored; none replaces the active checkout.

## Context boundary audit

| Input component | Owner and authority | R3 behavior | R4 boundary |
|---|---|---|---|
| Writer system prompt, conversation profile/mode, scratch instruction | `generation::chat_payload`; provider/system role | Counted separately at characters/3. | Actual serialized system prompt included in whole-payload accounting; never trimmed. |
| Canon, WCF, active state, POV/scene constraints | `analysis` and the established input-mode renderer | Workspace character cap could cut a record; derived WCF could prune at 4096 words. | Complete writer-specific grounding/WCF; mandatory token validation. Bounded preview behavior and scope selection remain intact. |
| User request, AIF, brief, unresolved context and separators | `compose_input`/provider serializer | Character estimate; some modes intentionally repeat the raw request. | Count the final renderer output, preserving existing mode semantics and required request. |
| R3 `selected` memory | Retrieval owns authorization/order/authority; compiler owns optional retention | Memory tail removed using characters/3; passage-only R3 packing also estimates cost. | Typed selected evidence, complete labels/provenance/scope counted; remove complete items from the tail before history. No raw `results` or `excluded` consumption. |
| Session history | `session_history`; continuity, not Canon | Turn count, then character cap and arbitrary suffix trimming. | Accepted edits retained; typed complete turns; oldest turns removed whole only after optional memory. `continuity_turns` remains bounded at 100. |
| Planner input/output | Deliberator; soft non-Canon guidance | Planner could run before writer overflow detection; writer model assumed. | Mandatory writer preflight first; planner has independent model/window/output validation; final writer check after planner output. |
| Previous beats and beat instruction | Shared beat orchestration; required active continuity | Last 9,000 characters retained; estimated future overhead. | Preserve full completed beat surface; reconstruct and validate each actual beat payload. A later overflow preserves the completed prefix as failed/partial. |
| Chat template, roles, generation prefix, special tokens | Actual writer tokenizer/provider | Unmeasured allowance. | Qualified SDK template count or explicit conservative template allowance; complete serialized payload rechecked. |
| Images/multimodal payload | Provider-specific | Uncounted. | Explicit unavailable accounting and HTTP 422 before planning/writing until image costs are qualified. |
| Visible/reasoning output | Existing `OutputBudget`/`BudgetPlan` | Combined provider output cap. | Reserve the unchanged actual API cap for each call/beat; preserve visible targets and reasoning semantics. |

The old compiler counted characters/3, subtracted an estimated system prompt and speculative beat overhead from a requested/configured window, clipped history and ignored images. Mandatory overflow already returned HTTP 413; R4 preserves that status and adds nonsensitive structured diagnostics. Generation still uses the existing writer, WCF/input renderer and durable completion/failure/cancellation machinery.

## Implementation

| Component | Responsibility |
|---|---|
| `inference/context.rs` | Typed items/authority/selection/history/budget/compiled context, deterministic allocation, whole-payload final validation and structured reports. |
| `inference/context/counter.rs` | Actual loaded-instance resolution, capacity checks, accounting states, native estimator and bounded optional SDK protocol. |
| `generation.rs` | Mandatory preflight, actual normal/stream/beat serialization, per-call recompilation, actual usage observation and terminal context rejection for idempotent requests. |
| `analysis.rs` | Independent planner budget, guidance-only serialization, compact source-scope provenance and existing selected-only handoff. |
| `context.rs`, `analysis/wcf.rs` | Separate complete writer rendering from bounded previews; prevent upstream Canon/locked-state clipping before token validation. |
| `lib.rs` | Optional error diagnostic payload; unrelated error responses retain their previous shape. |
| `examples/support/writer_sdk_counter.py` | Optional UTF-8 JSON-lines SDK adapter; enumerates already loaded handles and never JIT-loads weights. |
| `qualify_writer_tokens.py`, `context_qualification.rs`, `context_preparation.rs` | Frozen reference comparison, allocation benchmark and shared generation-preparation harness. |

`ContextItem` records stable ID, revision when available, content type, authority, mandatory/optional state, scope/applicability, provenance, priority, estimated cost and decision reason. Raw item content is excluded from diagnostic serialization. `ContextSelection` keeps mandatory narrative components separate from selected evidence and whole history turns. `CompiledWriterContext` carries the exact provider payload, rendered context, retained evidence, next selection and budget report; compatibility serialization remains the rendered string.

The allocator preserves R3 relative order and source identity. It never uses fusion scores to override Canon or eligibility. It first removes the low-ranked tail as needed, then deterministically reconsiders removed complete items against remaining space: a passage too large to fit cannot block a smaller later authorized passage. It never clips a passage. Once a compilation phase drops evidence/history, later phases/beats cannot restore it accidentally; excluded evidence IDs/reasons and dropped-history counts accumulate across phases. Selected passages retain source/revision, original authority/trust and compact project/world/branch/session labels. Evidence remains explicitly labeled as data, with escaped delimiters.

Workspace previews still honor their character cap, and standalone analytical WCF previews keep their existing word budget. Generation uses complete renderers over the same validated scope/records. Required workspace Canon, active scene and locked derived state therefore reach mandatory token validation intact; too-large content is rejected rather than silently passed as a clipped preview. Existing extraction/planner-normalization heuristics and R3's own preliminary selected-evidence packing remain unchanged. Their legacy estimates never authorize the final writer payload.

## Loaded model and token accounting

The native resolver uses the documented [LM Studio v1 model list](https://lmstudio.ai/docs/developer/rest/list), requiring exactly one loaded writer instance selected by model key or instance ID. It reads `loaded_instances[].config.context_length`; **`max_context_length` is never used as loaded capacity**. An unloaded, ambiguous or unsupported instance fails with HTTP 503 rather than silently assuming the configured/theoretical maximum or loading weights.

Requested/configured context can only lower the compiler's effective input cap. The physical loaded window is separately retained. The outgoing request uses that physical window, so a smaller allocation cap cannot trigger a model reload. Qualification observed that a differing per-request `context_length` with a custom instance ID could return 404; actual-window serialization eliminated that failure. The documented [chat API](https://lmstudio.ai/docs/developer/rest/chat) exposes context length and actual input usage, but does not make a model's theoretical maximum a loaded-window guarantee.

Metadata is read again before inference; there is no cross-request capacity cache. Stable identity covers model key, instance ID, load configuration, architecture and format, excluding volatile TTL countdown. Resize/reload/ambiguity tests fail closed. As with any external provider, a concurrent change after the final check cannot be made atomic with HTTP dispatch; the request pins the selected instance and actual window rather than requesting JIT replacement.

| Accounting state | Meaning |
|---|---|
| `verified_model_compatible` | Optional SDK counter matched an instance/tokenizer/template-bound real-provider qualification profile. Count covers the actual system/user template and qualified reasoning prefix. |
| `conservative_estimated` | Native serialized UTF-8 byte count plus 256 template tokens, or unqualified SDK tokenization plus 256 template tokens. Estimates remain explicitly labeled. |
| `unavailable_or_untrusted` | Loaded capacity unavailable/changed, unknown multimodal cost, or observed provider usage disagreeing with the compiled count. No unavailable preflight count is sent to inference. |

The safety reserve is `max(configured_margin, ceil(effective_window/20))`, default configured margin 128. Thus:

```text
input limit = effective loaded-window cap - unchanged output API cap - safety reserve
```

Provider/template costs are included in the counted input, not subtracted twice. The native estimator counts the entire serialized JSON payload, including non-token control fields, which deliberately overestimates ordinary byte-fallback tokenization. Its calibration is limited to the provisioned models/probes below; arbitrary tokenizers, provider-side preprocessors and custom templates are not universally proven by a byte estimate.

The [documented SDK tokenization procedure](https://lmstudio.ai/docs/typescript/tokenization) applies the model's prompt template before counting. R4 uses that behavior through an optional trusted local helper, not an undocumented REST tokenization endpoint. Bekko's embedding tokenizer is never used for writing. In-process Rust counting was investigated: the provisioned writers are GGUF, and the existing embedding tokenizer cannot reproduce their writer vocabulary/template/runtime formatting. Adding another model loader or guessing GGUF templates was not justified. Native conservative accounting remains Python-free; the SDK path is explicit developer configuration and not a mandatory service/dependency.

The helper checks the loaded SDK instance reference, context length, template probe hash and actual token-ID probe hash against a qualification profile. Reload/resize/probe mismatch downgrades its count instead of reusing an older qualification. UTF-8 stdio is explicit. Four process-wide helper slots, an 8 KiB response limit, ten-second exchange timeout and kill-on-drop bound helper work; failure falls back to native estimates. There is no automatic SDK/weight download. The helper uses already loaded handles, never `model()`/JIT loading.

## Allocation and writer integration

1. Resolve the loaded writer and output contract.
2. Compile mandatory context without optional memory/history before planner inference. Reject impossible mandatory input with 413.
3. If planning is enabled, resolve its own configured model and window, count its complete payload and reserve its output. Planner refusal is explicit soft fallback, not an oversized inference call.
4. Render the writer context with authorized selected evidence and complete history turns.
5. Remove lowest-ranked optional evidence first, then oldest whole history turns until the complete payload fits.
6. Reconstruct/count the final payload again after diagnostic measurements; a helper downgrade cannot leave a stale smaller count authorizing a larger payload.
7. Reconfirm model/window metadata immediately before dispatch.
8. Recompile for the actual normal/stream request and every beat, including effective reasoning and full prior surface. Never shrink the visible target to manufacture a fit.

Enabled planner guidance is retained whole at the compilation boundary, preserving the previous fixed-context semantics and its soft non-Canon designation; post-planner mandatory overflow returns 413. Existing planner response normalization is unchanged. Only whitelisted guidance/result fields enter the writer: planning budget/routing/provider diagnostics are excluded.

Streaming does not open a writer stream before final compilation. Normal, streaming, beats and ablation use the same contract. Terminal provider usage is compared with the compiled count/bound when supplied; disagreement is marked untrusted in diagnostics. Unknown/missing usage stays unknown. This observation does not retroactively claim that a previously sent request was exact.

For idempotent requests rejected before a writer call, the existing claimed run receives a terminal failed turn with `failure_phase="context_compilation"`; a repeated key returns the same failed owner rather than a second run. Retry after changing input/model configuration requires a new key, matching Phase C semantics. Pre-writer refusal reports `partial=false`; it does not invent partial prose. Per-beat overflow retains the completed prefix, its usage and failed/partial status. Existing startup recovery and cancellation checks remain intact. R3 retrieval still runs during analysis before the mandatory preflight; this gate prevents planner/writer inference, not the already-authorized query-embedding operation.

## Diagnostics and privacy

Successful reports include logical/loaded instance identity, effective/physical windows, counting method/confidence, safety/output reserves, whole mandatory/final cost, context remaining, retained/dropped evidence IDs and reasons, whole-turn trimming, authority/provenance items, retrieval readiness and stage timings. Component estimates/marginal differences are explicitly **non-additive**. System content, optional helper commands, API credentials and excluded passage text are not serialized in budget diagnostics.

`estimated_input_tokens` and `system_prompt_tokens` remain compatibility fields: the former mirrors the final count/bound with the explicit method alongside it; the latter is zero **additional** system reserve because system tokens are already included in the final full-payload count. New consumers should use `counting`, `final_input_tokens_or_bound` and `component_accounting`.

The report distinguishes no selected evidence, selected evidence that did not fit, observed R3 scope exclusion aggregates, semantic fallback and incomplete/unknown index coverage. It does not infer private evidence existence from an empty selection or reinterpret SQL-pruned R3 candidates. R3 owns that visibility boundary. No context compilation performs backfill, semantic reindexing or passage embedding.

Rejections carry a structured `input_budget` with counting state, known model/capacity, unchanged output reserve and overflow reason; errors never quote the rejected Canon/request/evidence. Developer diagnostics remain outside writer input.

## Qualification

### Tokenizer and real provider

The frozen `tests/fixtures/context_r4.json` covers English, Indonesian, Japanese, mixed long text, emoji, unusual punctuation, JSON/XML-like passages and escaped evidence delimiters. Each provisioned model was checked on six cases across reasoning off/on/omitted: **18 real SDK/REST comparisons per model**. SDK version: **1.5.0**. No model weights or SDK packages were downloaded.

| Provisioned writer | Loaded window | Theoretical maximum | Result |
|---|---:|---:|---|
| `qwen3.5-4b-uncensored-hauhaucs-aggressive` | **4096** | 262144 | Qualified template adapter matched all 18 actual REST input-token counts. |
| `qwen3-0.6b-heretic-abliterated-uncensored` | **2048** | 40960 | Raw template parity was not established; qualification remains false and accounting estimated. |

The first writer initially demonstrated SDK 24 versus REST 26 tokens with reasoning off. Its qualified adapter closes the thinking prefix and **counts the adjusted complete template**, rather than assuming raw SDK and REST formatting are identical. Profiles bind this behavior to that actual loaded instance/template/tokenizer. They are not portable exact-count certificates for other models or future sessions. Both models' 18 probes remained below the native byte estimate.

Real LM Studio normal, streaming and beat generation completed with selected evidence through the shared boundary. The recorded normal/stream counts were **887/887**, and the last beat **938**, each matching actual provider usage. Exact accounting here is text-only; images, tools/integrations, arbitrary provider preprocessors and other templates remain unqualified.

### Correctness matrix

The new unit/HTTP cases cover loaded versus theoretical capacity, lower request caps, resize/reload/ambiguity/unavailable models, volatile TTL, multilingual/emoji/structured text, mandatory overflow, memory before history, whole-turn trimming, selected-only provenance, accumulated decisions, planner debug exclusion, separate planner configuration, post-plan growth, unknown image cost, per-beat growth/partial failure, output reserves and preflight idempotency. Existing Phase A–C, legacy/shadow/hybrid and R0–R3 suites are retained. Mock providers now report realistic loaded-instance metadata; original behavioral assertions remain.

Final frozen-source validation passed **236 default tests** and **237 native-Bekko tests** across all targets, with zero failures. Strict Clippy (`-D warnings`) passed both configurations; release qualification examples built offline/locked. Three provisioned-artifact tests remain intentionally ignored in the ordinary native suite (R1 vector references, R2 benchmark and R3 live qualification); their prior results are preserved, not claimed as newly rerun. Ten grouped R4 test methods cover the cases above, including a long locked WCF and a Canon record exceeding the old preview cap. `git diff --check` passed. No frontend or platform-wide release qualification is claimed.

During final testing, the task-owned model expired its TTL. The old profile correctly downgraded to `conservative_estimated` after explicit reload. A new instance-bound profile passed all 18 reference comparisons before the final benchmarks. The final real generation rerun again matched 887/887/938 actual input tokens. Task-owned model instances are unloaded after qualification only when their SDK references still match; user-owned replacements are preserved.

### Performance methodology

`context_qualification` measures four controlled workloads—roomy, tight, Unicode pressure and mandatory overflow—in release mode, five repeats per arm. It checks actual usage on a successful representative payload per arm/case. The SDK process startup is included; no cross-request helper or model-info cache is claimed. The earlier failed benchmark encountered the differing-context/custom-ID 404 and remains separate; corrected reports preserve that history.

`context_preparation` uses the same source harness, logical input, six narrative evidence documents, fixed output reserves and a mock writer for the isolated R3/R4 release comparison. A separate real-provider run exercises normal, streaming and beats. Provider generation time and preparation telemetry are reported separately. The R3 snapshot is reconstructed from the checkpoint, and binary hashes identify each run. These are controlled engineering fixtures, not narrative continuity/quality or large-manuscript qualification. Critical Canon and latest continuity markers are asserted on every successful allocation case.

### Final release measurements

All compiler figures below use `compiler-release-final.json`: four workloads × five repetitions per arm, including five intentional mandatory-overflow refusals per arm. Percentiles use the median and nearest-rank p95. Successful-stage medians exclude refused requests. The mock preparation runs use ten repetitions per endpoint and separate frozen R3/R4 executables, without concurrent builds/tests. These are fixture measurements, not a production latency SLO.

| Compiler accounting | Compile p50 / p95 | Model lookup / revalidation medians | Token counting median | Packing/render median | Final payload recount median |
|---|---:|---:|---:|---:|---:|
| Native conservative | 12.90 / 17.81 ms | 6.51 / 6.47 ms | 0.055 ms | 0.212 ms | 0.001 ms |
| Qualified SDK subprocess | 978.64 / 1636.11 ms | 10.45 / 7.09 ms | 972.52 ms | 0.184 ms | 27.35 ms |

The SDK subprocess is reused within one compiler operation but started anew for each operation; its startup is included in counting. No model-info cache is used. Stage medians are not additive and the final recount is included in counting. Native estimates need no Python process.

| Workload / effective window | Native bound / actual tokens; kept / dropped | SDK verified / actual tokens; kept / dropped |
|---|---|---|
| Roomy / 4096 | 3533 / 796; 12 / 0 | 796 / 796; 12 / 0 |
| Tight / 1024 | 861 / 127; 0 / 12 | 796 / 796; 12 / 0 |
| Unicode pressure / 1024 | 861 / 127; 0 / 12 | 625 / 625; 1 / 11 |
| Mandatory overflow / 256 | 5/5 HTTP 413 | 5/5 HTTP 413 |

Actual input utilization is 19.4% of the roomy window; tight native/SDK utilization is 12.4%/77.7%, and Unicode native/SDK is 12.4%/61.0%. Output reserve and safety margins remain separately allocated. Critical Canon and latest continuity are retained on every successful case; this is a marker/contract assertion, not a literary-quality score. Conservative overestimation can remove all optional evidence in small windows. The qualified counter improves evidence retention but has substantial startup latency.

Compared with the character/3 **algorithm replay**, SDK counting uses the same 796 tokens in the roomy case, 55 more tokens in the tight case while retaining an additional passage, and **1407 fewer tokens** in Unicode pressure (2032 → 625). The old Unicode replay exceeds the 1024 window; R4 does not. Native replay comparisons are bounds, not actual token savings: bound reductions are 2435 tight and 5450 Unicode. Within R4, Unicode SDK packing saves 5161 verified tokens against its own full untrimmed request. Smaller is not always better: the tight case intentionally retains more useful evidence. Five intentional refusals among twenty samples per arm are a controlled 25% overflow frequency, not an operational failure rate.

| Endpoint | R3 preparation p50 / p95 | R4 native preparation p50 / p95 | R3 / R4 wall p50 |
|---|---:|---:|---:|
| Normal | 25 / 27 ms | 37.5 / 39 ms | 98.60 / 116.93 ms |
| Streaming | 25.5 / 27 ms | 38.5 / 40 ms | 111.80 / 131.58 ms |
| Two beats | 27 / 98 ms | 43 / 51 ms | 107.59 / 142.19 ms |

Both isolated runs retain all six evidence documents. R4 adds 12.5–16 ms median preparation on this fixture. Wall p95 R3/R4 is 149.10/165.11 ms normal, 117.01/138.91 ms streaming and 330.31/150.54 ms beats; small-sample tail variation is not evidence of a beat speedup. Real-provider SDK preparation takes 2135/1987/1968 ms and end-to-end wall time 3687.97/3286.70/4711.23 ms for normal/stream/beats respectively. Writer decoding and additional per-call compilation are outside preparation telemetry and inside wall time. Output caps remain 16 per call, 32 aggregate for two beats; the short output fixture validates integration, not story quality.

The compiler process resident peak rose from 10.79 to **16.13 MiB**, with private memory ending at **9.68 MiB**. This does not include the separately hosted LM Studio models or Python child peaks; it must not be reported as full-system RAM. Model files are approximately 3.38 GB and 396 MB; file sizes are not resident RAM measurements. Four simultaneous helper slots, output/timeout limits and existing inference residency controls bound admission, but sustained concurrency and total system peak RAM remain release-qualification work.

### Evidence and reproducibility

Local evidence is preserved in `.codex-audit/retrieval-r4-20261107/` (ignored): `writer-reference-final.json`, `writer-profile-final.json`, `reload-profile-downgrade.json`, `second-reference.json`, `compiler-release-final.json`, `preparation-r3-isolated.json`, `preparation-r4-isolated.json`, `preparation-r4-real-final.json`, `final-source-manifest.json`, `final-verification.json` and archived command logs. Earlier failed/corrected reports remain separate. Machine-specific qualification profiles are not shipped as portable certificates.

Frozen preparation executable SHA-256:

- R3: `f2a4aa78aa811b92d95bbc7d27a692412c2bf32187556ee7a93715fec01506d9`.
- R4: `ac5e13394cd621a5d24bad1900e10dd511ab41d6afe8e8d03b776717092aee10`.

Of the checkpoint's 44 files, **38 remain byte-identical**; six have intentional R4 edits. Other previously clean edited files remain recoverable from HEAD. The final source manifest matches the tested source, and database backups remain preserved.

## Configuration, operation and rollback

Default native conservative accounting needs no new configuration, Python or tokenizer service. It does require the writer to be explicitly loaded and its actual capacity visible through LM Studio's v1 API. Older servers/unloaded models fail clearly; R4 does not silently fall back to a theoretical or requested window.

```toml
[context_compiler]
safety_margin_tokens = 128 # also enforces at least 5% of the effective window

# Optional: only after qualifying the currently loaded instance.
# sdk_command = ["C:\\ArlineTools\\python.exe", "C:\\ArlineTools\\writer_sdk_counter.py", "--profile", "C:\\ArlineReports\\writer-profile.json"]

[deliberation]
# Optional independent planner; otherwise uses the selected writer model.
# model = "already-loaded-planner-id"
# context_length = 4096 # compiler cap; cannot exceed the reported loaded window
```

Do not use Bekko tokenizer files or automatically enable hybrid retrieval. Load the writer explicitly with the desired physical context through LM Studio before requesting a larger window. A request/configured context value is an allocation ceiling, not permission for R4 to reload a model. Unknown image costs return 422 until qualified support exists.

Reproduction, with already installed/provisioned artifacts and new output paths:

```powershell
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets
cargo test --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets -- -D warnings
cargo clippy --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --all-targets --features native-bekko -- -D warnings

uv run --no-project python crates/arline-runtime/examples/support/qualify_writer_tokens.py --model LOADED_INSTANCE --out C:\ArlineReports\reference.json --profile C:\ArlineReports\writer-profile.json
cargo run --release --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example context_qualification -- --out C:\ArlineReports\compiler.json --model LOADED_INSTANCE --sdk-python C:\ArlineTools\python.exe --profile C:\ArlineReports\writer-profile.json
cargo run --release --locked --offline --manifest-path crates/arline-runtime/Cargo.toml --example context_preparation -- --out C:\ArlineReports\preparation.json --repeats 10
```

Qualification does not load or download models. Its SDK must already be installed separately. Output files refuse overwrite. Profiles invalidate on reload/resize/probe changes; requalify rather than relabel an estimate exact. The default native path remains available if the optional helper is absent or fails.

There is **no database migration** for R4. To disable the optional SDK path, remove `context_compiler.sdk_command`; this retains native conservative safety. For full source rollback, restore the pre-R4 checkpoint into a separate checkout/data directory, preserving later user changes, then review the diff. Restoring R3 also restores its approximate context budgeting. Keep the R2/R3 backup procedures and independent semantic schema unchanged. Do not drop semantic tables, discard historical vectors, or overwrite the live database.

## Subsequent qualification

Keep hybrid retrieval opt-in. Broaden writer/template/runtime reference coverage, including multimodal costs and provider preprocessing, before making wider exact-count claims. A native in-process writer tokenizer would need writer GGUF/template parity and independent provider verification, not reuse of the embedding tokenizer. The optional helper's startup cost warrants a separately qualified persistent/in-process implementation before latency-sensitive default activation.

Future release work should evaluate real manuscripts, large contexts, Canon/continuity retention under pressure, sustained concurrency, context changes during long sessions, and platform behavior. R4 makes accounting and refusal explicit; it does not establish literary quality, universal tokenizer equivalence, universal mathematical byte bounds, Linux support or a new production latency SLO.
