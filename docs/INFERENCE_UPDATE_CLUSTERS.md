# Arline Studio — Inference update clusters

Prepared by Opheline · 23 October 2026

Status: implementation roadmap based on supplied specifications and local static inspection. U1 adds generation timing, provider-stat normalization and an isolated benchmark runner; see [the profiling contract](INFERENCE_PROFILING.md) and [benchmark usage](INFERENCE_BENCHMARK.md). U2 implements [INF-06/07 routing](INFERENCE_U2_VALIDATION.md) and [INF-09 output budgets](INFERENCE_OUTPUT_BUDGET.md). INF-10 and U3–U7 remain planned or evidence-gated. Original static observations below describe the pre-implementation baseline.

The supplied C01–C05 remain useful technical categories. The seven U-clusters below define delivery ownership and dependencies. Every original INF ID has one owner; references from other clusters do not create duplicate implementations.

## Scope and evidence

- Input: `C:/Users/Revian/Downloads/Arline_Inference_Clusters_MD/`, including all seven supplied files. The combined document contains the index and C01–C05 verbatim after trimming outer whitespace.
- Baseline runtime inspected: `crates/arline-runtime`, matching the supplied package before implementation. Current U1/U2 changes are documented separately; baseline line references below are historical.
- Preserve Canon authority, branch/fork visibility, POV, privacy, user overrides, validation and local-first persistence in every cluster.
- Separate application preparation latency, server first-text latency, UI first-render latency, provider TTFT, decode throughput and total duration. String caching does not establish neural KV reuse.
- APORIA case: `.codex-audit/aporia/inference-update-clusters/`. Its local ledger retains the supplied roadmap and the static audit notes. Static observations establish planning boundaries, not measured performance benefits.

## Delivery clusters

| Cluster | Update | Owned feature IDs | Priority / trigger | Depends on |
|---|---|---|---|---|
| U1 | Measurement and reproducible baseline | INF-01–05 | P0: start here | Existing runtime |
| U2 | Generation routing, budgets and retry identity | INF-06, 07, 09, 10 | P0: extend existing behavior | U1 instrumentation; latency/quality baseline before changing defaults |
| U3 | Token budgeting and safe context reuse | INF-08, 11–14 | P0: budget and invalidation first; reuse defaults require evidence | U1; shared scope/revision contract |
| U4 | Stream finalization and persistence | INF-22, 23 | P0 correctness contract; batching is P1 and measurement-gated | U1; INF-23 before INF-22 |
| U5 | Model residency and GPU experiments | INF-17–21 | P1 when load/decode/VRAM measurements justify it; INF-21 experimental | U1; relevant provider capabilities |
| U6 | Provider capabilities and optional backend comparison | INF-16, 24, 25 | Small capability contract when needed; full second-backend work P2 | U1; demonstrated requirement beyond baseline |
| U7 | Prewarming and request scheduling | INF-15, 26 | P2: only after foreground behavior and reuse are understood | U3 and U4; U6 for backend cache controls |

### U1 — Measurement and reproducible baseline

**Update:** create the request/run identity at entry, before analysis; attach monotonic stage timings and normalized optional provider statistics. Record model residency and hardware metadata where observable. Supply fixed workloads with explicit cold/warm/cache conditions.

**Existing foundation:** run IDs, raw provider stats, model load controls and memory timing exist. The generation run ID is currently allocated after preparation, so it cannot identify the whole request from entry. There is no complete generation-stage profile in the inspected boundary.

**Touchpoints:** `generation.rs:596–622, 661–663`, `analysis.rs`, `foundation/memory.rs`, `models.rs:517–533`; frontend `api.ts:376–380` and `views/ChatView.tsx:462–474` only for client timing correlation. Server timings alone cannot prove button-to-visible-text latency.

**Done when:** one identity links preparation, provider request, first text, completion and persistence; absent provider/GPU metrics remain null/unknown; benchmark runs retain configuration, output length, cache state and outcome. Keep benchmark artifacts outside Canon data. Instrumentation must preserve text and request semantics.

### U2 — Generation routing, budgets and retry identity

**Update:** add task-aware `auto/fast/deep` selection around the current optional planning pass; preserve explicit overrides. Extend the current output/reasoning budgets consistently across stream, single, beat and deliberation paths. Add explicit retry idempotency with atomic ownership of a request key and a defined replay/in-progress response.

**Existing foundation:** `deliberation_mode=on/off` and a disabled-by-default configuration already exist (`analysis.rs:242–264`). A call to `deliberate()` does not imply an extra neural request. Visible-output and reasoning-reserve budgets already exist (`generation.rs:215–247, 505–564`). Generation still creates fresh run/turn identities for each call.

**Order:** INF-06 + INF-07 together → INF-09 → INF-10. Idempotency can proceed independently once its storage contract is defined; it does not require a scheduler.

**Current slice:** INF-06/07 provide legacy `on/off` compatibility, opt-in `auto/fast/deep`, shared preparation/validation and routing telemetry. INF-09 adds opt-in task budgets, explicit-limit precedence, exact beat totals, separate reasoning/planner accounting and observed/estimated cutoff reporting. Fixed remains the budget default; current planning defaults also remain unchanged. INF-10 retry deduplication is pending, so U2 as a whole remains incomplete.

**Done when:** simple tasks avoid optional planning when appropriate, deep/explicit instructions remain honored, both generation endpoints preserve validation and scope, and concurrent retries share one run. Intentional creative regeneration receives a fresh request key. Compare latency at comparable output length and assess continuity/POV/Canon quality before changing routing defaults.

### U3 — Token budgeting and safe context reuse

**Update:** budget the final provider input, then introduce one shared dependency fingerprint/invalidation contract and two distinct cache payloads: deterministic analysis snapshots and compiled context. Experiment with stable-first serialization only after scope and token accounting are explicit.

**Existing foundation:** `analysis_cache` is UUID-keyed run/bundle storage (`analysis.rs:1661–1686`). WCF has deterministic sections, pruning and a declared whitespace estimate with a fixed 4096 budget (`analysis/wcf.rs:50–65, 107–161`). History is prepended during preparation (`generation.rs:1432–1434`). These do not establish reusable compiled context or provider KV hits.

**Order:** INF-14 → common revision/scope identity → INF-08 + INF-12 → INF-11 + INF-13. Tokenizer access can use a small capability contract from U6; unavailable exact counting needs a clearly labeled conservative fallback.

**Done when:** the final prompt plus output/reasoning reserve fits the effective context window; Canon/LOCKED/UNKNOWN/POV rules survive pruning; branch/fork/permission/source/memory revisions invalidate affected entries; model/tokenizer/template/serializer changes invalidate relevant compiled artifacts; caches have size/eviction bounds. Report estimated token-prefix reuse separately from backend-confirmed hits. Keep chronological facts in order and test serializer authority/quality before enabling it by default.

### U4 — Stream finalization and persistence

**Update:** define one finalization contract for complete, error, cancel and disconnect, including persistence failures. Then coalesce checkpoints while forwarding ordered text deltas promptly.

**Existing foundation:** streaming writes accumulated text before yielding each answer delta (`generation.rs:647–648`); store updates open SQLite connections (`store.rs:76, 275`). `CancellationGuard` performs best-effort asynchronous status persistence (`generation.rs:35–59`), and the final write result is discarded (`generation.rs:673`). These are observable paths; their latency impact has not been measured.

**Order:** INF-23 → INF-22. Once buffering exists, cancellation must retain and flush the buffered text as well as status. Specify the tolerated checkpoint-loss window before selecting a flush interval.

**Done when:** progressive output stays ordered, successful completion is consistent with persistence outcome, cancellation/error retain valid partial output, and restart/recovery behavior matches the declared durability contract. Extend existing stream/disconnect/failure tests. Adopt batching only if write counts/latency improve without violating recovery; do not infer OS/power-loss durability from client-disconnect tests.

### U5 — Model residency and GPU experiments

**Update:** reuse compatible loaded instances and apply conservative eviction; benchmark offload, available quantizations and supported KV-memory settings. Consider speculative decoding separately after measuring its overhead and benefit.

**Existing foundation:** loaded instances, GPU ratio, context and Flash Attention controls already exist (`models.rs:517–645`). Explicit reload currently unloads instances; this alone is not evidence of unwanted reloads during scene switching. Trace actual load triggers before adding residency policy.

**Order:** INF-17 if loading is costly; INF-18/19/20 when decode or VRAM is limiting; INF-21 last and experimental. These branches do not need to wait for every U2/U3 feature. Provider-specific controls require verified capabilities from U6.

**Done when:** results identify actual GPU/VRAM, model file, quantization, backend, context, sampling and output length; compare cold/warm latency, throughput, memory, failures and narrative quality. Retain current defaults if a candidate fails the workload gate. Hardware/model availability remains unverified in this planning task.

### U6 — Provider capabilities and optional backend comparison

**Update:** separate capability reporting, request construction, stream/result normalization, usage, cancellation and supported cache controls from orchestration as needed.

**Existing foundation:** LM Studio integration and a model capability object exist. Stream and non-stream paths already preserve raw output/statistics, but parsing and final-stat handling are separate (`generation.rs:383–564, 625–681`). Start with shared normalization and a small capability data contract; a full provider framework is not a prerequisite for collecting timings.

**Order:** minimal INF-24 capability/stat contract when U1/U3 needs it → full interface when a second backend has a concrete purpose → INF-16 where actual cache controls exist → INF-25 optional comparison. Cache reuse may be available within the baseline provider without migrating it; confirm support and observability before claiming it.

**Done when:** unsupported options fail or fall back explicitly, baseline behavior remains covered, and any llama.cpp comparison controls model/quantization/template/sampling/context/output as far as possible. Adopt another backend only after a documented baseline shortfall and fair benchmark. Keep neural KV state provider-owned.

### U7 — Prewarming and request scheduling

**Update:** begin with cancelable CPU context preparation while idle; add resource-limited fair scheduling only if overlapping foreground/background requests make it useful.

**Order:** INF-15 CPU preparation after U3 invalidation works → measure interference → INF-26 if concurrency needs it. GPU warmup/prefix grouping additionally requires U6 capabilities and demonstrated reusable state.

**Done when:** scene/branch changes cancel obsolete work, foreground writing takes priority, queues have bounded concurrency and no starvation, and single-user latency does not regress. Do not create a scheduler merely to implement retry deduplication. Default to the simple path if concurrency/reuse benefit is absent.

## Feature ownership manifest

| ID | Original feature | Owner |
|---|---|---|
| INF-01 | Stage Latency Profiler | U1 |
| INF-02 | Provider Performance Collector | U1 |
| INF-03 | Cold/Warm Benchmark | U1 |
| INF-04 | VRAM & Model Residency Diagnostics | U1 |
| INF-05 | Generation Benchmark Suite | U1 |
| INF-06 | Adaptive Deliberation | U2 |
| INF-07 | Fast Generation Path | U2 |
| INF-08 | Reusable Analysis Snapshot | U3 |
| INF-09 | Output Budget Optimization | U2 |
| INF-10 | Generation Request Deduplication | U2 |
| INF-11 | Stable-First Prompt Serializer | U3 |
| INF-12 | Versioned Context Cache | U3 |
| INF-13 | Prefix Reuse Diagnostics | U3 |
| INF-14 | Token-Aware Context Budget | U3 |
| INF-15 | Context Prewarming | U7 |
| INF-16 | KV Cache-Aware Adapter | U6 |
| INF-17 | Resident Model Policy | U5 |
| INF-18 | GPU Offload Optimizer | U5 |
| INF-19 | Quantization Benchmark | U5 |
| INF-20 | KV Memory Tuning | U5 |
| INF-21 | Speculative Decoding | U5 |
| INF-22 | Batched Streaming Persistence | U4 |
| INF-23 | Durable Cancellation Flush | U4 |
| INF-24 | Provider Adapter Interface | U6 |
| INF-25 | llama.cpp Benchmark Adapter | U6 |
| INF-26 | Cache-Aware Scheduling | U7 |

## Recommended first implementation slice

1. Add INF-01/02 request-entry identity, stage timers and shared optional statistics. Extend existing generation paths; avoid a second runtime or large provider refactor.
2. Establish INF-03/05 reproducible workloads and capture INF-04 residency/environment metadata, including explicit unavailable values. Measure both application and provider boundaries.
3. Add INF-14 final-input budgeting and define INF-23 persistence/cancellation outcomes. These correctness contracts support later optimizations and can be developed independently.
4. Use the baseline to choose the next performance change: INF-06/07 for expensive optional planning, INF-08/12 for repeated deterministic preparation, INF-11/13 for demonstrated prefix opportunities, INF-22 for meaningful persistence overhead, or INF-17–20 for load/decode/VRAM limitations.
5. Deliver INF-09/10 as independent budget/retry contracts; retain INF-15/16/21/25/26 as conditional work until their prerequisites and expected benefit are evidenced.

This changes the original phase ordering: cancellation precedes batching, token accounting precedes token-prefix evaluation, shared invalidation precedes both reusable caches, and residency/persistence work does not require all of C02/C03. A minimal provider capability contract can arrive early; a full alternate-backend abstraction remains conditional.

## Validation to run during implementation

Existing test anchors: `tests/planning_toggle.rs`, `tests/context_scope.rs`, `tests/generation_parity.rs`, and `tests/generation_http.rs` under `crates/arline-runtime`.

Add focused checks only where the new contract requires them: routing overrides, final-input budget boundaries/multilingual inputs, scope/revision cache invalidation, concurrent retry identity, buffered cancel/error finalization and unsupported capabilities. Inspecting the existing tests in this planning task does not establish that they currently pass.

Performance acceptance requires baseline/candidate runs on the same declared workload and environment, with comparable output length and explicit quality/continuity checks. No speedup or default-setting recommendation is supported by this static plan alone.
