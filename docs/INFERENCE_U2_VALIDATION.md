# Adaptive deliberation and fast generation

Implemented by Opheline · 23 October 2026 · Local changes only

This document records the INF-06/07 slice from [the update roadmap](INFERENCE_UPDATE_CLUSTERS.md). [INF-09 output-budget optimization](INFERENCE_OUTPUT_BUDGET.md) was implemented subsequently; INF-10 request deduplication remains pending. INF-06/07 selects the existing optional planner; that slice itself does not change model reasoning, output budgets, caching, provider choice or GPU settings. Existing installations retain their saved planning behavior. Validation counts below are the historical INF-06/07 checkpoint.

## Mode contract

Both `/api/generate` and `/api/generate/stream` accept `deliberation_mode`:

| Mode | Planning behavior |
|---|---|
| `off` | Explicitly disables the optional planner, including for author commands; the writer still receives the author request. |
| `on` | Legacy behavior: always requests planning. |
| `deep` | Always requests planning. |
| `fast` | Skips optional planning; parsed `/intuition` or `/alternatives` commands still request planning. |
| `auto` | Uses the conservative task rules below; parsed author commands request planning. |

Precedence is a non-null request mode, then saved `deliberation.mode`, then legacy `deliberation.enabled` mapped to `on/off`. A null request means unspecified. Invalid modes or non-string request values fail with HTTP 400 before analysis or provider calls. A legacy `enabled=false` installation remains off until explicitly changed.

The settings API accepts flat `deliberation_mode` or nested `deliberation.mode`. Saving an explicit mode synchronizes the legacy boolean. An older client sending only `deliberation_enabled` or nested `deliberation.enabled` replaces any saved adaptive mode with `on/off`. Invalid settings are rejected without writing the file. API `planning_enabled` is a compatibility indicator for `on/auto/deep`; consult each run's routing decision for actual planner selection.

Settings → Generation and Chat → Run settings expose Off/Auto/Fast/Deep. Legacy `on` displays as Deep while retaining its original value until changed. Chat changes apply to the next request; Save settings persists the current mode. Frontend explicit mode overrides take precedence over legacy boolean overrides, which take precedence over saved configuration.

## Auto rules and shared preparation

Auto requests planning for Story Lab, beat generation, continuity-review prefixes in English/Indonesian, scene/interaction/revision command profiles, unresolved analysis or references, UNKNOWN records, invalid WCF diagnostics, more than two references, or prompts longer than 80 whitespace words or 800 Unicode characters. Remaining short continuations and bounded dialogue use the fast route. This is a deterministic heuristic, not a model-based complexity or quality estimate.

Only commands parsed at the start of a trimmed prompt line can trigger the author-command override. An inline quoted mention does not become a command. The whole parsed command stack is inspected, so a later command cannot erase an earlier `/intuition` or `/alternatives` request. Catalog planner/output metadata now survives directive parsing.

Every route still performs scope checks, analysis, configured retrieval, writer-context composition, history handling, writer generation, output validation and persistence. Fast skips only the optional planning pass. Single, stream and beat paths share this preparation boundary; a beat run plans once before its writer calls. Existing planner fallback behavior remains intact.

The scope regression fixture exposed an existing handoff defect: rendering derived writer context replaced the previously scope-filtered workspace WCF, dropping selected Canon before generation. The handoff now retains that workspace context alongside the derived rendering. Tests verify active-branch Canon reaches the writer, inactive-branch and foreign-project content does not, and foreign pinned references fail before a provider call. This repair changes writer input when scoped workspace context exists. The existing 4096 whitespace-token WCF budget applies to the derived rendering, not the final concatenated input; `wcf_metadata.budget_scope` and `workspace_context_characters` make that distinction explicit. Final-input token budgeting remains INF-14 work.

## Decision evidence

The response and cached analysis bundle contain `deliberation.routing` version `1.0` with requested/effective mode, mode source, planning flag, task, reason and preparation-fast-path flag. Effective mode is `deep` when planning is selected and `fast` otherwise; requested `off` is retained separately. A provider error can still cause the existing planner fallback, so effective `deep` does not prove successful model planning.

`stats.inference.metadata` includes `deliberation_requested_mode`, `deliberation_effective_mode`, `deliberation_route_reason`, `generation_task` and `preparation_fast_path`. Routing diagnostics are appended after composing the writer input and contain no prompt/context text. Planning latency remains in `durations_ms.deliberation`; writer call counts exclude planner calls, as in U1.

## Validation

The following checks passed against this implementation:

- Desktop runtime suite: **160 passed, 0 failed**, including 71 unit tests and HTTP integration suites.
- Benchmark example: **3 passed**; the CLI accepts adaptive modes and an `auto` dry run passed without contacting the provider.
- Desktop all-targets Clippy with `-D warnings`: passed.
- Frontend `npm run typecheck -- --pretty false`: passed.
- Routing tests cover legacy modes, saved/request precedence, null/invalid values, stacked author commands, inline quoted mentions, complex/UNKNOWN contexts, Story Lab, beats and multilingual continuity detection.
- HTTP tests exercise both generation endpoints, actual planner/writer call counts, preserved validation fields and absence of routing diagnostics in the writer prompt. Scope tests cover Canon and reference isolation.
- Browser functional QA on an isolated SQLite workspace: legacy enabled displayed Deep; Auto saved successfully and survived reload; the Chat selector selected Fast; a streamed UI generation completed and its rendered Inspector statistics showed requested/effective `fast`, disabled planning, one writer call and `preparation_fast_path=true`.

Runtime commands from the repository root:

```powershell
cargo test --locked --offline --features desktop --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 --tests
cargo clippy --locked --offline --features desktop --all-targets --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2 -- -D warnings
cargo test --locked --offline --features desktop --example inference_benchmark --manifest-path crates/arline-runtime/Cargo.toml --target-dir .codex-audit/native-target2
npm --prefix frontend run typecheck -- --pretty false
```

Local raw evidence is retained under `.codex-audit/inference-u2-20261023/`: live comparison script and JSON with synthetic outputs, UI snapshots and Inspector telemetry, isolated QA configuration, and copied test/Clippy logs. Browser QA used Vite on loopback with the original browser Host forwarded to the isolated runtime; an initial proxy-origin mismatch was corrected in the QA helper. Screenshot capture failed, so browser evidence is functional DOM/state evidence rather than a visual-layout assessment. The real workspace and model residency settings were not changed.

## Exploratory model observations

Sixteen non-streaming samples used the already resident local `qwen3.5-4b-uncensored-hauhaucs-aggressive` model: two synthetic workloads × `on/fast/auto/deep` × two repetitions, with reversed mode order in the second repetition. Writer reasoning was off, temperature 0.2 and output limit 160 tokens; the existing planner limit was 700. Requests used fresh sessions in an isolated workspace with automatic memory context disabled. Provider cache state and seed were uncontrolled.

| Requested mode / actual route | Samples | Median preparation (ms) | Median planning (ms) | Median server total (ms) |
|---|---:|---:|---:|---:|
| `on` / planned | 4 | 5613 | 5611 | 7517 |
| `deep` / planned | 4 | 6072 | 6070 | 7933 |
| `fast` / skipped, short prompt | 2 | 1 | 0 | 1143 |
| `fast` / planned, `/alternatives` | 2 | 5779 | 5777 | 8633 |
| `auto` / skipped, short prompt | 2 | 2 | 0 | 991 |
| `auto` / planned, `/alternatives` | 2 | 5485 | 5483 | 8290 |

All 16 routing decisions matched the expected contract. These observations demonstrate removal of the optional planning stage for eligible requests. They do not establish an end-to-end speedup at matched output length: short outputs varied from 42–60 provider tokens, alternatives from 62–108, and each cell has very few samples. The separate streamed browser sample also included substantial persistence/backpressure time, which fast routing does not address.

Manual output review found **0/8** short outputs satisfying the complete requested two-sentence, 45–65-word contract; seven contained three sentences and one had two sentences but only 34 whitespace words. Seven ended with exact `She waited.`. All eight alternatives outputs contained three numbered one-sentence options, but some added speculative objects or actions. The built-in validator reported all 16 valid, demonstrating that its current checks do not cover these complete author constraints. This slice does not establish narrative-quality equivalence or comprehensive Canon/POV safety. Planning defaults remain unchanged pending stronger quality evidence.
